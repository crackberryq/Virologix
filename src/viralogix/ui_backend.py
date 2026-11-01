"""Presentation adapters for registry and external pipeline management."""
import os
import psutil
from . import __version__, updates
from .samples import register
from .runs import register_folder, save_draft, start_run, archive_run, browse_folder
from .pipelines import installation, task_snapshot, handle_pipeline

def snapshot(store):
    return {"version": __version__, "home": str(store.home),
            "app_update": updates.status(store), "flupop": installation(store), "tasks": task_snapshot(store), "samples": store.all("samples"), "cloud_runs": store.all("cloud_runs"), "cpu": os.cpu_count(),
            "ram_gib": round(psutil.virtual_memory().available / 2**30, 2),
            "desktop": bool(os.environ.get("VIRALOGIX_DESKTOP_SESSION"))}

def handle_request(store, request):
    response = {"id": request.get("id"), "action": request.get("action")}
    args = request.get("args") or {}
    try:
        action = request.get("action")
        if action=='app-check':
            response.update(updates.refresh(store))
        elif action=='app-install':
            response.update(updates.request_update(store,args.get('release_id'),request.get('id')))
        elif action in {"cloud-demo", "cloud-package", "cloud-open", "flupop-install", "flupop-resume"}:
            response.update(handle_pipeline(store, action, args, request.get("id")))
        elif action == 'browse':response.update(browse_folder(args))
        elif action == 'sample-add':response.update(register_folder(store,args))
        elif action == 'run-save':response.update(save_draft(store,args))
        elif action == 'run-start':response.update(start_run(store,args,request.get('id')))
        elif action == 'run-archive':response.update(archive_run(store,args))
        elif action == "register":
            register(store, *(str(args.get(key, "")).strip() for key in ("sample", "r1", "r2", "reference")))
            response["message"] = "Sample registered. Input files remain in their original locations."
        elif action == "restart-as-browser":
            from .desktop import request_browser
            if not request_browser(store):
                raise ValueError("Browser restart is available only in a managed desktop session.")
            response["message"] = "Browser restart requested."
        elif action != "refresh":
            raise ValueError("Unknown workspace action.")
        response["ok"] = True
    except (ValueError, UnicodeError, OSError, TypeError, KeyError) as exc:
        response.update(ok=False, message=str(exc))
    return response
