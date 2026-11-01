import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from . import __version__
from .store import workspace

def main():
    parser = argparse.ArgumentParser(description="Viralogix local virology workspace")
    parser.add_argument("--version", action="version", version=__version__)
    subs = parser.add_subparsers(dest="command", required=False)
    serve = subs.add_parser("serve")
    serve.add_argument("--home")
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument("--no-browser", action="store_true")
    serve.add_argument("--host")
    serve.add_argument("--app-window", action="store_true")
    serve.add_argument("--desktop-control")
    serve.add_argument("--desktop-session")
    subs.add_parser("doctor")
    subs.add_parser("update", help="Install the latest main commit; stop the app first")
    for command in ("validate", "export-consensus"):
        sub = subs.add_parser(command)
        sub.add_argument("--input", required=True, type=Path)
        if command == "export-consensus":
            sub.add_argument("--output", required=True, type=Path)
    argv = sys.argv[1:]
    if argv and argv[0] in {"--home", "--host", "--port", "--no-browser", "--app-window", "--desktop-control", "--desktop-session"}:
        argv = ["serve", *argv]
    args = parser.parse_args(argv)
    if args.command is None:
        args = parser.parse_args(["serve"])
    try:
        if args.command == "serve":
            if args.no_browser and args.app_window:
                parser.error("--no-browser and --app-window are mutually exclusive")
            from .launcher import serve as launch
            options = {"browser": not args.no_browser}
            if args.app_window:
                options["app_window"] = True
            if args.desktop_control:
                options.update(desktop_control=args.desktop_control, desktop_session=args.desktop_session)
            raise SystemExit(launch(workspace(args.home), args.host, args.port, **options))
        if args.command == "update":
            from .updates import update
            update()
            return
        if args.command == "doctor":
            import psutil
            print(json.dumps({"version": __version__, "home": str(workspace()), "cpu_count": os.cpu_count(), "available_ram_gib": round(psutil.virtual_memory().available / 2**30, 2), "role": "pipeline_manager", "pipelines": ["flupop"]}, indent=2))
        else:
            raise ValueError("cFASTA processing belongs to FluPop. Use Virologix Pipelines to install and launch FluPop.")
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(2, f"Viralogix: {exc}\n")

if __name__ == "__main__":
    main()
