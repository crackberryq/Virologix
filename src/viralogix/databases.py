"""Read-only resource discovery and explicit, revision-checked default updates.

This checks recognizable layouts, not complete checksums or scientific suitability.
No database programs are run, no models are loaded and no resources are downloaded.
"""
from __future__ import annotations

from collections import deque
import hashlib
import json
import os
from pathlib import Path
import re
import time

import yaml

from .local import local_path, environment_paths
from .runs import parse_config, template
from .store import now

MAX_DIRS = 5000
MAX_ENTRIES = 3000
MAX_DEPTH = 7
MAX_SECONDS = 8
JSON_LIMIT = 4 * 1024 * 1024
SKIP = {".git", "__pycache__", "node_modules", "raw", "reads", "logs", "proc", "sys", "dev", "$Recycle.Bin", "System Volume Information"}
DEEP_PATHS = ("reference_fasta", "reference_metadata", "domain_database", "profiles_dir", "motif_rules", "placement_registry")


def _module(key, name, description, hint):
    prefix = "modules." + key + "."
    return dict(id=key, name=name, description=description, hint=hint,
                fields=[prefix + k for k in ("database", "metadata", "database_version", "reference_fasta")])


CATALOG = {'flupop': [],
    "micpscope": [],
    "hybas": [
        dict(id="kraken", name="Kraken2", description="Choose the folder containing the three Kraken2 index files.", hint="hash.k2d", fields=[]),
        dict(id="busco", name="BUSCO lineage", description="Choose a complete lineage dataset. A matching configured lineage is preferred.", hint="dataset.cfg", fields=[]),
        dict(id="prokka", name="Prokka databases", managed=True, description="Bundled with the annotation tool environment; this HybAs AWARE version does not accept a separate database path."),
    ],
    "basis": [
        _module("amrfinder", "AMRFinderPlus", "Choose a versioned database folder, or its parent containing latest.", "AMRProt.fa"),
        _module("rgi", "CARD / RGI", "Choose the folder containing card.json, or paste the file path.", "card.json"),
        _module("vfdb", "VFDB", "Choose the folder containing vfdb_setA.dmnd and its reference FASTA.", "vfdb_setA.dmnd"),
        _module("bacmet", "BacMet", "Choose the folder containing bacmet_exp.dmnd and its reference FASTA.", "bacmet_exp.dmnd"),
        _module("antismash", "antiSMASH", "Choose the prepared database bundle, including its Pfam folder.", "pfam"),
        _module("genomad", "geNomad", "Choose the genomad_db folder containing its metadata and compiled indices.", "genomad_marker_metadata.tsv"),
        _module("mobsuite", "MOB-suite", "Choose the initialized database directory containing taxa.sqlite and sequence indices.", "taxa.sqlite"),
        _module("mlst", "MLST / PubMLST", "Choose the prepared folder containing pubmlst and blast subfolders.", "pubmlst"),
        _module("crisprcasfinder", "CRISPRCasFinder / CASFinder", "Choose the prepared source-and-model bundle. The native runner verifies its pinned versions.", "CRISPRCasFinder.pl"),
        dict(id="prosite", name="PROSITE", description="Choose a complete BaSIS PROSITE snapshot, including its provenance.", hint="prosite.dat", fields=["deep.prosite_snapshot"]),
        dict(id="prott5", name="ProtT5 + classifier models", description="Choose a prepared BaSIS bundle or resource receipt containing both model locations and recorded model identity.", hint="model-identity.json", fields=["modules.pathogenfinder2." + k for k in ("prot_t5_path", "weights_model", "prot_t5_identity")]),
        dict(id="deep_catalogue", name="BaSIS deep reference bundle", description="Choose a completed BaSIS resource folder with its receipt. All required companion paths are kept together.", hint=None, fields=["deep." + k for k in DEEP_PATHS]),
        dict(id="integronfinder", name="IntegronFinder models", managed=True, description="Uses models bundled in its tool environment; the pinned adapter does not redirect them to a custom folder."),
        dict(id="isescan", name="ISEScan models", managed=True, description="Uses models bundled in its tool environment; the pinned adapter does not redirect them to a custom folder."),
        dict(id="icescreen", name="ICEscreen databases", managed=True, description="Uses databases bundled in its tool environment; the pinned adapter does not redirect them to a custom folder."),
        dict(id="minced", name="MinCED", managed=True, description="No external database is required."),
    ],
}


