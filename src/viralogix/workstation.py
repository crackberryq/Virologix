"""Opt-in, sample-free checks with per-attempt records and explicit user observations."""
from __future__ import annotations

import base64
import hashlib
import html
import json
import platform
from pathlib import Path
import shutil
import sys
import tempfile

from . import __version__
from .catalog import PIPELINES, supported
from .controllers import controller_requirements, controller_check_code
from .engine import Cancelled, find_conda
from .store import now

OBSERVATIONS = {
    'browser': 'I launched Virologix normally and its browser page opened on this PC.',
    'report': 'I opened and could read the workstation check report.',
    'download': 'I downloaded and could open the workstation JSON record.',
}
SCOPE = ('This checks local software orchestration, not analysis results, database integrity, GPU computation, '
         'Windows browser launching or recovery after a physical machine restart. Browser/report/download '
         'observations are user-reported. Each result belongs to this attempt and is not a current health guarantee.')


def selected_runner(store, iid):
    if iid is None:
        return None
    if not isinstance(iid, str):
        raise ValueError('Choose an installed runner or app-only checks.')
    item = store.get('installs', iid)
    if not item or not item.get('ready') or not supported(item['tool'], item['version']['commit'], store):
        raise ValueError('Choose a supported, configured runner.')
    definition = (Path(item['source']) / PIPELINES[item['tool']]['environment']).read_bytes()
    return {'id': iid, 'tool': item['tool'], 'commit': item['version']['commit'],
            'controller': item['controller'], 'definition_sha256': hashlib.sha256(definition).hexdigest(),
            'requirements': controller_requirements(definition), 'conda': find_conda(store)}


def request(store, iid=None):
    from .restart import current_launcher
    launcher = current_launcher(store)
    return {'runner': selected_runner(store, iid), 'requested_at': now(),
            'launcher_recorded': bool(launcher)}


def inspect(store, jid):
    if not isinstance(jid, str):
        raise ValueError('Choose a workstation check.')
    job = store.job(jid)
    if not job or job['kind'] != 'workstation':
        raise ValueError('This workstation check no longer exists.')
    result = store.get('workstation_checks', jid, {'id': jid, 'rows': [], 'observations': {}, 'created': job['created']})
    return {**result, 'job_status': job['status'], 'scope': SCOPE,
            'partial': job['status'] in {'cancelled', 'interrupted', 'failed'} or not result.get('finished'),
            'observation_labels': OBSERVATIONS}


def history(store):
    jobs = [j for j in store.jobs() if j['kind'] == 'workstation'][:20]
    return [inspect(store, j['id']) for j in jobs]


def execute_check(ctx):
    store, job = ctx.store, ctx.job
    record = {'id': job['id'], 'created': now(), 'app_version': __version__,
              'system': platform.system(), 'architecture': platform.machine(), 'python': platform.python_version(),
              'runner': job['payload'].get('runner'), 'rows': [], 'observations': {}}
    def save():
        store.put('workstation_checks', job['id'], record)
    def row(key, label, state, detail):
        record['rows'].append({'id': key, 'label': label, 'state': state, 'detail': detail, 'checked_at': now()})
        save()
        ctx.write(f'{label}: {state} — {detail}')
    def check(key, label, callback):
        ctx.check_cancel()
        try:
            detail = callback()
        except Cancelled:
            raise
        except Exception as exc:
            row(key, label, 'Failed', str(exc)[:1000])
        else:
            row(key, label, 'Passed', detail)
    save()
    row('queue', 'Worker and durable record', 'Passed', 'The background worker started this requested job and retained its dated result.')
    row('launcher', 'Launcher supervision', 'Recorded' if job['payload'].get('launcher_recorded') else 'Not verified',
        'A live launcher record was present at request time.' if job['payload'].get('launcher_recorded') else 'No active launcher record was available at request time; manual Streamlit launches can still run these checks.')
    try:
        def storage():
            with tempfile.TemporaryDirectory(prefix='workstation-probe-', dir=store.home) as folder:
                probe = Path(folder) / 'probe.txt'
                probe.write_text('Virologix software check\n')
                assert probe.read_text() == 'Virologix software check\n'
                probe.rename(probe.with_suffix('.checked'))
            free = shutil.disk_usage(store.home).free
            return f'Created, read, renamed and removed only a temporary probe. Free workspace space: {free // 2**20} MiB. Other destinations and quotas are not verified.'
        check('storage', 'Workspace file access', storage)
        def process():
            ctx.command([sys.executable, '-c', 'print("Virologix child process passed")'], timeout=15)
            return 'An app-Python child process completed and its output reached the job log.'
        check('process', 'Child process and log', process)
        def cancellation():
            try:
                ctx.command([sys.executable, '-c', 'import time; time.sleep(120)'], stop_after=1, timeout=10)
            except Cancelled:
                ctx.check_cancel()  # A user cancelling this job is not a successful probe.
                return 'The normal SIGINT process-group stop path stopped this check’s disposable child. No analysis process was touched.'
            raise RuntimeError('The probe exited without exercising cancellation.')
        check('cancellation', 'Process cancellation', cancellation)
        runner = record['runner']
        if not runner:
            row('runner', 'Existing pipeline runner', 'Not verified', 'App-only checks were selected. No runner was installed or executed.')
        else:
            def runner_probe():
                if selected_runner(store, runner['id']) != runner:
                    raise ValueError('The selected installation or Conda path changed after this check was requested. Request a new check.')
                if not runner['conda']:
                    raise ValueError('The configured Conda executable is unavailable.')
                command = [runner['conda'], 'run', '--no-capture-output', '-p', runner['controller']]
                ctx.command([*command, 'python', '-c', controller_check_code(runner['tool'], runner['requirements'])], timeout=60)
                with tempfile.TemporaryDirectory(prefix='workstation-runner-', dir=store.home) as folder:
                    source = Path(folder) / 'Snakefile'
                    source.write_text('rule all:\n    output: "software-check.txt"\n    run:\n        from pathlib import Path\n        Path(output[0]).write_text("Virologix runner check")\n')
                    ctx.command([*command, 'snakemake', '--cores', '1', '--directory', folder,
                                 '--snakefile', str(source)], cwd=folder, timeout=90)
                    if (Path(folder) / 'software-check.txt').read_text() != 'Virologix runner check':
                        raise ValueError('The runner did not produce the expected software-only output.')
                return 'Pinned runner imports/versions and a tiny native Snakemake job passed. No tool environments or databases were installed.'
            check('runner', 'Existing pipeline runner', runner_probe)
        record['finished'] = now()
        save()
        if any(r['state'] == 'Failed' for r in record['rows']):
            raise RuntimeError('One or more workstation checks failed. Review the dated check record and job log.')
    finally:
        # Incremental rows survive cancellation, failures and subsequent attempts.
        save()


