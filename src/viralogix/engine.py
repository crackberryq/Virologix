"""Explicit operations executed by a detached, single-workspace worker."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, urlopen
from .catalog import PIPELINES, api, supported
from .controllers import controller_requirements, controller_check_code
from .store import Store, now


class Cancelled(Exception):
    pass


def find_conda(store):
    configured = store.get("settings", "conda", "")
    candidates = [configured, os.environ.get("CONDA_EXE"), shutil.which("conda"),
                  store.home / "tools/miniforge/bin/conda"]
    candidates += [Path.home() / p / "bin/conda" for p in ("miniforge3", "miniconda3", "anaconda3", "mambaforge")]
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return str(Path(candidate).resolve())
    return None


def doctor(store):
    conda = find_conda(store)
    disk = shutil.disk_usage(store.home)
    return {"system": platform.system(), "architecture": platform.machine(), "python": platform.python_version(),
            "git": shutil.which("git"), "conda": conda, "workspace": str(store.home),
            "free_gb": round(disk.free / 2**30, 1), "cpus": os.cpu_count(),
            "pipeline_platform_supported": platform.system() == "Linux"}


def launch_worker(store):
    if platform.system() != "Linux":
        raise RuntimeError("Pipeline execution requires Linux or WSL2. Launch Virologix inside WSL.")
    with (store.home / "logs/worker.log").open("ab") as log:
        env = dict(os.environ)
        owner = env.pop('VIRALOGIX_DESKTOP_SESSION', None)
        args = ['--desktop-owner', owner] if owner else []
        subprocess.Popen([sys.executable, "-m", "viralogix.worker", "--home", str(store.home), *args],
                         stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True, env=env)


def enqueue(store, kind, payload):
    if kind not in {"install", "connect", "bootstrap", "check", "workflow", "smoke", "workstation", "app_update", "environments", "database_download"}:
        raise ValueError("Unknown operation")
    if platform.system() != "Linux":
        raise RuntimeError("Run this app inside Linux or WSL2 to execute jobs.")
    from .updates import assert_current
    assert_current(store)
    if kind == "workflow":
        from .runs import validate_launch
        validate_launch(store, payload["run_id"], payload["action"])
    jid = store.submit(kind, payload)
    launch_worker(store)
    return jid


class Context:
    def __init__(self, store, job, lock_fd=None, environment_fd=None):
        self.store, self.job, self.lock_fd = store, job, lock_fd
        self.lock_fds = tuple(fd for fd in (lock_fd, environment_fd) if fd is not None)
        self.log = store.log_path(job["id"]).open("a", buffering=1)
        self.observer = None
        self.observer_warned = False
        try:
            from .telemetry import Recorder
            self.observer = Recorder(store, job)
        except Exception:
            self.observation_warning()

    def observation_warning(self):
        if not self.observer_warned:
            self.observer_warned = True
            try:
                self.write("Resource observation is unavailable or incomplete; job execution continues.")
            except Exception:
                pass

    def observe(self, method, *args):
        # Observation must never change a command's result or prevent cancellation.
        if self.observer is not None:
            try:
                getattr(self.observer, method)(*args)
            except Exception:
                try:
                    self.observer.record['observer_errors'] = True
                except Exception:
                    pass
                self.observation_warning()

    def write(self, message):
        self.log.write(str(message) + "\n")

    def check_cancel(self):
        self.refresh_desktop_cancel()
        if self.store.job(self.job["id"])["cancel"]:
            raise Cancelled("Stopped by user")

    def refresh_desktop_cancel(self):
        from .desktop import owner_cancelled
        if self.job['kind'] != 'app_update' and owner_cancelled(self.store, self.job['id']):
            self.store.cancel(self.job['id'])

    def command(self, argv, cwd=None, extra_env=None, stdout=None, *, timeout=None, stop_after=None):
        import shlex
        self.check_cancel()
        self.write("$ " + shlex.join([str(x) for x in argv]))
        env = os.environ.copy()
        env.update({"PYTHONUNBUFFERED": "1", "PYTHONNOUSERSITE": "1"})
        env.update(extra_env or {})
        started_stop = None
        command_started = time.monotonic()
        timed_out = False
        proc = subprocess.Popen([str(x) for x in argv], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                stdout=stdout if stdout is not None else self.log,
                                stderr=self.log if stdout is not None else subprocess.STDOUT, start_new_session=True,
                                pass_fds=self.lock_fds)
        self.store.put("processes", self.job["id"], {"pid": proc.pid, "started": now()})
        try:
            self.observe("begin_command", proc, argv[0])
            while proc.poll() is None:
                self.refresh_desktop_cancel()
                elapsed_command = time.monotonic() - command_started
                timed_out = timed_out or (timeout is not None and elapsed_command >= timeout)
                if timed_out:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                if self.store.job(self.job["id"])["cancel"] or (stop_after is not None and elapsed_command >= stop_after):
                    if started_stop is None:
                        started_stop = time.monotonic()
                        self.write("Stopping process group gracefully (SIGINT)…")
                        try:
                            os.killpg(proc.pid, signal.SIGINT)
                        except ProcessLookupError:
                            pass
                    elapsed = time.monotonic() - started_stop
                    if elapsed > 30:
                        try:
                            os.killpg(proc.pid, signal.SIGKILL if elapsed > 60 else signal.SIGTERM)
                        except ProcessLookupError:
                            pass
                self.observe("tick")
                time.sleep(0.25)
            if timed_out:
                self.check_cancel()  # A concurrent user stop keeps its cancellation status.
                raise TimeoutError("Software check command exceeded its time limit; its process group was stopped.")
            if started_stop is not None:
                # The session leader can exit before its children. This group
                # was created by this command; never signal unrelated WSL PIDs.
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                raise Cancelled("Stopped by user; inspect the log before resuming")
            if proc.returncode:
                raise RuntimeError(f"Command exited with code {proc.returncode}; see the job log")
        finally:
            self.observe("end_command")
            self.store.put("processes", self.job["id"], {"pid": None, "finished": now()})


def controller_key(tool, content):
    context = "|".join((tool, platform.system(), platform.machine(), "conda-controller-v1")).encode()
    return hashlib.sha256(context + b"\0" + content).hexdigest()[:20]


def check_controller(ctx, conda, prefix, tool, requirements):
    if tool=='flupop':
        ctx.command([str(Path(prefix)/'bin/python'),'-c',controller_check_code(tool,requirements)+'\nimport flupop\n'])
        ctx.command([str(Path(prefix)/'bin/python'),'-m','pip','check'])
        return
    if not conda or not prefix:
        raise RuntimeError("Set up this pipeline's runner before checking it.")
    code = controller_check_code(tool, requirements)
    ctx.command([conda, "run", "--no-capture-output", "-p", str(prefix), "python", "-c", code])
    ctx.command([conda, "run", "--no-capture-output", "-p", str(prefix), "snakemake", "--version"])


def inherited_cache(store, tool):
    previous = store.get('installs', store.get('settings', 'active-' + tool), {})
    return previous.get('rule_cache') or str(store.home / 'envs' / tool)


def install(ctx):
    store, payload = ctx.store, ctx.job["payload"]
    tool, version = payload["tool"], payload["version"]
    spec = PIPELINES[tool]
    commit = version["commit"]
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Installation requires an exact 40-character Git commit")
    if not shutil.which("git"):
        raise RuntimeError("Git is missing. Install Git through your Linux distribution and retry.")
    key = tool + "-" + commit
    target = store.home / "sources" / key
    if not target.exists():
        temporary = Path(tempfile.mkdtemp(prefix=key + "-", dir=store.home / "sources"))
        try:
            ctx.command(["git", "init", str(temporary)])
            ctx.command(["git", "-C", str(temporary), "remote", "add", "origin", f'https://github.com/{spec["repo"]}.git'])
            ctx.command(["git", "-C", str(temporary), "fetch", "--depth", "1", "origin", commit])
            ctx.command(["git", "-C", str(temporary), "checkout", "--detach", "FETCH_HEAD"])
            if subprocess.check_output(["git", "-C", str(temporary), "rev-parse", "HEAD"], text=True).strip() != commit:
                raise RuntimeError("Downloaded source does not match the selected commit")
            temporary.rename(target)
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
    if subprocess.check_output(["git", "-C", str(target), "status", "--porcelain"], text=True).strip():
        raise RuntimeError("Installed source has local changes; preserve them and choose a clean installation.")
    from .setup_state import mode
    setup_mode = mode(store, tool, commit)
    record = store.get("installs", key, {"id": key, "tool": tool, "source": str(target), "version": version,
                                        "created": now(), "controller": None, "ready": False,
                                        "rule_cache": inherited_cache(store, tool)})
    record.setdefault('setup_mode', setup_mode)
    record.setdefault('setup_phase', 'source')
    record.setdefault('rule_cache', str(store.home / 'envs' / tool))
    store.put("installs", key, record)
    if not supported(tool, commit, store):
        ctx.write("Source downloaded. This version needs an adapter compatibility review before managed execution.")
        return
    from .release_contract import preflight
    preflight(store, tool, commit, target)
    record['setup_phase'] = 'runner'
    store.put('installs', key, record)
    prepare_controller(ctx, record, repair=payload.get("repair", False))
    if record.get('setup_mode') == 'first_install' and not record.get('setup_completed'):
        prepare_first_install(ctx, record)


def prepare_first_install(ctx, record):
    if record['tool']=='flupop':
        record.update(setup_phase='complete',setup_completed=now())
        ctx.store.put('installs',record['id'],record)
        return
    from . import maintenance
    rows = maintenance.recipes(record)
    if not rows:
        raise RuntimeError('No tool environment recipes found; first setup cannot be completed.')
    record['setup_phase'] = 'environments'
    ctx.store.put('installs', record['id'], record)
    ctx.write('First installation: preparing and checking tool environments. Databases remain a separate setup step.')
    original = ctx.job['payload']
    try:
        ctx.job['payload'] = maintenance.environment_request(ctx.store, record['id'], [r['id'] for r in rows], 'install')
        maintenance.execute_environments(ctx)
    finally:
        ctx.job['payload'] = original
    record.update(setup_phase='complete', setup_completed=now())
    ctx.store.put('installs', record['id'], record)
    ctx.write('First installation complete. Review databases and validate a run before execution.')


def prepare_controller(ctx, record, repair=False):
    if record['tool']=='flupop':
        from .flupop_adapter import prepare_controller
        return prepare_controller(ctx,record,repair)
    store = ctx.store
    tool, target = record["tool"], Path(record["source"])
    spec = PIPELINES[tool]
    record.update(ready=False)
    store.put("installs", record["id"], record)
    content = (target / spec["environment"]).read_bytes()
    requirements = controller_requirements(content)
    record["controller_requirements"] = requirements
    store.put("installs", record["id"], record)
    ctx.write(f"Required runner: Python {requirements['python']}; Snakemake {requirements['snakemake']}.")
    conda = find_conda(store)
    if not conda:
        ctx.write("Installing workspace-local Conda to prepare the selected release's runner.")
        bootstrap(ctx)
        conda = find_conda(store)
        if not conda:
            raise RuntimeError("Local Conda setup did not produce an executable. Inspect the setup log.")
    digest = controller_key(tool, content)
    base = store.home / "controllers" / (tool + "-" + digest)
    prefix = Path(record["controller"]) if record.get("controller") and record.get("controller_digest") == digest else base
    if repair and prefix.exists():
        prefix = Path(str(base) + "-repair-" + ctx.job["id"][4:])
        ctx.write("Preparing a fresh controller; the previous environment is retained.")
    if not prefix.exists():
        ctx.write("Installing the selected release's Python and Snakemake in a separate runner.")
        ctx.command([conda, "env", "create", "--yes", "--prefix", str(prefix), "--file", str(target / spec["environment"])])
    else:
        ctx.write("Checking the existing controller before reuse.")
    try:
        check_controller(ctx, conda, prefix, tool, requirements)
    except Cancelled:
        raise
    except Exception:
        record.update(ready=False)
        store.put("installs", record["id"], record)
        raise RuntimeError(f"Runner check failed for Python {requirements['python']} / Snakemake {requirements['snakemake']}. "
                           "Inspect the log; use Repair to create a separate controller.") from None
    record.update(controller=str(prefix), conda=conda, controller_digest=digest, controller_origin="managed", ready=True, checked=now())
    store.put("installs", record["id"], record)
    store.put("settings", "active-" + tool, record["id"])
    ctx.write("Runner ready. Matching tool environments are reused automatically. Use Install environments in Install & update to prepare missing tools.")


def connect_existing(ctx):
    """Snapshot committed source locally; never edit the user's checkout or env."""
    from .local import inspect_installation, local_path
    store, payload = ctx.store, ctx.job["payload"]
    tool = payload["tool"]
    info = inspect_installation(payload["path"], tool, store)
    if info["commit"] != payload["commit"]:
        raise ValueError("The checkout changed since inspection. Inspect it again before connecting.")
    if not info["supported"]:
        raise ValueError("This source commit needs an adapter review before it can be connected for runs.")
    key = tool + "-local-" + hashlib.sha256((info["path"] + info["commit"]).encode()).hexdigest()[:20]
    target = store.home / "sources" / key
    if not target.exists():
        temporary = Path(tempfile.mkdtemp(prefix=key + "-", dir=store.home / "sources"))
        try:
            ctx.command(["git", "init", str(temporary)])
            ctx.command(["git", "-C", str(temporary), "fetch", "--depth", "1", "--no-tags", "--no-recurse-submodules",
                         info["path"], info["commit"]])
            ctx.command(["git", "-c", "core.hooksPath=/dev/null", "-C", str(temporary), "checkout", "--detach", "FETCH_HEAD"])
            temporary.rename(target)
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
    actual = subprocess.check_output(["git", "-C", str(target), "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.check_output(["git", "-C", str(target), "status", "--porcelain"], text=True).strip()
    if actual != info["commit"] or dirty:
        raise ValueError("The local source snapshot changed. Choose a clean installation.")
    from .release_contract import preflight
    preflight(store, tool, info["commit"], target)
    previous = store.get("installs", key)
    prefix = local_path(payload["controller"]) if payload.get("controller") else None
    cache = local_path(payload["rule_cache"]) if payload.get("rule_cache") else None
    if prefix and (not (prefix / "conda-meta").is_dir() or not (prefix / "bin/python").is_file()):
        raise ValueError("Select an existing Linux Conda environment folder, containing conda-meta and bin/python.")
    if cache and (not cache.is_dir() or not os.access(cache, os.W_OK)):
        raise ValueError("The selected Snakemake environment cache must be an existing writable folder.")
    record = {"id": key, "tool": tool, "source": str(target), "original_source": info["path"], "origin": "local",
              "version": {"id": "local:" + key, "ref": info["ref"], "commit": info["commit"], "kind": "local"},
              "created": previous["created"] if previous else now(), "controller": str(prefix) if prefix else None,
              "rule_cache": str(cache) if cache else inherited_cache(store, tool), "ready": False}
    if previous and previous.get("ready"):
        raise ValueError("This installation is already connected. Select it under Install & update.")
    store.put("installs", key, record)
    ctx.write("Source copied from local Git history; original configs, databases and results are untouched.")
    if info["modified"]:
        ctx.write("The original checkout has local edits. This snapshot uses its committed version. Import your settings in Configuration.")
    if prefix:
        conda = find_conda(store)
        if not conda:
            raise ValueError("Choose your Conda executable before connecting an environment.")
        requirements = controller_requirements((target / PIPELINES[tool]["environment"]).read_bytes())
        check_controller(ctx, conda, prefix, tool, requirements)
        record.update(ready=True, conda=conda, checked=now(), controller_origin="external",
                      controller_requirements=requirements)
        store.put("installs", key, record)
        store.put("settings", "active-" + tool, key)
        ctx.write("Connected: existing runner verified and reused. No environment was installed or updated.")
    else:
        prepare_controller(ctx, record)


def bootstrap(ctx):
    store = ctx.store
    existing = find_conda(store)
    if existing:
        ctx.write("Existing Conda found: " + existing)
        return
    machine = {"x86_64": "x86_64", "aarch64": "aarch64"}.get(platform.machine())
    if platform.system() != "Linux" or not machine:
        raise RuntimeError("Automatic Miniforge setup supports Linux x86_64/aarch64. Configure an existing Conda executable.")
    release = api("repos/conda-forge/miniforge/releases/latest")
    name = "Miniforge3-" + release["tag_name"] + "-Linux-" + machine + ".sh"
    assets = {asset["name"]: asset["browser_download_url"] for asset in release["assets"]}
    if name not in assets or name + ".sha256" not in assets:
        raise RuntimeError("Official release has no matching installer/checksum")
    destination = store.home / "tools/miniforge"
    if destination.exists():
        raise RuntimeError("An incomplete Miniforge folder exists. Inspect it or configure another Conda executable; it was not removed.")
    destination.parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as tmp:
        installer = Path(tmp) / name
        with urlopen(Request(assets[name + ".sha256"], headers={"User-Agent": "Virologix"}), timeout=60) as response:
            expected = response.read(4096).decode().split()[0].lower()
        if not re.fullmatch(r"[a-f0-9]{64}", expected):
            raise RuntimeError("Official Miniforge checksum file has an unexpected format")
        for attempt in range(1, 4):
            ctx.check_cancel()
            ctx.write(f"Downloading official installer, attempt {attempt}/3")
            req = Request(assets[name], headers={"User-Agent": "Virologix"})
            with urlopen(req, timeout=60) as response, installer.open("wb") as out:
                while chunk := response.read(1024 * 1024):
                    ctx.check_cancel()
                    out.write(chunk)
            actual = hashlib.sha256(installer.read_bytes()).hexdigest()
            if actual == expected:
                break
            ctx.write(f"Download did not match its checksum ({installer.stat().st_size} bytes). Retrying a fresh download.")
        else:
            raise RuntimeError("Miniforge checksum verification failed after three downloads; installer was not executed")
        ctx.write("Official Miniforge " + release["tag_name"] + "; SHA-256 " + actual)
        ctx.command(["bash", str(installer), "-b", "-p", str(destination)])
    store.put("settings", "conda", str(destination / "bin/conda"))
    ctx.write("Local Conda installed. No shell initialization was changed.")


def smoke(ctx):
    """Real orchestration check. No biological data or analysis tools."""
    store = ctx.store
    prefix = ctx.job["payload"].get("controller")
    conda = find_conda(store)
    if not prefix:
        ready = [item for item in store.all("installs") if item.get("ready")]
        if ready:
            prefix = ready[0]["controller"]
    if not prefix or not conda:
        raise RuntimeError("Set up a pipeline runner before the Snakemake smoke test.")
    folder = store.home / "runs" / ("smoke-" + ctx.job["id"][4:])
    folder.mkdir()
    (folder / "Snakefile").write_text('rule all:\n    input: "report.html"\n\nrule report:\n    output: "report.html"\n    run:\n        from pathlib import Path\n        Path(output[0]).write_text("<html><body><h1>Virologix live test passed</h1><p>A real Snakemake job created this report. No sample analysis was performed.</p></body></html>")\n')
    ctx.command([conda, "run", "--no-capture-output", "-p", prefix, "snakemake", "--cores", "1", "--directory", str(folder), "--snakefile", str(folder / "Snakefile")], cwd=folder)
    if not (folder / "report.html").is_file():
        raise RuntimeError("Smoke workflow returned without its expected report")
    store.put("smoke", ctx.job["id"], {"id": ctx.job["id"], "report": str(folder / "report.html"), "finished": now()})
    ctx.write("PASS — actual Snakemake process, durable log and HTML output verified.")


def execute(ctx):
    kind = ctx.job["kind"]
    if kind == "app_update":
        from .updates import install_update
        install_update(ctx)
    elif kind == "install":
        install(ctx)
    elif kind == "connect":
        connect_existing(ctx)
    elif kind == "bootstrap":
        bootstrap(ctx)
    elif kind == "check":
        record = ctx.store.get("installs", ctx.job["payload"]["installation"])
        if not record:
            raise ValueError("Installation no longer exists")
        try:
            if not supported(record["tool"], record["version"]["commit"], ctx.store):
                raise ValueError("This source version needs an adapter review.")
            from .release_contract import preflight
            preflight(ctx.store, record["tool"], record["version"]["commit"], record["source"])
            if ctx.job["payload"].get("repair") or ctx.job["payload"].get("setup"):
                prepare_controller(ctx, record, repair=ctx.job["payload"].get("repair", False))
                return
            requirements = controller_requirements((Path(record["source"]) / PIPELINES[record["tool"]]["environment"]).read_bytes())
            check_controller(ctx, find_conda(ctx.store), record["controller"], record["tool"], requirements)
            record.update(ready=True, checked=now(), controller_requirements=requirements)
        except Exception:
            record["ready"] = False
            raise
        finally:
            ctx.store.put("installs", record["id"], record)
    elif kind == "workstation":
        from .workstation import execute_check
        execute_check(ctx)
    elif kind == "smoke":
        smoke(ctx)
    elif kind == "workflow":
        from .runs import execute_workflow
        execute_workflow(ctx)
    elif kind in {"environments", "database_download"}:
        from .maintenance import execute_environments, execute_download
        (execute_environments if kind == "environments" else execute_download)(ctx)
    else:
        raise ValueError("Unsupported job")


