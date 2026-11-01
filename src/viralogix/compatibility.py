"""Version and binding overview from application metadata and stored records only."""
import importlib.metadata
import json
import platform
import sys

from packaging.specifiers import SpecifierSet, InvalidSpecifier

from . import __version__, updates
from .catalog import PIPELINES, versions
from .store import now

NOTICE = ('Adapter support is matched by exact commit, not a branch or release name. '
          'Runner requirements and check dates are stored records, not fresh package probes. '
          'This overview does not inspect source/configuration integrity, inputs, databases or tool environments, '
          'and does not certify a run as ready. Use the existing setup checks and run validation to verify them. '
          'Refresh rereads local records; it does not contact GitHub, change active versions or start jobs. '
          'Exports include local paths and run labels and are not redacted.')


def source_state(tool, commit, store=None):
    spec = PIPELINES.get(tool)
    if not spec:
        return 'unknown_pipeline'
    if not commit:
        return 'missing_commit'
    if commit == spec['commit']:
        return 'recommended'
    if commit in spec.get('previous_commits', []):
        return 'earlier_supported'
    from .catalog import supported
    return 'contract_supported' if supported(tool, commit, store) else 'unreviewed'


def panel(store):
    update = updates.status(store)
    try:
        package = importlib.metadata.metadata('viralogix')
        installed = package.get('Version')
        requirement = package.get('Requires-Python')
    except importlib.metadata.PackageNotFoundError:
        installed = requirement = None
    try:
        python_matches = platform.python_version() in SpecifierSet(requirement) if requirement else None
    except InvalidSpecifier:
        python_matches = None
    app = {'running_version': __version__, 'installed_version': installed,
           'python_version': platform.python_version(), 'python_requirement': requirement,
           'python_matches': python_matches, 'python_executable': sys.executable,
           'platform': platform.system(), 'managed_execution_platform': platform.system() == 'Linux',
           'restart_required': bool(update['restart_required'] or installed and installed != __version__), 'active_update': update['active_job']}
    items = store.all('installs')
    by_id = {item['id']: item for item in items}
    jobs = store.jobs()
    pipelines = []
    for tool, spec in PIPELINES.items():
        active = store.get('settings', 'active-' + tool)
        catalog = versions(store, tool)
        refs = [r for r in catalog['versions'] if r['kind'] != 'pinned']
        pipelines.append({'tool': tool, 'name': spec['name'], 'active_installation': active,
            'active_registered': bool(active in by_id and by_id[active].get('tool') == tool),
            'commits': [{'commit': commit, 'support': source_state(tool, commit, store),
                         'url': f"https://github.com/{spec['repo']}/tree/{commit}"}
                        for commit in [spec['commit'], *spec.get('previous_commits', [])]],
            'catalog_checked_at': catalog.get('checkedAt'),
            'catalog_origin': 'Saved GitHub response' if catalog.get('live') else 'Bundled catalogue',
            'unreviewed_catalog_refs': sum(source_state(tool, r.get('commit'), store) == 'unreviewed' for r in refs)})
    installations = []
    for item in items:
        tool = item.get('tool')
        commit = item.get('version', {}).get('commit')
        checks = [j for j in jobs if j['kind'] == 'check' and j['payload'].get('installation') == item['id']]
        latest = checks[0] if checks else None
        requirements = item.get('controller_requirements') or {}
        installations.append({'id': item['id'], 'tool': tool,
            'ref': item.get('version', {}).get('ref'), 'commit': commit,
            'support': source_state(tool, commit, store), 'active': store.get('settings', 'active-' + str(tool)) == item['id'],
            'source': item.get('source'), 'runner': item.get('controller'),
            'runner_origin': item.get('controller_origin', 'Not recorded'),
            'setup_recorded': bool(item.get('ready') and item.get('controller')),
            'checked_at': item.get('checked'),
            'requirements': {key: requirements.get(key) for key in ('python', 'snakemake')},
            'latest_check': {k: latest.get(k) for k in ('id', 'status', 'created', 'finished')} if latest else None})
    archived = {r['id'] for r in store.all('run_visibility') if r.get('archived')}
    runs = []
    for run in store.all('runs'):
        tool, commit = run.get('tool'), run.get('commit')
        item = by_id.get(run.get('installation'))
        if not item:
            binding = 'missing_installation'
        elif item.get('tool') != tool or item.get('version', {}).get('commit') != commit:
            binding = 'source_mismatch'
        elif not item.get('ready') or not item.get('controller'):
            binding = 'setup_needed'
        else:
            binding = 'recorded_match'
        support = source_state(tool, commit, store)
        valid_support = support in {'recommended', 'earlier_supported', 'contract_supported'}
        recorded_runner = run.get('controller')
        current_runner = item.get('controller') if item else None
        validated_runner = run.get('validated_controller', recorded_runner)
        validation = ('not_recorded' if not run.get('dry_run_ok') else
                      'binding_unavailable' if binding != 'recorded_match' else
                      'same_runner_path' if validated_runner == current_runner else 'runner_changed')
        latest = next((j for j in jobs if j['kind'] == 'workflow' and j['payload'].get('run_id') == run['id']
                       and j['payload'].get('action') == 'run'), None)
        runs.append({'id': run['id'], 'label': run.get('label', run['id']), 'tool': tool,
            'commit': commit, 'support': support, 'installation': run.get('installation'),
            'binding': binding, 'archived': run['id'] in archived,
            'active_installation': store.get('settings', 'active-' + str(tool)),
            'uses_active_selection': store.get('settings', 'active-' + str(tool)) == run.get('installation'),
            'recorded_runner': recorded_runner, 'current_runner': current_runner,
            'runner_changed_since_draft': bool(current_runner and current_runner != recorded_runner),
            'validation': validation, 'validated_runner': validated_runner, 'validated_at': run.get('validated'),
            'needs_review': not valid_support or binding != 'recorded_match' or validation != 'same_runner_path',
            'latest_execution': {k: latest.get(k) for k in ('id', 'status', 'finished')} if latest else None})
    return {'schema': 1, 'created_at': now(), 'app': app, 'pipelines': pipelines,
            'installations': installations, 'runs': runs, 'notice': NOTICE}


def export(doc):
    return {'name': 'viralogix-compatibility.json', 'type': 'application/json',
            'text': json.dumps(doc, ensure_ascii=False, indent=2) + '\n'}
