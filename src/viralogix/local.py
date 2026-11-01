"""Local folder browsing and bounded, read-only installation discovery."""
from __future__ import annotations

from collections import deque
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from .catalog import PIPELINES, supported
from .runs import absolute_path


def local_path(value):
    """Accept Linux paths and Explorer paths pasted into a WSL-hosted app."""
    value = str(value).strip()
    if sys.platform == "linux" and re.match(r"^[A-Za-z]:[\\/]", value):
        value = "/mnt/" + value[0].lower() + "/" + value[3:].replace("\\", "/")
    elif sys.platform == "linux" and re.match(r"^\\\\(?:wsl\$|wsl\.localhost)\\", value, re.I):
        parts = value.split("\\")
        distro = os.environ.get("WSL_DISTRO_NAME")
        if not distro or len(parts) < 5 or parts[3].casefold() != distro.casefold():
            raise ValueError("Choose a folder in the WSL distribution running Virologix.")
        value = "/" + "/".join(parts[4:])
    return absolute_path(value)


def bookmarks(store):
    paths = [("Home", Path.home()), ("Workspace", store.home), ("Computer", Path("/"))]
    paths += [("Windows " + p.name.upper() + ":", p) for p in Path("/mnt").glob("[a-z]") if p.is_dir()]
    return [{"name": name, "path": str(path)} for name, path in paths if path.is_dir()]


def browse_folders(store, value="", offset=0, query="", show_hidden=False):
    path = local_path(value) if value else Path.home()
    if not path.is_dir():
        raise ValueError("Folder does not exist: " + str(path))
    offset = int(offset)
    if offset < 0:
        raise ValueError("Invalid folder page")
    folders = []
    files = 0
    scanned = 0
    limited = False
    try:
        with os.scandir(path) as entries:
            for entry in entries:
                scanned += 1
                if scanned > 20000:
                    limited = True
                    break
                if not show_hidden and entry.name.startswith("."):
                    continue
                try:
                    if entry.is_dir():
                        if query.casefold() in entry.name.casefold():
                            folders.append({"name": entry.name, "path": str(path / entry.name), "link": entry.is_symlink()})
                    else:
                        files += 1
                except OSError:
                    continue
    except PermissionError as exc:
        raise ValueError("You do not have permission to browse " + str(path)) from exc
    folders.sort(key=lambda row: row["name"].casefold())
    return {"path": str(path), "parent": str(path.parent), "name": path.name,
            "folders": folders[offset:offset + 100], "offset": offset,
            "more": offset + 100 < len(folders), "total": len(folders), "files": files,
            "limited": limited, "bookmarks": bookmarks(store),
            "layout": {name: (path / name).is_dir() for name in ("raw/illumina", "raw/nanopore", "annotation")}}


def git_read(path, *args):
    try:
        result = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, timeout=8,
                                env=dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0"))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("Cannot read this Git checkout; check Git and folder access.") from exc
    if result.returncode:
        raise ValueError("Choose a Git checkout of the pipeline, with its .git folder.")
    return result.stdout.strip()


def inspect_installation(value, tool, store=None):
    spec = PIPELINES[tool]
    path = local_path(value)
    if not (path / spec["snakefile"]).is_file() or not (path / spec["environment"]).is_file():
        raise ValueError(f"Choose the {spec['name']} folder containing {spec['snakefile']} and {spec['environment']}.")
    root = Path(git_read(path, "rev-parse", "--show-toplevel")).resolve()
    if root != path:
        raise ValueError("Choose the pipeline's Git repository root.")
    commit = git_read(path, "rev-parse", "HEAD")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Could not identify the installed source commit.")
    branch = git_read(path, "rev-parse", "--abbrev-ref", "HEAD")
    dirty = bool(git_read(path, "diff", "--name-only", "HEAD", "--"))
    cache = path / ".snakemake/conda"
    return {"tool": tool, "path": str(path), "commit": commit, "ref": branch if branch != "HEAD" else commit[:12],
            "supported": supported(tool, commit, store), "modified": dirty,
            "rule_cache": str(cache) if cache.is_dir() else ""}


