"""User-selected GitHub wheel updates for the current application environment."""
from __future__ import annotations
import email
import copy
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time
from urllib.request import Request, urlopen
from zipfile import ZipFile

from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version

from . import __version__
def api(path):
    request = Request('https://api.github.com/' + path, headers={'User-Agent': 'Virologix', 'Accept': 'application/vnd.github+json'})
    if os.environ.get('GH_TOKEN'):
        request.add_unredirected_header('Authorization', 'Bearer ' + os.environ['GH_TOKEN'])
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def pages(path):
    for page in range(1, 11):
        rows = api(path + f'?per_page=100&page={page}')
        if not isinstance(rows, list): raise ValueError('Invalid release catalogue')
        yield from rows
        if len(rows) < 100: break

from .store import now
from . import restart as restart_control

REPO = "crackberryq/Virologix"
PROCESS_STARTED = time.time()
MAX_WHEEL_BYTES = 32 * 1024 * 1024


def release_record(release):
    """Accept only the expected wheel from this repository's published release."""
    if release.get("draft"):
        return None
    tag = release.get("tag_name", "")
    try:
        version = Version(tag.removeprefix("v"))
    except InvalidVersion:
        return None
    if tag != "v" + str(version):
        return None
    name = f"viralogix-{version}-py3-none-any.whl"
    assets = [a for a in release.get("assets", []) if a.get("name") == name]
    wheel = assets[0] if len(assets) == 1 else None
    url = f"https://github.com/{REPO}/releases/download/{tag}/{name}"
    checksum = (wheel or {}).get("digest", "") or ""
    available = bool(wheel and wheel.get("state") == "uploaded" and wheel.get("browser_download_url") == url
                     and re.fullmatch(r"sha256:[0-9a-f]{64}", checksum)
                     and 0 < wheel.get("size", 0) <= MAX_WHEEL_BYTES)
    return {"id": release["id"], "tag": tag, "version": str(version), "name": release.get("name") or tag,
            "prerelease": bool(release.get("prerelease")), "published_at": release.get("published_at"),
            "url": f"https://github.com/{REPO}/releases/tag/{tag}", "notes": (release.get("body") or "")[:50000],
            "available": available, "asset_id": wheel.get("id") if wheel else None,
            "wheel_name": name, "wheel_url": url, "sha256": checksum.removeprefix("sha256:") if available else None,
            "size": wheel.get("size") if wheel else None}


def fetch_releases():
    records = [record for release in pages(f"repos/{REPO}/releases") if (record := release_record(release))]
    records.sort(key=lambda row: Version(row["version"]), reverse=True)
    return {"checked_at": now(), "releases": records}


def status(store):
    state = store.get("settings", "app-update", {})
    queue_paused = store.queue_snapshot()['paused']
    active = next((j for j in store.jobs() if j["kind"] == "app_update" and j["status"] in {"queued", "running"}), None)
    try:
        installed = importlib.metadata.version("viralogix")
    except importlib.metadata.PackageNotFoundError:
        installed = __version__  # Source checkout or a wheel replacement in progress.
    restart = bool(state.get("pip_started_at", 0) > PROCESS_STARTED or installed != __version__)
    launcher = restart_control.current_launcher(store)
    automatic = bool(launcher
                     and (not active or active['payload'].get('launcher_id') == launcher['id'])
                     and (not restart or (state.get('launcher_id') == launcher['id'] and state.get('restart_status') != 'failed' and state.get('status') != 'failed')))
    catalog = copy.deepcopy(store.get("app_catalog", "releases"))
    if catalog:
        for release in catalog["releases"]:
            release["older"] = Version(release["version"]) < Version(__version__)
            release["newer"] = Version(release["version"]) > Version(__version__)
    return {"running_version": __version__, "installed_version": installed, "python": sys.executable,
            "environment": sys.prefix, "catalog": catalog,
            "active_job": active["id"] if active else None, "target_version": active["payload"]["release"]["version"] if active else None, "restart_required": restart,
            "automatic_restart": automatic, "queue_paused": queue_paused,
            "launcher": {k: launcher[k] for k in ('id', 'version', 'url')} if launcher else None,
            "last_update": state, "can_install": platform.system() == "Linux" and not restart and not queue_paused
            and not any(j["status"] in {"queued", "running"} for j in store.jobs())}


def assert_current(store):
    info = status(store)
    if info["restart_required"] and info["automatic_restart"]:
        raise ValueError("Virologix is updating and will restart automatically. Wait for this tab to refresh before starting more work.")
    if info["restart_required"]:
        raise ValueError("Restart Virologix to load the installed application before starting more work. In its terminal press Ctrl+C, then rerun your Virologix launch command.")


