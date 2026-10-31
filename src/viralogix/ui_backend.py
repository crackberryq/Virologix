"""Presentation adapters for existing local utilities; no pipeline execution."""
from dataclasses import asdict
from pathlib import Path
import os
import psutil
from . import __version__
from .samples import register
from .cfasta import parse, export_consensus

MAX_PREVIEW_BYTES = 10 * 1024 * 1024

def snapshot(store):
    return {"version": __version__, "home": str(store.home),
            "samples": store.all("samples"), "cpu": os.cpu_count(),
            "ram_gib": round(psutil.virtual_memory().available / 2**30, 2),
            "desktop": bool(os.environ.get("VIRALOGIX_DESKTOP_SESSION"))}

def handle_request(store, request):
    response = {"id": request.get("id"), "action": request.get("action")}
    args = request.get("args") or {}
    try:
        action = request.get("action")
        if action == "register":
            register(store, *(str(args.get(key, "")).strip() for key in ("sample", "r1", "r2", "reference")))
            response["message"] = "Sample registered. Input files remain in their original locations."
        elif action == "inspect":
            text = args.get("text", "")
            if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_PREVIEW_BYTES:
                raise ValueError("Choose a cFASTA file no larger than 10 MiB for interactive inspection.")
            entries = parse(text)
            response.update(entries=[asdict(entry) for entry in entries], consensus=export_consensus(entries),
                            filename=Path(str(args.get("name", "inspection.cfasta"))).stem + ".consensus.fasta")
        elif action == "restart-as-browser":
            from .desktop import request_browser
            if not request_browser(store):
                raise ValueError("Browser restart is available only in a managed desktop session.")
            response["message"] = "Browser restart requested."
        elif action != "refresh":
            raise ValueError("Unknown workspace action.")
        response["ok"] = True
    except (ValueError, UnicodeError, OSError) as exc:
        response.update(ok=False, message=str(exc))
    return response
