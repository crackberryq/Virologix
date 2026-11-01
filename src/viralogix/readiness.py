"""Read-only evidence for a frozen run, with explicit native environment inventory."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from .catalog import supported
from .runs import check_run_files, command, current_controller, dry_run_current, tree_digest
from .store import now


def identity(store, run):
    fields = [run['config_sha256'], run['workflow_sha256'], run.get('rule_cache'), current_controller(store, run)]
    return hashlib.sha256(json.dumps(fields).encode()).hexdigest()


def parse_inventory(text, folder, cache):
    """Read native paths; never calculate a replacement environment hash."""
    folder, cache = Path(folder).resolve(), Path(cache).resolve()
    rows, header = [], False
    for line in text.splitlines():
        parts = line.split('\t')
        if parts == ['environment', 'container', 'location']:
            header = True
            continue
        if not header or not line.strip():
            continue
        if len(parts) != 3:
            raise ValueError('Could not read a native environment inventory row. See the job log.')
        recipe, container, location = parts
        if container:
            raise ValueError('Container environments need a separate inventory check.')
        source, prefix = (folder / recipe).resolve(), (folder / location).resolve()
        if not source.is_relative_to(folder) or not source.is_file():
            raise ValueError('The workflow reported an environment recipe outside its saved source.')
        if prefix.parent != cache or not re.fullmatch(r'[a-f0-9]{8}(?:[a-f0-9]{24})?_?', prefix.name):
            raise ValueError('The workflow reported an unexpected environment cache path.')
        rows.append({'name': source.stem, 'recipe': str(source), 'path': str(prefix)})
    if not header:
        raise ValueError('Could not read the native environment inventory. See the job log.')
    return rows


def environment_state(row):
    prefix = Path(row['path'])
    if not (prefix / 'conda-meta/history').is_file():
        return 'Missing'
    if not prefix.with_suffix('.env_setup_done').is_file():
        return 'Incomplete'
    return 'Available'


def check_environments(ctx, run):
    # Invalidate older evidence before starting, including failed or cancelled checks.
    receipt = {'id': run['id'], 'identity': identity(ctx.store, run), 'status': 'checking', 'job': ctx.job['id']}
    ctx.store.put('run_environment_checks', run['id'], receipt)
    folder = Path(run['folder']) / 'workflow'
    listing = Path(run['folder']) / ('environments-' + ctx.job['id'] + '.tsv')
    with listing.open('w') as output:
        ctx.command(command(ctx.store, run, 'check-environments'), cwd=folder, stdout=output)
    text = listing.read_text()
    ctx.write(text)
    rows = parse_inventory(text, folder, run.get('rule_cache') or ctx.store.home / 'envs' / run['tool'])
    ctx.check_cancel()
    receipt.update(status='checked', checked_at=now(), rows=rows)
    ctx.store.put('run_environment_checks', run['id'], receipt)
    for row in rows:
        ctx.write(row['name'] + ': ' + environment_state(row) + ' · ' + row['path'])
    ctx.write('Inventory checked without installing or repairing environments. The current workflow plan determines this list; later checkpoint environments remain guarded at execution.')


def panel(store, run):
    """Checks are scoped and dated; no universal Ready claim or environment writes."""
    rows = []
    def row(key, title, state, text, level='info', checked_at=None):
        item = dict(id=key, title=title, state=state, text=text, level=level, checked_at=checked_at)
        rows.append(item)
        return item
    checked_at = now()
    blocked = False
    try:
        check_run_files(run)
        row('inputs', 'Inputs and saved files', 'Unchanged', 'File sizes, timestamps and staged input links match this draft.', 'good', checked_at)
    except (OSError, ValueError, KeyError) as exc:
        blocked = True
        row('inputs', 'Inputs and saved files', 'Needs attention', str(exc), 'error', checked_at)
    try:
        current_controller(store, run)
        if not supported(run['tool'], run['commit'], store):
            raise ValueError('This source version needs a supported execution adapter.')
        if tree_digest(Path(run['folder']) / 'workflow') != run['workflow_sha256']:
            raise ValueError('The saved workflow source changed. Create a new draft from a clean installation.')
        row('pipeline', 'Pipeline and runner', 'Setup recorded', 'The saved source is unchanged and its runner is configured. Native validation checks execution.', 'info', checked_at)
    except (OSError, ValueError, KeyError) as exc:
        blocked = True
        row('pipeline', 'Pipeline and runner', 'Needs setup', str(exc), 'error', checked_at)
    from . import preflight
    host = preflight.panel(store, run)
    rows.extend(host['rows'])
    # Output permissions can block execution while a diagnostic dry-run remains useful.
    execution_blocked = blocked or host['blocked']
    validated = dry_run_current(store, run) and not blocked
    row('configuration', 'Native validation', 'Dry-run passed' if validated else 'Validation needed',
        'The workflow accepted this saved configuration with the current runner.' if validated else 'Validate this run before installing tools or starting execution.',
        'info' if validated else 'pending', run.get('validated') if validated else None)
    row('databases', 'Database paths', 'Frozen in this draft',
        'Review the saved paths in Databases. Native validation and execution perform the applicable resource checks.', 'info')
    receipt = store.get('run_environment_checks', run['id'], {})
    inventory = []
    try:
        fresh = not blocked and receipt.get('status') == 'checked' and receipt.get('identity') == identity(store, run)
    except (ValueError, KeyError):
        fresh = False
    if fresh:
        inventory = [{**r, 'state': environment_state(r)} for r in receipt['rows']]
        missing = sum(r['state'] != 'Available' for r in inventory)
        row('environments', 'Tool environments', f'{missing} need installation' if missing else f'{len(inventory)} available' if inventory else 'None listed',
            'Checks for completed environment folders in this run’s cache. Tool functionality is checked during execution; later checkpoints may require additional environments.',
            'warning' if missing else 'info', receipt['checked_at'])
    else:
        missing = 0
        row('environments', 'Tool environments', 'Check this run’s cache',
            'Check environments after native validation. This reads the workflow inventory and never installs or repairs tools.', 'pending')
    return {'rows': rows, 'environments': inventory, 'destinations': host['destinations'],
            'checked_at': checked_at, 'blocked': blocked, 'execution_blocked': execution_blocked,
            'validated': validated, 'environment_check_current': fresh, 'missing_environments': missing,
            'next': 'review' if execution_blocked else 'dry-run' if not validated else 'prepare' if missing else 'run' if fresh else 'check-environments'}


def job_guidance(store, job):
    """Evidence-backed hints, never a diagnosis or an automatic repair request."""
    if job['status'] not in {'failed', 'interrupted'}:
        return None
    from .support import log_tail
    text, scope = log_tail(store, job['id'], max_bytes=24000)
    # Match complete bounded lines only; shell commands and huge payloads are not evidence.
    lines = [line for line in text.splitlines() if not line.lstrip().startswith('$ ')]
    error = str(job.get('error') or '')[:2048]
    if error:
        lines.append(error)
    patterns = [
        ('storage', r'No space left on device|Disk quota exceeded|\[Errno (?:28|122)\]',
         'Storage space or quota blocked this job',
         'Review the output, temporary and environment-cache disks and their quotas. Free space deliberately, then review the saved run before resuming.'),
        ('permissions', r'Permission denied|Read-only file system|PermissionError|\[Errno (?:13|30)\]',
         'A file location could not be accessed',
         'Review the path in the error and its ownership, permissions or mount state. Use a writable location through the existing settings controls; changed run paths require a revised draft.'),
        ('environments', r'existing environments only',
         'A matching tool environment is missing or incomplete',
         'Open the saved run and check its environment cache. Install environments only when you choose to, then review the run before retrying.'),
        ('dependencies', r"(?:AttributeError[^\n]*create_2d_density|(?:ModuleNotFoundError|ImportError):[^\n]*(?:plotly|kaleido)|ValueError[^\n]*kaleido)",
         'A plotting dependency may be incompatible',
         'Open pipeline setup and Check environments to verify the installed packages and rendering. Repair environments offers the supported NanoPlot/MultiQC workaround only when its exact package conditions match.'),
        ('databases', r'(?:database[^\n]{0,180}(?:missing|not found)|(?:BUSCO|Kraken)[^\n]{0,180}(?:missing|not found))',
         'Check the database location used by this run',
         'Review the frozen database paths. If you selected a new location, apply it to a revised draft and validate that draft.'),
        ('inputs', r'Input changed since|Input is no longer accessible|Staged inputs changed|Saved configuration changed',
         'Saved inputs or configuration changed',
         'Review the original folder and create a new draft for changed inputs or settings.'),
    ]
    selected = None
    for line in lines:
        for category, pattern, title, help_text in patterns:
            if re.search(pattern, line, re.I):
                selected = (category, title, help_text, line)
                break
    category, title, help_text, evidence = selected or (
        'log', 'Cause not identified', 'Open the full log to inspect the failure before retrying.', error)
    if job['status'] == 'interrupted':
        category, title = 'interrupted', 'The worker was interrupted'
        help_text = ('Review the retained outputs and log, then validate the saved run before Run / resume. '
                     'An interruption does not establish which tasks completed. Existing scheduler locks are not removed automatically.')
        evidence = error or 'The job was recorded as interrupted during worker recovery.'
    steps = re.findall(r'(?:Error in rule|Error in checkpoint) ([A-Za-z0-9_.-]{1,120})(?=[:\s]|$)', text)
    return {'title': title, 'text': help_text, 'category': category,
            'run_id': job['payload'].get('run_id'), 'step': steps[-1] if steps else None,
            'evidence': evidence[:1200], 'confidence': 'Recorded interruption' if category == 'interrupted' else 'Possible cause' if selected else 'Unknown',
            'scope': 'Hints use a bounded log excerpt and the recorded job error; the first error or another tool log may be missing.',
            'log_status': scope['status']}