def environment_paths(store):
    """Bounded metadata-only discovery, also used by database scanning."""
    from .engine import find_conda
    paths = {Path(sys.prefix), store.home / "envs/flupop"}
    registry = Path.home() / ".conda/environments.txt"
    try:
        with registry.open() as handle:
            for index, line in enumerate(handle):
                if index >= 1000:
                    break
                if line.strip():
                    paths.add(Path(line.strip()).expanduser())
    except OSError:
        pass
    roots = [Path.home() / name for name in ("miniconda3", "miniforge3", "anaconda3", "mambaforge")]
    conda = find_conda(store)
    if conda:
        roots.append(Path(conda).parent.parent)
    for var in ("CONDA_PREFIX", "CONDA_ENVS_PATH"):
        paths.update(Path(p) for p in os.environ.get(var, "").split(os.pathsep) if p)
    for base in roots:
        paths.add(base)
        try:
            with os.scandir(base / "envs") as entries:
                for index, entry in enumerate(entries):
                    if index >= 1000:
                        break
                    if entry.is_dir():
                        paths.add(Path(entry.path))
        except OSError:
            pass
    return sorted({p.resolve() for p in paths if p.is_dir()})


def discover_environments(store):
    from .engine import find_conda
    conda = find_conda(store)
    paths = {str(Path(sys.prefix).resolve())}
    warning = ""
    if conda:
        try:
            result = subprocess.run([conda, "env", "list", "--json"], capture_output=True, text=True, timeout=12)
            if result.returncode:
                raise ValueError("Conda did not return an environment list")
            paths.update(json.loads(result.stdout).get("envs", []))
        except (OSError, ValueError, subprocess.TimeoutExpired):
            warning = "Conda environments could not be listed. You can still browse to an environment folder."
    else:
        warning = "Select your Conda executable in Install & update to detect environments."
    rows = []
    for value in sorted(paths):
        path = Path(value).expanduser()
        if not (path / "conda-meta").is_dir():
            continue
        # Read package metadata only; detection never executes an environment's Python.
        versions = {}
        for pattern in ("python-*.json", "snakemake-*.json", "snakemake-minimal-*.json"):
            for file in (path / "conda-meta").glob(pattern):
                try:
                    if file.stat().st_size > 4 * 1024 * 1024:
                        continue
                    package = json.loads(file.read_text())
                    versions[package["name"]] = package["version"]
                except (OSError, ValueError, KeyError):
                    continue
        rows.append({"path": str(path.resolve()), "name": path.name, "python": versions.get("python", "unknown"),
                     "snakemake": versions.get("snakemake-minimal", versions.get("snakemake", "unknown"))})
    return {"environments": rows, "warning": warning}


def discover_installations(store, tool, root=""):
    starts = [local_path(root)] if root else [Path.home(), Path.cwd(), Path("/opt")]
    if root and not starts[0].is_dir():
        raise ValueError("Search folder does not exist.")
    excluded = {".git", ".snakemake", ".cache", ".local", "__pycache__", "node_modules", "envs", "pkgs",
                "controllers", "raw", "reads", "work", "outputs", "resources", "db", "databases", "annotation"}
    queue = deque((p, 0) for p in starts if p.is_dir())
    seen, candidates = set(), []
    started = time.monotonic()
    visited = 0
    while queue and visited < 2500 and time.monotonic() - started < 6:
        folder, depth = queue.popleft()
        try:
            canonical = folder.resolve()
            if canonical in seen:
                continue
            seen.add(canonical)
            visited += 1
            if (folder / PIPELINES[tool]["snakefile"]).is_file():
                try:
                    candidates.append(inspect_installation(folder, tool))
                except ValueError as exc:
                    candidates.append({"tool": tool, "path": str(folder), "supported": False, "error": str(exc)})
                continue
            if depth >= 4 or (folder / "conda-meta").is_dir():
                continue
            with os.scandir(folder) as entries:
                for index, entry in enumerate(entries):
                    if index >= 5000 or time.monotonic() - started >= 6:
                        break
                    if entry.name.startswith(".") or entry.name in excluded or entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        queue.append((Path(entry.path), depth + 1))
        except (OSError, RuntimeError):
            continue
    return {"candidates": candidates, "roots": [str(p) for p in starts], "visited": visited,
            "limited": bool(queue), "depth": 4}
