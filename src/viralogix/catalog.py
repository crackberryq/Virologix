"""GitHub releases are resolved to immutable commits before installation."""
from __future__ import annotations
import json
import copy
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import quote
from .store import now
from . import __version__

DATA = Path(__file__).parent / "data"
PIPELINES = {'flupop': {'name':'FluPop','repo':'crackberryq/Viromics_FluPop',
    'preferred':'main','commit':'cff5067e7b75af576e4417a5ae12b6ec0837e643',
    'previous_commits':['180d6a6f9759c1a078e8ea8337025f1d3ee7a0d9'],
    'snakefile':'workflow/Snakefile','environment':'environment.yml'}}


def api(path):
    req = Request("https://api.github.com/" + path,
                  headers={"User-Agent": "Virologix/" + __version__, "Accept": "application/vnd.github+json"})
    with urlopen(req, timeout=30) as response:
        return json.load(response)


def pages(path):
    rows = []
    for page in range(1, 21):
        batch = api(path + ("&" if "?" in path else "?") + f"per_page=100&page={page}")
        rows.extend(batch)
        if len(batch) < 100:
            return rows
    raise ValueError("GitHub listing exceeded 2,000 entries; narrow the catalogue before installation")


def fetch_versions(tool):
    spec = PIPELINES[tool]
    base = "repos/" + spec["repo"]
    rows = []
    for branch in pages(base + "/branches"):
        name = branch["name"]
        rows.append(dict(id="branch:" + name, kind="branch", ref=name, name=("MICP Scope development" if tool == "micpscope" and name == "main" else name),
                         commit=branch["commit"]["sha"], url=f'https://github.com/{spec["repo"]}/tree/{quote(name, safe="")}',
                         preferred=name == spec["preferred"], prerelease=False))
    for release in pages(base + "/releases"):
        if release.get("draft"):
            continue
        tag = release["tag_name"]
        # The commits endpoint peels annotated tags; target_commitish can be a moving branch.
        commit = api(base + "/commits/" + quote(tag, safe=""))["sha"]
        rows.append(dict(id="release:" + tag, kind="release", ref=tag,
                         name=release.get("name") or tag, commit=commit, url=release["html_url"],
                         preferred=False, prerelease=release.get("prerelease", False),
                         publishedAt=release.get("published_at"), notes=release.get("body", "")))
    rows.sort(key=lambda row: (not row["preferred"], row["kind"] != "release"))
    return {"checkedAt": now(), "versions": rows, "live": True}


def versions(store, tool):
    cached = store.get("catalog", tool)
    if not cached:
        snapshot = json.loads((DATA / "versions.json").read_text())
        pipeline = snapshot["pipelines"][tool]
        cached = {"checkedAt": pipeline.get("checkedAt", snapshot["checkedAt"]),
                  "versions": pipeline["versions"], "live": False}
    result = copy.deepcopy(cached)
    spec = PIPELINES[tool]
    # Moving branches must never hide the compatible snapshots after a refresh.
    pinned = []
    for commit in [spec["commit"], *spec.get("previous_commits", [])]:
        ref = spec.get("release_names", {}).get(commit) or (spec["preferred"] if commit == spec["commit"] else spec.get("previous_ref", spec["preferred"]))
        display_name = (ref + " — compatible snapshot") if "release_names" in spec else "Compatible legacy snapshot"
        pinned.append(dict(id="commit:" + commit, kind="pinned", ref=ref + " @ " + commit[:8],
                           name=display_name,
                           commit=commit, url=f'https://github.com/{spec["repo"]}/tree/{commit}',
                           preferred=commit == spec["commit"], prerelease=False))
    result["versions"] = pinned + [row for row in result["versions"] if row["kind"] != "pinned"]
    for row in result["versions"]:
        row["preferred"] = bool(row.get("preferred") and row["commit"] == spec["commit"])
    releases = sorted([r for r in result['versions'] if r['kind'] == 'release'],
                      key=lambda r: r.get('publishedAt') or '', reverse=True)
    result['latest_release'] = releases[0]['ref'] if releases else None
    reviewed = [r for r in releases if supported(tool, r['commit'], store)]
    result['recommended_release'] = reviewed[0]['ref'] if reviewed else None
    for row in result['versions']:
        row.setdefault('compatibility_reason', 'Reviewed legacy adapter' if supported(tool, row['commit'], store)
                       else 'No tested compatible contract for this commit; source download only.')
    return result


def supported(tool, commit, store=None):
    from .release_contract import approval
    spec = PIPELINES[tool]
    return commit in [spec["commit"], *spec.get("previous_commits", [])] or approval(store, tool, commit) is not None



