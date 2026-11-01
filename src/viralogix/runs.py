"""Version-pinned adapters with isolated outputs and immutable configurations."""
from __future__ import annotations
import copy
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import yaml
from .catalog import DATA, PIPELINES, supported
from .store import identifier, now
from . import __version__


def parse_config(text):
    if len(text.encode()) > 2 * 1024 * 1024:
        raise ValueError("Configuration exceeds 2 MB")
    cfg = yaml.safe_load(text)
    if not isinstance(cfg, dict) or not all(isinstance(k, str) for k in cfg):
        raise ValueError("Configuration must be a YAML mapping with string keys")
    # Avoid recursive aliases, non-JSON scalars and infinite nesting in saved state.
    try:
        encoded = json.dumps(cfg, allow_nan=False)
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValueError("Use ordinary YAML mappings, lists and scalar values; no recursive aliases or special values") from exc
    if len(encoded) > 4 * 1024 * 1024:
        raise ValueError("Expanded configuration exceeds 4 MB")
    return cfg

def template(tool):
    return (DATA / (tool + ".config.yaml")).read_text()

def valid_id(value):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", value) or value in {".", ".."}:
        raise ValueError("Sample ID must use letters, numbers, underscores, dots or dashes (up to 100 characters)")
    return value

def absolute_path(value):
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        raise ValueError("Use an absolute Linux path (or ~/…). Windows users should use WSL paths.")
    path = path.resolve()
    if any(ch in str(path) for ch in "{}\n\r\t"):
        raise ValueError("Paths cannot contain braces, tabs or newlines")
    return path

def register_sample(store, sid, path, mode="supplied_records"):
    valid_id(sid)
    folder = absolute_path(path)
    if not folder.is_dir():
        raise ValueError("Sample folder does not exist: " + str(folder))
    if mode not in {"supplied_records", "hybrid", "ont_only", "illumina_only"}:
        raise ValueError("Unsupported read mode")
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        matches = [json.loads(row[0]) for row in db.execute("SELECT body FROM items WHERE kind='samples'")]
        matches = [s for s in matches if s['id'].casefold() == sid.casefold()]
        if matches:
            if matches[0]['path'] == str(folder) and matches[0]['mode'] == mode:
                return matches[0]
            raise ValueError('That sample ID is already registered with different inputs')
        row = {'id': sid, 'path': str(folder), 'mode': mode, 'created': now()}
        db.execute("INSERT INTO items(kind,id,body) VALUES ('samples',?,?)", (sid, json.dumps(row)))
    return row

def remove_sample(store, sid, expected):
    """Unregister a sample and archive its idle runs without changing run records or files."""
    if not isinstance(sid, str) or not isinstance(expected, dict):
        raise ValueError("Choose a registered sample to remove.")
    valid_id(sid)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT body FROM items WHERE kind='samples' AND id=?", (sid,)).fetchone()
        if row is None:
            raise ValueError("This sample is no longer registered. Refresh the sample list.")
        if json.loads(row[0]) != expected:
            raise ValueError("This sample registration changed. Refresh the sample list before removing it.")
        active = _active_run_ids(db)
        archived, kept = [], []
        for row in db.execute("SELECT body FROM items WHERE kind='runs'").fetchall():
            run = json.loads(row[0])
            sample = run.get("sample", {})
            if sample.get("id") != sid or sample.get("path") != expected["path"]:
                continue
            if run["id"] in active:
                kept.append(run["id"])
            elif not _is_archived(db, run["id"]):
                _set_archive(db, run["id"], True, "sample removed")
                archived.append(run["id"])
        db.execute("DELETE FROM items WHERE kind='samples' AND id=?", (sid,))
    return {"archived": archived, "active": kept}

def _active_run_ids(db):
    rows = db.execute("SELECT payload FROM jobs WHERE kind='workflow' AND status IN ('queued','running')").fetchall()
    return {json.loads(row[0]).get("run_id") for row in rows}

def _is_archived(db, rid):
    row = db.execute("SELECT body FROM items WHERE kind='run_visibility' AND id=?", (rid,)).fetchone()
    return bool(row and json.loads(row[0]).get("archived"))

def _set_archive(db, rid, archived, reason):
    body = {"id": rid, "archived": archived, "changed": now(), "reason": reason}
    db.execute("INSERT INTO items VALUES ('run_visibility',?,?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body",
               (rid, json.dumps(body)))

