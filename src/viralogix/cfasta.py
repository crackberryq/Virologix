"""Read the supplied draft format; validate syntax, not biological truth."""
from dataclasses import dataclass
import math
import re

COLUMNS = "#id\tabundance\tconfidence\tsupport\tresolution\tspan\tedits"

@dataclass
class Entry:
    metadata: dict
    consensus: str
    haplotypes: list

def parse(text):
    entries = []
    current = None
    state = None
    seen = set()
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith(">"):
            if current is not None and state != "rows":
                raise ValueError(f"Line {number}: missing haplotype table.")
            fields = line[1:].split("|")
            meta = {}
            for field in fields:
                key, sep, value = field.partition("=")
                if not sep or not value or key in meta:
                    raise ValueError(f"Line {number}: malformed or duplicate header field.")
                meta[key] = value
            if not {"sample", "segment", "length", "format"} <= meta.keys():
                raise ValueError("Missing required header fields.")
            if meta["format"] != "cFASTA-v1.0":
                raise ValueError("Unsupported cFASTA version.")
            key = (meta["sample"], meta["segment"])
            if key in seen:
                raise ValueError("Duplicate sample/segment entry.")
            seen.add(key)
            current = Entry(meta, "", [])
            entries.append(current)
            state = "sequence"
        elif current is None:
            raise ValueError("Expected a cFASTA header.")
        elif line == "#HAPLOTYPES" and state == "sequence":
            state = "columns"
        elif state == "columns":
            if line != COLUMNS:
                raise ValueError("Invalid tab-delimited haplotype columns.")
            state = "rows"
        elif state == "sequence":
            if not re.fullmatch("[ACGTN]+", line):
                raise ValueError("Consensus must contain uppercase A, C, G, T or N.")
            current.consensus += line
        elif state == "rows":
            row = line.split("\t")
            if len(row) != 7:
                raise ValueError(f"Line {number}: expected seven tab-delimited columns.")
            current.haplotypes.append(dict(zip(COLUMNS[1:].split("\t"), row)))
        else:
            raise ValueError(f"Line {number}: unexpected content.")
    if not entries or state != "rows":
        raise ValueError("Empty or incomplete cFASTA file.")
    for entry in entries:
        validate(entry)
    return entries

def validate(entry):
    length = int(entry.metadata["length"])
    if length < 1 or length != len(entry.consensus):
        raise ValueError("Consensus length does not match header.")
    ids = set()
    for row in entry.haplotypes:
        if not row["id"] or row["id"] in ids:
            raise ValueError("Duplicate or empty haplotype ID.")
        ids.add(row["id"])
        abundance = float(row["abundance"])
        if not math.isfinite(abundance) or not 0 <= abundance <= 1:
            raise ValueError("Abundance must be finite and between zero and one.")
        if not row["support"].isdigit():
            raise ValueError("Support must be a nonnegative integer.")
        if row["confidence"] not in {"HIGH", "MED", "LOW", "UNRESOLVED"}:
            raise ValueError("Invalid confidence.")
        if row["resolution"] not in {"GLOBAL", "LOCAL", "FRAGMENT", "INFERRED"}:
            raise ValueError("Invalid resolution.")
        match = re.fullmatch(r"(\d+)-(\d+)", row["span"])
        if not match:
            raise ValueError("Invalid span.")
        start, end = map(int, match.groups())
        if not 1 <= start <= end <= length:
            raise ValueError("Span outside consensus.")
        if row["resolution"] == "GLOBAL" and (start, end) != (1, length):
            raise ValueError("GLOBAL requires a full-segment span.")
        if row["edits"] == ".":
            continue
        previous_end = 0
        for edit in row["edits"].split(";"):
            match = re.fullmatch(r"(\d+):(?:([ACGTN])>([ACGTN])|\+([ACGT]+)|-([1-9]\d*))", edit)
            if not match:
                raise ValueError("Invalid edit grammar.")
            pos = int(match[1])
            stop = pos + int(match[5]) - 1 if match[5] else pos
            if not start <= pos <= stop <= end or pos <= previous_end:
                raise ValueError("Edits must be sorted, nonoverlapping and inside the span.")
            if match[2] and entry.consensus[pos-1] != match[2]:
                raise ValueError("Edit reference does not match consensus.")
            previous_end = stop

def export_consensus(entries):
    blocks = []
    for index, entry in enumerate(entries, 1):
        description = "|".join(f"{key}={entry.metadata[key]}" for key in ("sample", "segment"))
        blocks.append(f">VG{index:06d} {description}\n" + "\n".join(entry.consensus[i:i+80] for i in range(0, len(entry.consensus), 80)))
    return "\n".join(blocks) + "\n"
