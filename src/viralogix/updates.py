"""Explicit update of the current Python environment from the project repository."""
import json
import re
import subprocess
import sys
from urllib.request import Request, urlopen

API = "https://api.github.com/repos/crackberryq/Virologix/commits/main"

def update():
    request = Request(API, headers={"User-Agent": "Viralogix", "Accept": "application/vnd.github+json"})
    with urlopen(request, timeout=30) as response:
        sha = json.load(response)["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("GitHub returned an invalid commit identifier")
    url = f"https://github.com/crackberryq/Virologix/archive/{sha}.zip"
    print(f"Installing Viralogix commit {sha}", flush=True)
    subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "--force-reinstall", "--no-deps", url], check=True)
    # Install any newly declared dependencies without forcing unrelated upgrades.
    subprocess.run([sys.executable, "-m", "pip", "install", "viralogix"], check=True)
    subprocess.run([sys.executable, "-m", "pip", "check"], check=True)
    print("Update complete. Start Viralogix again.")