def archive_runs(store, ids, archived=True):
    """Change list visibility atomically; frozen provenance, reports and files are retained."""
    if not isinstance(ids, list) or not ids or len(ids) > 500 or any(not isinstance(rid, str) for rid in ids):
        raise ValueError("Select between one and 500 saved runs.")
    ids = list(dict.fromkeys(ids))
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        active = _active_run_ids(db)
        for rid in ids:
            if not db.execute("SELECT 1 FROM items WHERE kind='runs' AND id=?", (rid,)).fetchone():
                raise ValueError("The selected run no longer exists.")
            if archived and rid in active:
                raise ValueError("Queued or running jobs stay visible. Wait for them to finish before archiving.")
        for rid in ids:
            _set_archive(db, rid, archived, "removed from list" if archived else "restored")
    return ids

def import_samples(store, text):
    from .sample_imports import commit
    return commit(store, text)

def snapshot_files(paths):
    result = []
    for path in sorted(set(Path(p).resolve() for p in paths)):
        stat = path.stat()
        result.append({"path": str(path), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns})
    return result

def check_inputs(run):
    for expected in run["inputs"]:
        path = Path(expected["path"])
        try:
            stat = path.stat()
        except OSError as exc:
            raise ValueError("Input is no longer accessible: " + str(path)) from exc
        if stat.st_size != expected["size"] or stat.st_mtime_ns != expected["mtime_ns"]:
            raise ValueError("Input changed since this draft was created: " + str(path) + ". Create a new draft.")

def current_controller(store, run):
    installed = store.get("installs", run["installation"])
    if not installed or not installed.get("ready") or not installed.get("controller"):
        raise ValueError("The pipeline runner needs setup or repair")
    if installed["tool"] != run["tool"] or installed["version"]["commit"] != run["commit"]:
        raise ValueError("The installation no longer matches this run's source version")
    return installed["controller"]

def dry_run_current(store, run):
    try:
        return bool(run.get("dry_run_ok") and run.get("validated_controller", run["controller"]) == current_controller(store, run))
    except ValueError:
        return False

def run_status(run, jobs, checked):
    related = [j for j in jobs if j["kind"] == "workflow" and j["payload"].get("run_id") == run["id"]]
    active = next((j for j in related if j["status"] in {"queued", "running"}), None)
    if active:
        return active["status"]
    execution = next((j for j in related if j["payload"].get("action") == "run"), None)
    failures = {"failed", "cancelled", "interrupted"}
    if execution and execution["status"] in failures:
        return execution["status"]
    if related and related[0]["status"] in failures:
        return related[0]["status"]
    return "completed" if run.get("completed") else "checked" if checked else "draft"

def tree_digest(folder):
    digest = hashlib.sha256()
    for path in sorted(Path(folder).rglob("*")):
        rel = path.relative_to(folder)
        if any(part in {".git", ".snakemake", "__pycache__"} for part in rel.parts) or path.suffix == ".pyc":
            continue
        if path.is_file():
            digest.update(str(rel).encode() + b"\0")
            digest.update(path.read_bytes())
    return digest.hexdigest()

def validate_launch(store, rid, action, check_busy=True):
    if action not in {"dry-run", "prepare", "run", "check-environments"}:
        raise ValueError("Unsupported workflow action")
    run = store.get("runs", rid)
    if not run:
        raise ValueError("Unknown run")
    if store.get("run_visibility", rid, {}).get("archived"):
        raise ValueError("Restore this run from Archived before starting a job.")
    if check_busy and any(j["kind"] == "workflow" and j["payload"]["run_id"] == rid and j["status"] in {"queued", "running"} for j in store.jobs()):
        raise ValueError("This run already has a queued or active job")
    current_controller(store, run)
    from .release_contract import preflight
    preflight(store, run["tool"], run["commit"], Path(run["folder"]) / "workflow")
    if not supported(run["tool"], run["commit"], store):
        raise ValueError("This source version has no reviewed execution adapter")
    if action != "dry-run" and not dry_run_current(store, run):
        raise ValueError("A successful native dry-run with the current runner is required before preparing tools or running")
    check_run_files(run)
    from .preflight import assert_launch
    assert_launch(run, action)
    return run

def reports(store):
    result = []
    jobs = store.jobs()
    for run in store.all("runs"):
        output = Path(run["output"])
        entries = report_candidates(store, run)
        for name, rel in entries:
            path = output / rel
            if path.is_file() and path.stat().st_size:
                result.append({"id": run["id"] + "-" + name, "name": name, "path": str(path.resolve()), "run": run["id"], "sample": run["sample"]["id"],
                               "run_status": run_status(run, jobs, dry_run_current(store, run))})
    for item in store.all("reports"):
        if Path(item["path"]).is_file():
            result.append(item)
    for item in store.all("smoke"):
        if Path(item["report"]).is_file():
            result.append({"id": item["id"], "name": "Live test report", "path": item["report"], "run": item["id"], "sample": "Software smoke test"})
    return result

from .flupop_adapter import create_run, command, check_run_files, execute_workflow, report_candidates, clone_runs

from .legacy_runs import save_draft, start_run, archive_run, register_folder, local_path, browse_folder
