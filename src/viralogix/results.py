"""Read-only run downloads and bounded, metadata-only report observations.

An observation associates a file with an attempt, not proof of its producer or
scientific completeness. Native reports remain in their original output folders.
"""
from contextlib import contextmanager
import base64
import hashlib
import json
import os
from pathlib import Path
import stat

from .runs import report_candidates, run_status, dry_run_current
from .store import now
from . import telemetry

REPORT_LIMIT = 50 * 1024 * 1024
LOG_LIMIT = 20 * 1024 * 1024
NOTICE = ('Report presence and a successful job do not establish complete requested scope. '
          'Report observations use file metadata, not content hashes or proof of the producing process. '
          'Original reports can change or disappear; historical copies are not retained. '
          'Downloads contain local paths and identifiers and are not redacted.')


@contextmanager
def _file(path):
    """Walk from / using directory descriptors; refuse links and special files."""
    path = Path(path).absolute()
    if '..' in path.parts:
        raise ValueError('Parent traversal is not allowed.')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        child = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        try:
            if not stat.S_ISREG(os.fstat(child).st_mode):
                raise ValueError('Only regular files can be downloaded.')
            with os.fdopen(child, 'rb', closefd=False) as handle:
                yield handle
        finally:
            os.close(child)
    finally:
        os.close(fd)


def _identity(st):
    return {k: getattr(st, 'st_' + k) for k in ('dev', 'ino', 'size', 'mtime_ns', 'ctime_ns')}


def file_info(path, limit):
    try:
        with _file(path) as handle:
            st = os.fstat(handle.fileno())
        return {'state': 'empty' if st.st_size == 0 else 'too_large' if st.st_size > limit else 'available',
                'bytes': st.st_size, 'fingerprint': _identity(st)}
    except FileNotFoundError:
        return {'state': 'missing'}
    except (OSError, ValueError):
        return {'state': 'unavailable'}


def read_file(path, limit):
    with _file(path) as handle:
        before = os.fstat(handle.fileno())
        if before.st_size > limit:
            raise ValueError('File exceeds the download limit. Open the displayed original path.')
        raw = handle.read(limit + 1)
        if len(raw) > limit or _identity(before) != _identity(os.fstat(handle.fileno())):
            raise ValueError('File changed during download. Refresh and try again.')
    return raw


def observe(ctx, run, phase):
    if ctx.job['payload'].get('action') != 'run':
        return
    try:
        record = ctx.store.get('result_observations', ctx.job['id'], {
            'id': ctx.job['id'], 'run_id': run['id'], 'schema': 1})
        record[phase] = {'at': now(), 'files': {
            rel: file_info(Path(run['output']) / rel, REPORT_LIMIT)
            for _, rel in report_candidates(ctx.store, run)}}
        ctx.store.put('result_observations', ctx.job['id'], record)
    except Exception:
        # Export bookkeeping must never change workflow success, failure or cancellation.
        try:
            ctx.write('Report observation unavailable; job execution is unchanged.')
        except Exception:
            pass


def _run(store, rid):
    if not isinstance(rid, str):
        raise ValueError('Choose an existing run.')
    run = store.get('runs', rid)
    if not run:
        raise ValueError('Choose an existing run.')
    return run


def inspect(store, rid):
    run = _run(store, rid)
    jobs = [j for j in store.jobs() if j['kind'] == 'workflow' and j['payload'].get('run_id') == rid]
    executions = [j for j in jobs if j['payload'].get('action') == 'run']
    latest = executions[0] if executions else None
    observations = {j['id']: store.get('result_observations', j['id'], {}) for j in executions}
    rows = []
    for name, rel in report_candidates(store, run):
        path = Path(run['output']) / rel
        info = file_info(path, REPORT_LIMIT)
        observed = None
        if info.get('fingerprint') and not (latest and latest['status'] in {'queued', 'running'}):
            for job in executions:
                record = observations[job['id']]
                after = record.get('after', {}).get('files', {}).get(rel, {})
                if (record.get('schema') == 1 and record.get('id') == job['id']
                        and record.get('run_id') == rid and after.get('fingerprint') == info['fingerprint']):
                    before = record.get('before', {}).get('files', {}).get(rel, {})
                    observed = {'job_id': job['id'], 'status': job['status'],
                                'at': record['after']['at'],
                                'changed': (before.get('fingerprint') != after['fingerprint'])
                                if before.get('state') in {'available', 'empty', 'too_large', 'missing'} else None}
                    break
        rows.append({'id': rid + '-' + name, 'name': name, 'relative': rel, 'path': str(path),
                     'state': info['state'], 'bytes': info.get('bytes'), 'observation': observed,
                     'producer': 'Not recorded'})
    attempts = []
    for job in jobs:
        log = file_info(store.log_path(job['id']), LOG_LIMIT)
        usage = telemetry.view(store.get('job_telemetry', job['id']), job)
        attempts.append({k: job.get(k) for k in ('id', 'status', 'created', 'started', 'finished')} | {
            'action': job['payload'].get('action'), 'held': bool(job.get('held')),
            'log': {'state': log['state'], 'bytes': log.get('bytes'), 'path': str(store.log_path(job['id']))},
            'resource_record': bool(usage), 'resource_partial': bool(usage and (usage.get('incomplete') or usage.get('state') == 'recording')),
            'report_observation': observations.get(job['id'], {}).get('after', {}).get('at')})
    return {'schema': 1, 'id': rid, 'label': run['label'], 'tool': run['tool'], 'sample': run['sample']['id'],
            'created_at': now(), 'status': run_status(run, jobs, dry_run_current(store, run)),
            'commit': run.get('commit'), 'config_sha256': hashlib.sha256(run['config'].encode()).hexdigest(),
            'variant': run.get('variant'),
            'variant_manifest_sha256': run.get('variant_manifest_sha256'),
            'latest_execution': {k: latest.get(k) for k in ('id', 'status', 'finished')} if latest else None,
            'reports': rows, 'attempts': attempts, 'notice': NOTICE,
            'shared_output_unavailable': run.get('run_type') == 'followup' and store.get('followup_output_owner', run.get('parent')) != rid}


def download(store, rid, kind, report_id=None):
    run = _run(store, rid)
    if kind == 'config':
        return {'name': rid + '.yaml', 'type': 'text/yaml', 'text': run['config']}
    if kind == 'manifest':
        return {'name': rid + '-results.json', 'type': 'application/json',
                'text': json.dumps({**inspect(store, rid), **({'result_inheritance': json.loads(Path(run['folder'], 'variant.json').read_text())} if run.get('variant') else {})}, indent=2, ensure_ascii=False) + '\n'}
    if kind == 'report':
        row = next((r for r in inspect(store, rid)['reports'] if r['id'] == report_id), None)
        if not row or row['state'] != 'available':
            raise ValueError('Report is unavailable. Refresh the results centre.')
        raw = read_file(row['path'], REPORT_LIMIT)
        return {'name': rid + '-' + Path(row['relative']).name, 'type': 'text/html',
                'base64': base64.b64encode(raw).decode('ascii')}
    raise ValueError('Choose configuration, results manifest or a report.')