def _spec(tool, key):
    spec = next((s for s in CATALOG[tool] if s["id"] == key), None)
    if not spec or spec.get("managed"):
        raise ValueError("Choose a database that supports a local folder.")
    return spec


def _get(cfg, dotted, default=None):
    value = cfg
    for key in dotted.split("."):
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]
    return value


def _set(cfg, dotted, value):
    keys = dotted.split(".")
    target = cfg
    for key in keys[:-1]:
        if key not in target:
            target[key] = {}
        if not isinstance(target[key], dict):
            raise ValueError("Configuration section must be a mapping: " + key)
        target = target[key]
    if value is None:
        target.pop(keys[-1], None)
    else:
        target[keys[-1]] = value


def revision(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _text(store, tool):
    return store.get("configs", tool, template(tool))


def _file(path):
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _json(path):
    try:
        if not _file(path) or path.stat().st_size > JSON_LIMIT:
            return {}
        with path.open("rb") as handle:
            value = json.loads(handle.read(JSON_LIMIT + 1))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _children(path):
    """Bounded enumeration, including file entries; never an unbounded glob."""
    entries = []
    with os.scandir(path) as iterator:
        for entry in iterator:
            if len(entries) == MAX_ENTRIES:
                return entries, True
            entries.append(entry)
    return entries, False


def _some(path, suffix=None):
    try:
        entries, _ = _children(path)
        return any((suffix is None or e.name.endswith(suffix)) and _file(Path(e.path)) for e in entries)
    except OSError:
        return False


def _require(root, names):
    missing = [n for n in names if not _file(root / n)]
    if missing:
        raise ValueError("Missing or empty: " + ", ".join(missing[:8]))


def _hybas_paths(store, cfg):
    raw = cfg.get("db_root", "db")
    base = store.home / "resources/hybas/db" if str(raw) == "db" else local_path(raw)
    return {"kraken": base / str(cfg.get("kraken_db_name", "standard")),
            "busco": base / "busco" / str(cfg.get("busco_lineage", "bacteria_odb10"))}


def _fields(cfg, spec):
    return {key: _get(cfg, key) for key in spec["fields"] if _get(cfg, key) is not None}


def panel(store, tool):
    text = _text(store, tool)
    cfg = parse_config(text)
    locations = store.get("database_locations", tool, {})
    rows = []
    for spec in CATALOG[tool]:
        row = {k: spec[k] for k in ("id", "name", "description")}
        row["managed"] = bool(spec.get("managed"))
        row["path"] = ""
        if not row["managed"]:
            values = _fields(cfg, spec)
            if tool == "hybas":
                try:
                    row["path"] = str(_hybas_paths(store, cfg)[spec["id"]].resolve())
                except (OSError, ValueError):
                    row["path"] = ""
            else:
                primary = values.get(spec["fields"][0], "")
                saved = locations.get(spec["id"], {})
                row["path"] = saved.get("path", "") if saved.get("fields") == values and primary else str(primary or "")
            row["configured"] = bool(row["path"])
        rows.append(row)
    return {"tool": tool, "revision": revision(text), "rows": rows,
            "policy": _get(cfg, "resources.policy", "auto") if tool == "basis" else "manual",
            "lineage": str(cfg.get("busco_lineage", "bacteria_odb10")) if tool == "hybas" else ""}


def _receipt(root, spec):
    for name in ("provenance.json", "completed.json"):
        data = _json(root / name)
        if data.get("status") != "completed":
            continue
        result = data.get("result", data)
        if not isinstance(result, dict):
            continue
        updates = {}
        for dotted in spec["fields"]:
            parts = dotted.split(".")
            value = _get(result, ("module_updates." + ".".join(parts[1:])) if parts[0] == "modules" else "deep_updates." + parts[1])
            if value is not None:
                updates[dotted] = value
        if updates.get(spec["fields"][0]):
            return updates, str(root / name)
    return {}, ""


def _validate_updates(spec, updates):
    """Receipts are data: import only this resource's allowlisted fields."""
    for key, value in list(updates.items()):
        if key not in spec["fields"] or not isinstance(value, str):
            raise ValueError("Unrecognized resource receipt field: " + key)
        if key.endswith(("database_version", "prot_t5_identity")):
            if not value or len(value) > 500:
                raise ValueError("Invalid recorded resource identity.")
            continue
        path = local_path(value)
        is_directory = key.endswith((".profiles_dir", ".prot_t5_path", ".weights_model", ".prosite_snapshot"))
        is_database = key.endswith(".database")
        if (is_directory and not path.is_dir()) or (not is_directory and not is_database and not _file(path)) or (is_database and not path.is_dir() and not _file(path)):
            raise ValueError("Resource companion is missing or empty: " + str(path))
        updates[key] = str(path)


def inspect(store, tool, key, value, cfg=None):
    spec = _spec(tool, key)
    cfg = cfg if cfg is not None else parse_config(_text(store, tool))
    path = local_path(value)
    if not path.exists():
        raise ValueError("Location does not exist: " + str(path))
    root = path if path.is_dir() else path.parent
    updates, receipt = _receipt(root, spec) if tool == "basis" else ({}, "")
    primary = spec["fields"][0] if spec["fields"] else ""
    if updates:
        _validate_updates(spec, updates)
        path = local_path(updates[primary])
        root = path if path.is_dir() else path.parent
    elif key in {"deep_catalogue", "prott5"}:
        current = _fields(cfg, spec)
        selected = next((r["path"] for r in panel(store, tool)["rows"] if r["id"] == key), "")
        if selected and local_path(selected) == path and current.get(primary):
            updates = current
    database = path
    version = ""
    if key == "kraken":
        _require(root, ("hash.k2d", "opts.k2d", "taxo.k2d"))
        database = root
    elif key == "busco":
        _require(root, ("dataset.cfg", "scores_cutoff", "lengths_cutoff"))
        if not _some(root / "hmms", ".hmm"):
            raise ValueError("BUSCO lineage needs nonempty hmms/*.hmm files.")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+_odb[0-9]+", root.name):
            raise ValueError("Choose a lineage directory named like bacteria_odb10.")
        database, version = root, root.name
    elif key == "amrfinder":
        if (root / "latest").is_dir() and not (root / "AMRProt.fa").exists():
            root = (root / "latest").resolve()
        _require(root, ("version.txt", "AMRProt.fa", "AMRProt.fa.phr", "AMR.LIB", *("AMR.LIB.h3" + s for s in "fimp")))
        database = root
    elif key in {"rgi", "vfdb", "bacmet"}:
        expected = {"rgi": "card.json", "vfdb": "vfdb_setA.dmnd", "bacmet": "bacmet_exp.dmnd"}[key]
        database = path if path.is_file() else root / expected
        _require(database.parent, (database.name,))
        if (key == "rgi" and database.suffix.lower() != ".json") or (key != "rgi" and database.suffix.lower() != ".dmnd"):
            raise ValueError("Choose " + expected + " or its containing folder.")
        if key != "rgi":
            names = ("VFDB_setA_pro.normalized.fas", "vfdb_setA.faa", "VFDB_setA_pro.fas", "vfdb_setA.fasta") if key == "vfdb" else ("BacMet2_EXP_database.fasta",)
            reference = updates.get("modules." + key + ".reference_fasta")
            match = Path(reference) if reference else next((root / n for n in names if _file(root / n)), None)
            if match:
                updates["modules." + key + ".reference_fasta"] = str(match)
            elif key == "vfdb":
                raise ValueError("VFDB needs its matching reference FASTA alongside the DIAMOND index (or recorded in a completed receipt).")
    elif key == "genomad":
        _require(root, ("version.txt", "genomad_marker_metadata.tsv", "names.dmp", "nodes.dmp", *(p + s for p in ("genomad_db", "genomad_mini_db", "genomad_integrase_db") for s in ("", ".dbtype", ".index"))))
        database = root
    elif key == "antismash":
        entries, _ = _children(root / "pfam")
        if not any(_file(Path(e.path) / "Pfam-A.hmm") and all(_file(Path(e.path) / ("Pfam-A.hmm.h3" + s)) for s in "fimp") for e in entries):
            raise ValueError("Missing prepared pfam/<version>/Pfam-A.hmm and HMMER indices.")
        for name in ("as-js", "mite", "resfam", "tigrfam", "clusterblast", "knownclusterblast", "clustercompare", "comparippson", "nrps_pks"):
            if not (root / name).is_dir():
                raise ValueError("antiSMASH bundle is missing " + name)
        database = root
    elif key == "mobsuite":
        _require(root, ("ncbi_plasmid_full_seqs.fas", "ncbi_plasmid_full_seqs.fas.msh", "repetitive.dna.fas", "rep.dna.fas", "mob.proteins.faa", "mpf.proteins.faa", "orit.fas", "clusters.txt", "taxa.sqlite"))
        entries, _ = _children(root)
        for prefix in ("ncbi_plasmid_full_seqs.fas", "repetitive.dna.fas"):
            for suffix in ("nhr", "nin", "nsq"):
                if not any(e.name.startswith(prefix + ".") and e.name.endswith("." + suffix) and _file(Path(e.path)) for e in entries):
                    raise ValueError("Missing BLAST index: " + prefix + "." + suffix)
        database = root
    elif key == "mlst":
        _require(root, tuple("blast/mlst.fa." + s for s in ("nhr", "nin", "nsq")))
        entries, _ = _children(root / "pubmlst")
        if not any(_file(Path(e.path) / (e.name + ".txt")) for e in entries):
            raise ValueError("No nonempty PubMLST scheme definitions found.")
        database = root
    elif key == "crisprcasfinder":
        _require(root, ("CRISPRCasFinder.pl", "sel392v2.so", "models/CASFinder/metadata.yml"))
        if not _some(root / "models/CASFinder/profiles", ".hmm"):
            raise ValueError("CASFinder HMM profiles are missing.")
        database = root
    elif key == "prosite":
        _require(root, ("prosite.dat", "prosite.aux", "prosite.doc", "ps_reldt.txt", "ps_scan.pl", "prorule.dat", "provenance.json"))
        database = root
    elif key == "prott5":
        if not updates:
            identity = _json(root / "model-identity.json")
            if not identity.get("repository") or not identity.get("revision"):
                raise ValueError("Choose a prepared model bundle with model-identity.json or its completed resource receipt.")
            updates = dict(zip(spec["fields"], (str(root / "model"), str(root / "classifier_weights"), str(identity["repository"]) + "@" + str(identity["revision"]))))
        if any(not updates.get(k) for k in spec["fields"]):
            raise ValueError("Both model folders and prot_t5_identity are required.")
        model, weights = (local_path(updates[k]) for k in spec["fields"][:2])
        _require(model, ("config.json", "spiece.model"))
        if not any(_file(model / n) for n in ("pytorch_model.bin", "model.safetensors")):
            raise ValueError("Encoder weights are missing.")
        model_config = _json(model / "config.json")
        if model_config.get("model_type") != "t5" or model_config.get("d_model") != 1024:
            raise ValueError("Model configuration does not match the pipeline's encoder format.")
        _require(weights, ("model.pt", *(f"weights_model{n}.pt" for n in range(1, 5))))
    elif key == "deep_catalogue":
        required = list(spec["fields"][:4])
        if _get(cfg, "deep.motifs", True):
            required.append("deep.motif_rules")
        if _get(cfg, "deep.family_placement", True):
            required.append("deep.placement_registry")
        if any(not updates.get(k) for k in required):
            raise ValueError("Choose a completed resource receipt with all required reference, metadata, profile and companion paths.")
        if not _some(local_path(updates["deep.profiles_dir"]), ".yaml"):
            raise ValueError("The recorded profiles directory is empty.")
    if tool == "basis":
        if key not in {"prott5", "deep_catalogue"}:
            updates[primary] = str(database.resolve())
        # A nearby provider manifest records metadata without importing executable
        # overrides or analysis options from another configuration.
        metadata = root / "resource-provenance.json"
        manifest = _json(metadata)
        if manifest.get("provider") in {key, "card" if key == "rgi" else key}:
            if "modules." + key + ".metadata" in spec["fields"]:
                updates.setdefault("modules." + key + ".metadata", str(metadata))
                recorded = manifest.get("resolved_version")
                if isinstance(recorded, str):
                    updates.setdefault("modules." + key + ".database_version", recorded)
        _validate_updates(spec, updates)
        version = updates.get("modules." + key + ".database_version", "")
    if not version and _file(root / "version.txt"):
        with (root / "version.txt").open("r", errors="replace") as handle:
            version = handle.read(120).strip()
    return {"id": key, "path": str(local_path(value)) if key in {"prott5", "deep_catalogue"} else str(database.resolve()),
            "folder": str(root), "updates": updates, "version": version,
            "receipt": receipt, "status": "Layout recognized", "checked_at": now()}


def _roots(store, tool, cfg, extra):
    roots = []
    if extra:
        chosen = local_path(extra)
        if not chosen.is_dir():
            raise ValueError("Choose an existing folder to scan.")
        roots.append(chosen)
    for row in panel(store, tool)["rows"]:
        if row.get("path"):
            try:
                path = local_path(row["path"])
                roots.append(path if path.is_dir() else path.parent)
            except (OSError, ValueError):
                pass
    roots.append(store.home / "resources" / tool)
    roots.append(store.home / "envs" / tool)
    for download in store.all("database_downloads"):
        if download.get("tool") == tool:
            roots.append(Path(download["destination"]))
    if tool == "basis":
        raw = _get(cfg, "resources.directory", "resources")
        if raw != "resources":
            roots.append(local_path(raw))
    for install in store.all("installs"):
        if install.get("tool") != tool:
            continue
        for key in ("original_source", "source"):
            if install.get(key):
                base = Path(install[key])
                roots.extend((base / "resources", base / "db", base / ".snakemake/conda", base))
        for key in ("rule_cache", "controller"):
            if install.get(key):
                roots.append(Path(install[key]))
    # Start at environment prefixes, not at Home: package databases can otherwise
    # exceed the depth limit before reaching share/ or site-packages/.
    roots.extend(environment_paths(store))
    home = Path.home()
    for parent in (home / "bactomics", home / "databases", home / "db"):
        if parent.is_dir():
            roots.append(parent)
            entries, _ = _children(parent)
            for entry in entries:
                base = Path(entry.path)
                for relative in ("resources", "db", "databases", ".snakemake/conda"):
                    roots.append(base / relative)
    roots.extend((home, Path("/data"), Path("/databases"), Path("/mnt"), Path("/media"), Path("/opt")))
    for var in ("CONDA_PREFIX", "CONDA_ENVS_PATH"):
        roots.extend(Path(p) for p in os.environ.get(var, "").split(os.pathsep) if p)
    return list(dict.fromkeys(p.resolve() for p in roots if p.is_dir()))


def scan(store, tool, extra=""):
    cfg = parse_config(_text(store, tool))
    current = panel(store, tool)
    specs = [s for s in CATALOG[tool] if not s.get("managed")]
    found = {s["id"]: {} for s in specs}
    invalid = []
    configured = {}
    rejected = set()
    def add(key, path, explicit=False, recognized=False):
        try:
            result = inspect(store, tool, key, str(path), cfg)
            keypath = result["path"]
            if explicit:
                configured[key] = keypath
            prior = found[key].get(keypath)
            if not prior or (result["receipt"] and not prior["receipt"]):
                found[key][keypath] = result
        except (OSError, ValueError, RuntimeError) as exc:
            identity = (key, str(path))
            if (explicit or recognized) and identity not in rejected and len(invalid) < 200:
                rejected.add(identity)
                invalid.append({"id": key, "path": str(path), "message": str(exc), "configured": explicit})
    for row in current["rows"]:
        if row.get("path"):
            add(row["id"], row["path"], True)
    roots = _roots(store, tool, cfg, extra)
    queue = deque((p, 0) for p in roots)
    seen = set()
    reasons = set()
    inaccessible = 0
    deadline = time.monotonic() + MAX_SECONDS
    while queue:
        if len(seen) >= MAX_DIRS or time.monotonic() >= deadline:
            reasons.add("folder/time limit")
            break
        raw, depth = queue.popleft()
        try:
            path = raw.resolve()
            if path in seen:
                continue
            seen.add(path)
            entries, limited = _children(path)
            if limited:
                reasons.add("entries per folder limit")
            names = {e.name for e in entries}
            receipt = bool(names & {"provenance.json", "completed.json"})
            for spec in specs:
                recognized = spec.get("hint") in names
                matched_receipt = receipt and tool == "basis" and bool(_receipt(path, spec)[0])
                if matched_receipt or recognized:
                    add(spec["id"], path, recognized=True)
            for entry in sorted(entries, key=lambda e: e.name.casefold()):
                if time.monotonic() >= deadline:
                    reasons.add("folder/time limit")
                    break
                if entry.name == ".snakemake":
                    cache = Path(entry.path) / "conda"
                    if cache.is_dir():
                        queue.appendleft((cache, 0))
                    continue
                if entry.name in SKIP or entry.name.startswith("."):
                    continue
                try:
                    if entry.is_dir():
                        if depth < MAX_DEPTH:
                            queue.append((Path(entry.path), depth + 1))
                        else:
                            reasons.add("depth limit")
                except OSError:
                    inaccessible += 1
        except (OSError, RuntimeError):
            inaccessible += 1
    for spec in specs:
        key = spec["id"]
        def ranking(candidate):
            if candidate["path"] == configured.get(key):
                return (0, candidate["path"])
            if key == "busco" and Path(candidate["path"]).name == current["lineage"]:
                return (1, candidate["path"])
            return (2 if candidate["receipt"] else 3, candidate["path"])
        choices = sorted(found[key].values(), key=ranking)
        for i, candidate in enumerate(choices):
            candidate["preferred"] = i == 0
            candidate["reason"] = ("Current valid location" if ranking(candidate)[0] == 0 else
                                   "Matches configured lineage" if ranking(candidate)[0] == 1 else
                                   "Completed resource receipt found" if candidate["receipt"] else
                                   "Recognized layout; choose the release appropriate for your run")
        found[key] = choices
    return {"tool": tool, "revision": current["revision"], "candidates": found, "invalid": invalid,
            "roots": [str(p) for p in roots], "visited": len(seen), "limited": bool(reasons),
            "limits": sorted(reasons), "inaccessible": inaccessible, "checked_at": now(),
            "scope": f"Known resource folders, registered Conda environments and Snakemake caches, up to {MAX_DEPTH} levels deep per root. Symlinks are followed with cycle and time limits. Add a specific scan folder when the scan is limited."}


def _hybas_layout(store, paths, lineage):
    identity = {key: str(value) for key, value in paths.items()}
    identity["lineage"] = lineage
    digest = revision(json.dumps(identity, sort_keys=True))[:24]
    root = store.home / "resources/hybas/locations" / digest
    root.mkdir(parents=True, exist_ok=True)
    (root / "busco").mkdir(exist_ok=True)
    for key, alias in (("kraken", root / "kraken"), ("busco", root / "busco" / lineage)):
        target = paths[key]
        if alias.is_symlink():
            if Path(os.readlink(alias)) != target:
                raise ValueError("Managed database link changed; refusing to replace it: " + str(alias))
        elif alias.exists():
            raise ValueError("Managed database location already contains a file or directory: " + str(alias))
        else:
            alias.symlink_to(target, target_is_directory=True)
    return root


def save(store, tool, changes, expected_revision):
    if not isinstance(changes, dict) or not changes:
        raise ValueError("Choose or check a database location first.")
    original = _text(store, tool)
    if revision(original) != expected_revision:
        raise ValueError("Defaults changed since this page was loaded. Reload locations before saving.")
    cfg = parse_config(original)
    locations = store.get("database_locations", tool, {})
    checked = {}
    for key, value in changes.items():
        _spec(tool, key)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError("Choose a folder or explicitly reset this resource to pipeline defaults.")
        checked[key] = inspect(store, tool, key, value, cfg) if value is not None else None
    if tool == "hybas":
        paths = _hybas_paths(store, cfg)
        lineage = str(cfg.get("busco_lineage", "bacteria_odb10"))
        for key, item in checked.items():
            if item:
                paths[key] = Path(item["path"])
                if key == "busco":
                    lineage = paths[key].name
            else:
                paths[key] = store.home / "resources/hybas/db" / ("standard" if key == "kraken" else "busco/bacteria_odb10")
                if key == "busco":
                    lineage = "bacteria_odb10"
        if not re.fullmatch(r"[A-Za-z0-9_.-]+_odb[0-9]+", lineage):
            raise ValueError("Choose a named BUSCO lineage before saving database locations.")
        root = _hybas_layout(store, {k: v.resolve() for k, v in paths.items()}, lineage)
        cfg.update(db_root=str(root), kraken_db_name="kraken", busco_lineage=lineage)
        # Keep native download actions targeting the selected lineage in this layout.
        previous = cfg.get("busco_download_lineages", [])
        cfg["busco_download_lineages"] = list(dict.fromkeys([lineage, *(previous if isinstance(previous, list) else [])]))
    else:
        for key, item in checked.items():
            spec = _spec(tool, key)
            # Replace only fields owned by this database; keep all analysis settings.
            for field in spec["fields"]:
                _set(cfg, field, item["updates"].get(field) if item else None)
            if item:
                locations[key] = {"path": item["path"], "fields": _fields(cfg, spec)}
            else:
                locations.pop(key, None)
    text = yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True)
    parse_config(text)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT body FROM items WHERE kind='configs' AND id=?", (tool,)).fetchone()
        actual = json.loads(row[0]) if row else template(tool)
        if revision(actual) != expected_revision:
            raise ValueError("Defaults changed while checking locations. Reload locations before saving.")
        for kind, value in (("configs", text), ("database_locations", locations)):
            db.execute("INSERT INTO items VALUES (?,?,?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body", (kind, tool, json.dumps(value)))
    return text