def download_wheel(record, directory):
    path = directory / record["wheel_name"]
    digest = hashlib.sha256()
    request = Request(record["wheel_url"], headers={"User-Agent": "Virologix/" + __version__})
    count = 0
    try:
        with urlopen(request, timeout=60) as response, path.open("wb") as target:
            if not response.url.startswith("https://"):
                raise ValueError("Wheel download redirected to an insecure URL")
            while chunk := response.read(1024 * 1024):
                count += len(chunk)
                if count > record["size"] or count > MAX_WHEEL_BYTES:
                    raise ValueError("Wheel download exceeds the published size")
                digest.update(chunk)
                target.write(chunk)
        if count != record["size"] or digest.hexdigest() != record["sha256"]:
            raise ValueError("Wheel size or SHA-256 does not match GitHub. Nothing was installed.")
        validate_wheel(path, record["version"])
        return path
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def validate_wheel(path, expected_version):
    with ZipFile(path) as wheel:
        files = [n for n in wheel.namelist() if n.endswith(".dist-info/METADATA")]
        if len(files) != 1 or wheel.getinfo(files[0]).file_size > 1024 * 1024:
            raise ValueError("Invalid application wheel metadata")
        metadata = email.message_from_bytes(wheel.read(files[0]))
    if metadata.get("Name", "").lower() != "viralogix" or metadata.get("Version") != expected_version:
        raise ValueError("Wheel identity does not match the selected Virologix version")
    requirement = metadata.get("Requires-Python")
    if not requirement or Version(platform.python_version()) not in SpecifierSet(requirement):
        raise ValueError(f"This release needs Python {requirement}; this environment uses {platform.python_version()}.")


def install_update(ctx):
    """The worker holds exclusive environment and workspace locks throughout."""
    selected = ctx.job["payload"]["release"]
    latest = release_record(api(f"repos/{REPO}/releases/{int(selected['id'])}"))
    identity = ("id", "tag", "version", "asset_id", "wheel_url", "sha256", "size")
    if not latest or not latest["available"] or any(latest[k] != selected[k] for k in identity):
        raise ValueError("The release asset changed. Refresh Virologix releases and select it again.")
    if latest["version"] == __version__:
        raise ValueError("That Virologix version is already running.")
    directory = ctx.store.home / "updates" / ctx.job["id"]
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    ctx.write(f"Downloading {latest['tag']} from {REPO} and verifying its SHA-256…")
    wheel = download_wheel(latest, directory)
    ctx.write("Wheel identity, checksum and Python requirement verified.")
    ctx.write("Updating only the application environment: " + sys.prefix)
    state = {"job": ctx.job["id"], "from_version": __version__, "version": latest["version"],
             "wheel": str(wheel), "sha256": latest["sha256"], "pip_started_at": time.time(), "status": "installing",
             "environment": sys.prefix, "launcher_id": ctx.job['payload'].get('launcher_id')}
    ctx.store.put("settings", "app-update", state)
    argv = [sys.executable, "-m", "pip", "--isolated", "install", "--upgrade", "--no-user", "--no-input",
            "--disable-pip-version-check", str(wheel)]
    env = dict(os.environ, PYTHONNOUSERSITE="1", PYTHONUNBUFFERED="1")
    try:
        # Do not kill pip halfway through replacing the application package.
        subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=ctx.log, stderr=subprocess.STDOUT,
                       env=env, pass_fds=ctx.lock_fds, check=True)
        code = ("import importlib.metadata as m; import viralogix, streamlit; "
                f"assert m.version('viralogix') == {latest['version']!r}; "
                f"assert viralogix.__version__ == {latest['version']!r}; "
                "print('Installed Virologix', m.version('viralogix'))")
        subprocess.run([sys.executable, "-c", code], stdin=subprocess.DEVNULL, stdout=ctx.log,
                       stderr=subprocess.STDOUT, env=env, pass_fds=ctx.lock_fds, check=True)
        subprocess.run([sys.executable, "-m", "pip", "check"], stdin=subprocess.DEVNULL,
                       stdout=ctx.log, stderr=subprocess.STDOUT, env=env, pass_fds=ctx.lock_fds, check=True)
    except BaseException:
        state.update(status="failed", finished=now())
        ctx.store.put("settings", "app-update", state)
        ctx.write("Application installation failed. Read the pip output above. Restart the app before further work; the environment may have changed.")
        raise
    state.update(status="installed", finished=now())
    ctx.store.put("settings", "app-update", state)
    if state['launcher_id']:
        ctx.write('Update verified. The launcher will restart the app on the same address after this job finishes; open browser tabs will refresh automatically.')
    else:
        ctx.write('Update verified. This session has no automatic restart supervisor. Press Ctrl+C, then run viralogix once and refresh the browser.')


def refresh(store):
    catalog = fetch_releases()
    store.put('app_catalog', 'releases', catalog)
    return {'message': 'Application releases checked.'}


def request_update(store, release_id, request_id):
    from .pipelines import enqueue
    info = status(store)
    if not info['can_install']:
        raise ValueError('Finish active work and restart if required before updating Virologix.')
    catalog = store.get('app_catalog', 'releases', {})
    selected = next((r for r in catalog.get('releases', []) if str(r['id']) == str(release_id)), None)
    if not selected or not selected['available']:
        raise ValueError('Check releases and select a verified application wheel.')
    if Version(selected['version']) <= Version(__version__):
        raise ValueError('Select a newer version. Downgrades are not offered by this updater.')
    launcher = restart_control.current_launcher(store)
    jid = enqueue(store, 'app_update', {'release': selected, 'launcher_id': launcher['id'] if launcher else None}, request_id)
    return {'message': 'Virologix update started. Keep the application open until it finishes.', 'job_id': jid}


def update():
    from .store import Store
    import uuid
    store = Store()
    refresh(store)
    choices = [r for r in store.get('app_catalog','releases')['releases'] if r['available'] and Version(r['version']) > Version(__version__)]
    if not choices:
        print('No newer verified release is available.'); return
    result = request_update(store, choices[0]['id'], uuid.uuid4().hex)
    print(result['message'], result['job_id'])
