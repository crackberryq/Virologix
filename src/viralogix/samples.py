"""Local input registration only; never uploads sequencing data."""
from pathlib import Path
import re
from .store import now

def register(store, sample, r1, r2="", reference=""):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", sample):
        raise ValueError("Use a sample ID containing letters, digits, dots, underscores or hyphens.")
    paths = {}
    for key, value in (("r1", r1), ("r2", r2), ("reference", reference)):
        if not value:
            if key == "r1":
                raise ValueError("R1 is required.")
            continue
        path = Path(value).expanduser().resolve()
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"{key}: select an existing nonempty file.")
        suffixes = (".fa", ".fasta", ".fna") if key == "reference" else (".fastq", ".fq", ".fastq.gz", ".fq.gz")
        if not str(path).lower().endswith(suffixes):
            raise ValueError(f"{key}: unsupported file extension.")
        paths[key] = str(path)
    if paths.get("r2") == paths["r1"]:
        raise ValueError("R1 and R2 must be different files.")
    if store.get("samples", sample):
        raise ValueError("This sample ID is already registered.")
    return store.put("samples", sample, dict(id=sample, **paths, created=now(), status="registered"))
