"""Apply reviewed saved resource locations to independent revisions of runs."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from . import databases as db
from .runs import check_run_files, create_run, current_controller, parse_config, tree_digest


def _run(store, key):
    run = store.get("runs", key)
    if not run:
        raise ValueError("Choose an existing run.")
    if run.get("run_type") == "followup":
        raise ValueError("Follow-up resources must be changed through a new reviewed follow-up request.")
    if any(j["kind"] == "workflow" and j["payload"].get("run_id") == key
           and j["status"] in {"queued", "running"} for j in store.jobs()):
        raise ValueError("Wait for this run's queued or active job to finish: " + key)
    check_run_files(run)
    return run


def paths(store, run):
    cfg = parse_config(run["config"])
    result = []
    hybas = db._hybas_paths(store, cfg) if run["tool"] == "hybas" else {}
    for spec in db.CATALOG[run["tool"]]:
        if spec.get("managed"):
            continue
        path = str(hybas[spec["id"]].resolve()) if hybas else str(db._get(cfg, spec["fields"][0], "") or "")
        result.append({"id": spec["id"], "name": spec["name"], "path": path})
    return result


def preview(store, ids):
    if not isinstance(ids, list) or not ids or len(ids) > 100 or any(not isinstance(i, str) for i in ids):
        raise ValueError("Choose between one and 100 runs.")
    runs = [_run(store, key) for key in dict.fromkeys(ids)]
    tool = runs[0]["tool"]
    if any(r["tool"] != tool for r in runs):
        raise ValueError("Select runs from one pipeline at a time.")
    text = db._text(store, tool)
    saved_cfg = parse_config(text)
    saved_panel = db.panel(store, tool)
    if saved_panel["revision"] != db.revision(text):
        raise ValueError("Saved locations changed. Review the database changes again.")
    specs = {s["id"]: s for s in db.CATALOG[tool] if not s.get("managed")}
    checked = {}
    for row in saved_panel["rows"]:
        if row["managed"]:
            continue
        try:
            if not row["path"]:
                raise ValueError("No saved location. Select and save this database first.")
            checked[row["id"]] = db.inspect(store, tool, row["id"], row["path"], saved_cfg)
        except (OSError, ValueError, RuntimeError) as exc:
            checked[row["id"]] = {"error": str(exc), "path": row["path"]}
    plans = []
    for run in runs:
        cfg = parse_config(run["config"])
        rows = []
        for current in paths(store, run):
            key = current["id"]
            candidate = checked[key]
            row = {**current, "current": current["path"], "saved": candidate["path"],
                   "valid": "error" not in candidate, "error": candidate.get("error", ""),
                   "updates": candidate.get("updates", {})}
            row.pop("path")
            row["changed"] = (row["current"] != row["saved"] if tool == "hybas" else
                              db._fields(cfg, specs[key]) != row["updates"])
            rows.append(row)
        plans.append({"id": run["id"], "label": run["label"], "config_sha256": run["config_sha256"], "rows": rows})
    result = {"tool": tool, "revision": saved_panel["revision"], "runs": plans}
    result["signature"] = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
    return result


def apply(store, ids, selections, signature):
    plan = preview(store, ids)
    if plan["signature"] != signature:
        raise ValueError("Run or saved database locations changed. Review the database changes again.")
    if not isinstance(selections, dict) or set(selections) - {r["id"] for r in plan["runs"]}:
        raise ValueError("Choose databases from the reviewed runs.")
    prepared = []
    for reviewed in plan["runs"]:
        selected = selections.get(reviewed["id"], [])
        if not isinstance(selected, list) or any(not isinstance(k, str) for k in selected):
            raise ValueError("Invalid database selection.")
        if not selected:
            continue
        choices = {r["id"]: r for r in reviewed["rows"] if r["valid"] and r["changed"]}
        if set(selected) - choices.keys():
            raise ValueError("Select changed, valid saved database locations only.")
        parent = _run(store, reviewed["id"])
        current_controller(store, parent)
        if tree_digest(Path(parent["folder"]) / "workflow") != parent["workflow_sha256"]:
            raise ValueError("The run's workflow source changed. Create a new run.")
        cfg = parse_config(parent["config"])
        selected = list(dict.fromkeys(selected))
        if parent["tool"] == "hybas":
            locations = db._hybas_paths(store, cfg)
            for key in selected:
                locations[key] = Path(choices[key]["saved"])
            lineage = locations["busco"].name
            root = db._hybas_layout(store, {k: p.resolve() for k, p in locations.items()}, lineage)
            cfg.update(db_root=str(root), kraken_db_name="kraken", busco_lineage=lineage)
            if "busco" in selected:
                previous = cfg.get("busco_download_lineages", [])
                cfg["busco_download_lineages"] = list(dict.fromkeys([lineage, *(previous if isinstance(previous, list) else [])]))
        else:
            for key in selected:
                spec = db._spec(parent["tool"], key)
                for field in spec["fields"]:
                    db._set(cfg, field, choices[key]["updates"].get(field))
            # Keep the run's analysis options when validating grouped resources.
            for key in selected:
                db.inspect(store, parent["tool"], key, choices[key]["saved"], cfg)
        prepared.append((parent, cfg, selected))
    if not prepared:
        raise ValueError("Select at least one changed, valid saved database.")
    created = []
    for parent, cfg, selected in prepared:
        try:
            child = create_run(store, parent["tool"], parent["sample"], yaml.safe_dump(cfg, sort_keys=False),
                               parent["cores"], parent["memory_mb"], parent["id"], parent["label"] + " · saved databases",
                               parent["installation"], expected_inputs=parent["inputs"])
            child["rule_cache"] = parent.get("rule_cache", child["rule_cache"])
            child["database_refresh"] = {"revision": plan["revision"], "resources": selected}
            Path(child["folder"], "viralogix-run.json").write_text(json.dumps(child, indent=2) + "\n")
            store.put("runs", child["id"], child)
            created.append(child)
        except Exception as exc:
            raise ValueError(f"Created {len(created)} revised draft(s). Could not revise {parent['id']}: {exc}") from exc
    return created
