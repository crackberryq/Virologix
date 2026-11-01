"""Reviewed release approvals, independent of application releases.

Only the application's official registry is trusted. Pipeline self-declarations
or moving branch heads never authorize managed execution.
"""
import base64
import hashlib
import json
import re
from pathlib import Path

from .controllers import controller_requirements
from .store import now

REGISTRY = 'repos/crackberryq/Virologix/contents/compatibility/releases-v1.json?ref=main'
INTERFACE = 1


def reason(tool, row):
    from .catalog import PIPELINES
    spec = PIPELINES[tool]
    if not isinstance(row, dict):
        return 'No reviewed release contract is available.'
    if row.get('adapter_interface') != INTERFACE:
        return 'Adapter update required: unsupported adapter interface.'
    if row.get('configuration_schema') != tool + '-v1':
        return 'Adapter update required: configuration schema changed.'
    if row.get('entry_points') != {'workflow': spec['snakefile'], 'environment': spec['environment']}:
        return 'Adapter update required: workflow or runner entry point changed.'
    if row.get('repository') != spec['repo'] or not re.fullmatch('[0-9a-f]{40}', str(row.get('commit', ''))):
        return 'Release contract has an invalid repository or immutable commit.'
    if row.get('channel') not in ('stable', 'prerelease') or not row.get('tag'):
        return 'Release contract has no valid release channel/tag.'
    if row.get('tested') is not True or not re.fullmatch(
            r'https://github.com/crackberryq/[A-Za-z0-9_-]+/actions/runs/[0-9]+', str(row.get('test_run', ''))):
        return 'Release has no recorded successful adapter test review.'
    hashes = row.get('files_sha256')
    if not isinstance(hashes, dict) or not {spec['snakefile'], spec['environment']} <= hashes.keys():
        return 'Release contract lacks entry-point checksums.'
    for path, digest in hashes.items():
        if Path(path).is_absolute() or '..' in Path(path).parts or not re.fullmatch('[0-9a-f]{64}', str(digest)):
            return 'Release contract contains invalid file checksums.'
    followup = row.get('followup')
    if followup is not None:
        if (tool != 'basis' or not isinstance(followup, dict)
                or followup.get('interface') != 1
                or followup.get('entry_point') != 'Followup.smk'
                or followup.get('screening_schema') != 'basis-snakemake-run-v1'
                or 'Followup.smk' not in hashes):
            return 'Adapter update required: invalid follow-up contract or checksum.'
        parents, scopes = followup.get('parent_commits'), followup.get('scopes')
        if (not isinstance(parents, list) or any(not re.fullmatch('[0-9a-f]{40}', str(c)) for c in parents)
                or not isinstance(scopes, list) or not scopes
                or any(s not in ('all-supported', 'amrfinder-review') for s in scopes)):
            return 'Release contract has invalid follow-up parent versions or scopes.'
    runner = row.get('runner', {})
    if not re.fullmatch(r'\d+\.\d+(\.\d+)?', str(runner.get('python', ''))) or not re.fullmatch(r'\d+\.\d+\.\d+', str(runner.get('snakemake', ''))):
        return 'Release contract must pin Python and Snakemake requirements.'
    return None


def approval(store, tool, commit):
    if store is None:
        return None
    row = store.get('release_approvals', tool + ':' + commit)
    return row if row and not reason(tool, row) else None


def refresh(store, tool):
    from .catalog import api, fetch_versions
    # Commit the new catalogue only after both requests and validation succeed.
    catalog = fetch_versions(tool)
    if tool=='flupop':
        store.put('catalog',tool,catalog)
        return catalog
    response = api(REGISTRY)
    doc = json.loads(base64.b64decode(response['content'], validate=False))
    if doc.get('schema_version') != 1 or not isinstance(doc.get('releases'), list):
        raise ValueError('Unsupported compatibility registry schema; cached catalogue retained.')
    reviewed = [r for r in doc['releases'] if isinstance(r, dict) and r.get('tool') == tool]
    by_commit = {r.get('commit'): r for r in reviewed}
    for row in catalog['versions']:
        review = by_commit.get(row['commit'])
        if review:
            issue = reason(tool, review)
            if not issue and row['kind'] == 'release' and (row['ref'] != review['tag'] or row['prerelease'] != (review['channel'] == 'prerelease')):
                issue = 'Release tag/channel does not match its reviewed contract.'
            row['compatibility_reason'] = issue or 'Reviewed adapter contract v1; source preflight required.'
            if not issue and row['kind'] == 'release':
                key = tool + ':' + row['commit']
                previous = store.get('release_approvals', key)
                if previous is not None and previous != review:
                    raise ValueError('Reviewed contract changed for an existing immutable commit; previous approval retained.')
                store.put('release_approvals', key, review)
    catalog['registry_checked_at'] = now()
    store.put('catalog', tool, catalog)
    return catalog


def preflight(store, tool, commit, source):
    row = approval(store, tool, commit)
    if not row:
        from .catalog import PIPELINES
        spec = PIPELINES[tool]
        if commit in [spec['commit'], *spec.get('previous_commits', [])]:
            return  # Existing releases retain their legacy adapter checks.
        raise ValueError('This commit has no compatible reviewed release contract.')
    root = Path(source).resolve()
    for name, digest in row['files_sha256'].items():
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('Release compatibility preflight failed for ' + name)
    actual = controller_requirements((root / row['entry_points']['environment']).read_bytes())
    if actual != row['runner']:
        raise ValueError('Release runner requirements differ from the reviewed contract.')