def record_observation(store, jid, key, confirmed):
    item = inspect(store, jid)
    if item['job_status'] in {'queued', 'running'} or not item.get('finished'):
        raise ValueError('Wait for this check to finish before recording observations.')
    if not isinstance(key, str) or key not in OBSERVATIONS or type(confirmed) is not bool:
        raise ValueError('Choose a valid observation and confirmation.')
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        raw = db.execute("SELECT body FROM items WHERE kind='workstation_checks' AND id=?", (jid,)).fetchone()
        record = json.loads(raw[0])
        if confirmed and key in {'report', 'download'} and not record.get('served', {}).get(key):
            raise ValueError('Open the report or request its download before confirming that observation.')
        record.setdefault('observations', {})[key] = {'confirmed': confirmed, 'recorded_at': now(), 'source': 'user-reported'}
        db.execute("UPDATE items SET body=? WHERE kind='workstation_checks' AND id=?", (json.dumps(record), jid))
    return inspect(store, jid)


def artifact(store, jid, kind):
    item = inspect(store, jid)
    if item['job_status'] in {'queued', 'running'} or not item.get('rows'):
        raise ValueError('Wait for the check to stop before exporting its record.')
    if kind not in {'report', 'download'}:
        raise ValueError('Choose a check report or JSON download.')
    # Serving a file does not establish that the browser displayed or saved it.
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        raw = db.execute("SELECT body FROM items WHERE kind='workstation_checks' AND id=?", (jid,)).fetchone()
        record = json.loads(raw[0])
        record.setdefault('served', {})[kind] = now()
        db.execute("UPDATE items SET body=? WHERE kind='workstation_checks' AND id=?", (json.dumps(record), jid))
    item = inspect(store, jid)
    if kind == 'download':
        return {'name': jid + '-workstation.json', 'type': 'application/json', 'text': json.dumps(item, indent=2) + '\n'}
    rows = ''.join('<tr>' + ''.join('<td>' + html.escape(str(r[k])) + '</td>' for k in ('label', 'state', 'detail', 'checked_at')) + '</tr>' for r in item['rows'])
    content = ('<!doctype html><html><head><meta charset="utf-8"><title>Workstation check</title>'
               '<style>body{font:16px system-ui;margin:24px}td,th{padding:12px;text-align:left;border-bottom:1px solid #ccc;overflow-wrap:anywhere}table{width:100%;table-layout:fixed}</style>'
               '</head><body><h1>Virologix workstation check</h1><p>' + html.escape(jid + ' · ' + item['job_status']) +
               '</p><p>' + html.escape(SCOPE) + '</p><table><tr><th>Check</th><th>State</th><th>Evidence</th><th>Time</th></tr>' + rows + '</table></body></html>')
    return {'id': jid, 'name': 'Workstation check report', 'path': 'Generated from this dated check record',
            'base64': base64.b64encode(content.encode()).decode(), 'workstation': True}
