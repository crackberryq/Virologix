"""Best-effort job observation. Never controls tools, scheduling or scientific settings."""
from __future__ import annotations

import base64
import csv
from datetime import datetime, timezone
import io
import json
import math
import os
from pathlib import Path
import platform
import re
import time
import zipfile

from . import __version__
from .store import now

try:
    import psutil
except ImportError:  # A broken observer must not prevent an already installed workflow.
    psutil = None

INTERVAL = 2.0
HISTORY_LIMIT = 2048
LOG_LIMIT = 1024 * 1024
RECORD_LIMIT = 4 * 1024 * 1024
NOTES = [
    'CPU and RAM are sampled from the launched process and its discoverable descendants; brief or detached processes and between-sample peaks may be missed.',
    '100% CPU represents one fully used logical CPU thread. CPU seconds are observed user+system counter increments, not complete scheduler accounting.',
    'RAM is the sum of process resident memory (RSS). Shared pages may be counted more than once; this is not unique physical memory.',
    'Task counts come from recognized workflow log messages and describe the current plan, not remaining time or biological completeness. Checkpoints can change the total.',
    'Long histories are combined into time buckets, retaining observed CPU seconds and the peak observed RSS in each bucket. Missing readings stay explicit.',
    'GPU utilization, energy consumption and remote cluster jobs are not measured. All records remain local until downloaded or shared.',
]


class Progress:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.done = self.total = None
        self.active = {}
        self.pending = None
        self.dynamic = self.gap = False

    def feed(self, line):
        if not self.enabled:
            return
        line = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', line).strip()
        if 'DAG of jobs will be updated after completion' in line:
            self.dynamic = True
        counts = re.fullmatch(r'(\d+) of (\d+) steps \([\d.]+%\) done', line)
        if counts:
            done, total = map(int, counts.groups())
            if 0 <= done <= total <= 100000000 and total:
                self.dynamic |= self.total is not None and total != self.total
                self.done, self.total = done, total
            self.pending = None
            return
        header = re.fullmatch(r'(?:local)?(?:rule|checkpoint) ([A-Za-z_][A-Za-z0-9_.-]{0,127}):', line)
        if header:
            self.pending = header[1]
            return
        job = re.fullmatch(r'jobid: (\d+)', line)
        if job and self.pending:
            if len(self.active) < 256 or job[1] in self.active:
                self.active[job[1]] = self.pending
            else:
                self.gap = True
            self.pending = None
        finished = re.match(r'Finished (?:job (\d+)\.|jobid: (\d+)(?:\s|$))', line)
        if finished:
            self.active.pop(finished[1] or finished[2], None)
        if not line:
            self.pending = None

    def value(self):
        return {'completed': self.done, 'total': self.total,
                'percent': round(100 * self.done / self.total, 1) if self.total else None,
                'active_rules': list(dict.fromkeys(self.active.values()))[:12],
                'active_count': len(self.active), 'dynamic_plan': self.dynamic, 'log_gap': self.gap,
                'source': 'workflow log' if self.enabled else 'not applicable'}


class Sampler:
    def __init__(self, pid):
        self.root = psutil.Process(pid) if psutil else None
        self.counters = {}
        self.partial = not bool(psutil)

    def sample(self):
        if self.root is None:
            return None
        try:
            if not self.root.is_running():
                return None
            processes = [self.root, *self.root.children(recursive=True)]
        except (psutil.Error, OSError):
            self.partial = True
            return None
        cpu, rss, seen = 0.0, 0, 0
        for process in processes[:4096]:
            try:
                with process.oneshot():
                    identity = (process.pid, process.create_time())
                    times = process.cpu_times()
                    counter = times.user + times.system  # Exclude reaped-child counters to avoid double counting.
                    memory = process.memory_info().rss
                previous = self.counters.get(identity, 0.0)
                if len(self.counters) >= 32768 and identity not in self.counters:
                    # Keep memory bounded without inventing CPU usage for untracked processes.
                    self.partial = True
                    previous = counter
                else:
                    self.counters[identity] = counter
                cpu += max(0.0, counter - previous)
                rss += memory
                seen += 1
            except (psutil.Error, OSError):
                self.partial = True
        self.partial |= len(processes) > 4096
        return {'cpu_s': cpu, 'rss_mb': rss / 1024 ** 2, 'processes': seen} if seen else None


def _peak(*values):
    present = [v for v in values if v is not None]
    return max(present) if present else None


def compact(points):
    """Join adjacent intervals; preserve integrals, peaks and missing-sample counts."""
    result = []
    for index in range(0, len(points), 2):
        a = points[index]
        if index + 1 == len(points):
            result.append(a)
            continue
        b = points[index + 1]
        result.append({'start_s': a['start_s'], 'end_s': b['end_s'],
                       'cpu_s': a['cpu_s'] + b['cpu_s'],
                       'rss_peak_mb': _peak(a['rss_peak_mb'], b['rss_peak_mb']),
                       'processes_peak': _peak(a['processes_peak'], b['processes_peak']),
                       'observed': a['observed'] + b['observed'], 'unavailable': a['unavailable'] + b['unavailable']})
    return result


class Recorder:
    def __init__(self, store, job):
        self.store, self.job = store, job
        self.started = self.last = time.monotonic()
        self.last_save = self.started
        self.proc = None
        self.sampler = None
        self.position, self.pending = 0, b''
        self.discard_line = False
        self.history = []
        self.progress = Progress(job['kind'] == 'workflow' and job['payload'].get('action') == 'run')
        run = store.get('runs', job['payload'].get('run_id'), {})
        self.record = {'schema': 1, 'id': job['id'], 'run_id': run.get('id'),
                       'kind': job['kind'], 'action': job['payload'].get('action'),
                       'started_at': now(), 'updated_at': now(), 'state': 'recording',
                       'app_version': __version__, 'python': platform.python_version(),
                       'system': platform.system(), 'architecture': platform.machine(),
                       'pipeline': run.get('tool'), 'commit': run.get('commit'),
                       'config_sha256': run.get('config_sha256'), 'workflow_sha256': run.get('workflow_sha256'),
                       'budget': {k: run.get(k) for k in ('cores', 'memory_mb')},
                       'elapsed_s': 0.0, 'command_count': 0, 'command_name': None,
                       'observed_cpu_s': 0.0, 'peak_rss_mb': None, 'samples': 0,
                       'unavailable_samples': 0, 'partial_process_tree': False,
                       'latest': None, 'history_compacted': False, 'observer_errors': False, 'notes': NOTES}

    def begin_command(self, proc, name):
        self.proc = proc
        self.record.update(command_count=self.record['command_count'] + 1, command_name=Path(str(name)).name)
        self.last = time.monotonic()
        try:
            self.sampler = Sampler(proc.pid)
        except (OSError, psutil.Error if psutil else OSError):
            self.sampler = None
            self.record['partial_process_tree'] = True
        self.tick(force=True)

    def read_log(self):
        path = self.store.log_path(self.job['id'])
        with path.open('rb') as handle:
            size = os.fstat(handle.fileno()).st_size
            if size < self.position or size - self.position > LOG_LIMIT:
                self.position = max(0, size - LOG_LIMIT)
                self.pending = b''
                self.discard_line = False
                self.progress.active.clear()
                self.progress.pending = None
                self.progress.gap = True
                if self.position:
                    handle.seek(self.position)
                    handle.readline(LOG_LIMIT)  # Do not interpret a clipped line.
                    self.position = handle.tell()
            handle.seek(self.position)
            block = handle.read(LOG_LIMIT)
            self.position = handle.tell()
        lines = (self.pending + block).replace(b'\r', b'\n').split(b'\n')
        tail = lines.pop()
        if self.discard_line and lines:
            lines.pop(0)
            self.discard_line = False
        self.discard_line |= len(tail) > 8192
        self.pending = b'' if self.discard_line else tail
        for line in lines:
            if len(line) <= 8192:
                self.progress.feed(line.decode('utf-8', errors='replace'))

    def tick(self, force=False):
        current = time.monotonic()
        if not force and current - self.last < INTERVAL:
            return
        elapsed = max(0.0, current - self.started)
        interval = max(0.0, current - self.last)
        sample = self.sampler.sample() if self.sampler else None
        if self.proc is not None:
            point = {'start_s': max(0.0, self.last - self.started), 'end_s': elapsed,
                     'cpu_s': sample['cpu_s'] if sample else 0.0,
                     'rss_peak_mb': sample['rss_mb'] if sample else None,
                     'processes_peak': sample['processes'] if sample else None,
                     'observed': int(sample is not None), 'unavailable': int(sample is None)}
            self.history.append(point)
            if len(self.history) > HISTORY_LIMIT:
                self.history = compact(self.history)
                self.record['history_compacted'] = True
            self.record['samples'] += point['observed']
            self.record['unavailable_samples'] += point['unavailable']
            self.record['observed_cpu_s'] += point['cpu_s']
            self.record['peak_rss_mb'] = _peak(self.record['peak_rss_mb'], point['rss_peak_mb'])
            self.record['latest'] = {'cpu_percent': 100 * sample['cpu_s'] / interval if sample and interval >= .1 else None,
                                     'rss_mb': sample['rss_mb'] if sample else None,
                                     'processes': sample['processes'] if sample else None}
        self.record['partial_process_tree'] |= bool(self.sampler and self.sampler.partial)
        self.last = current
        self.read_log()
        self.record.update(elapsed_s=elapsed, updated_at=now(), progress=self.progress.value())
        self.store.put('job_telemetry', self.job['id'], self.record)
        if force or current - self.last_save >= 30:
            self.persist_history()
            self.last_save = current

    def persist_history(self):
        # A separate bounded snapshot avoids sending the series with every UI refresh.
        self.store.put('job_usage_history', self.job['id'], {'schema': 1, 'id': self.job['id'],
                       'updated_at': self.record['updated_at'], 'points': self.history})

    def end_command(self):
        self.tick(force=True)
        self.proc = self.sampler = None
        self.record.update(command_name=None, latest=None)
        self.store.put('job_telemetry', self.job['id'], self.record)

    def finish(self, status):
        self.tick(force=True)
        if self.pending:
            self.progress.feed(self.pending.decode('utf-8', errors='replace'))
        self.record.update(state=status, finished_at=now(), latest=None, command_name=None, progress=self.progress.value())
        self.store.put('job_telemetry', self.job['id'], self.record)
        self.persist_history()


def view(record, job):
    if not isinstance(record, dict) or record.get('schema') != 1 or record.get('id') != job['id']:
        return None
    result = dict(record, job_status=job['status'])
    try:
        updated = datetime.fromisoformat(record['updated_at'])
        age = (datetime.now(timezone.utc) - updated).total_seconds()
    except (ValueError, TypeError, KeyError):
        age = float('inf')
    result['live'] = job['status'] == 'running' and record.get('state') == 'recording' and 0 <= age <= 15
    result['stale'] = job['status'] == 'running' and not result['live']
    result['incomplete'] = record.get('state') == 'recording' and job['status'] not in {'queued', 'running'}
    if not result['live']:
        result['latest'] = None
    return result


def inspect(store, jid):
    if not isinstance(jid, str):
        raise ValueError('Choose an existing job.')
    job = store.job(jid)
    if not job:
        raise ValueError('Choose an existing job.')
    summary = view(store.get('job_telemetry', jid), job)
    if not summary:
        raise ValueError('No resource record was collected for this job. Records start with new jobs in v0.1.0a27.')
    history = store.get('job_usage_history', jid, {})
    valid = isinstance(history, dict) and history.get('schema') == 1 and history.get('id') == jid
    points = history.get('points', []) if valid else []
    if not isinstance(points, list) or len(points) > HISTORY_LIMIT:
        raise ValueError('This resource history is invalid or exceeds the display limit.')
    cleaned = []
    previous = 0
    for point in points:
        if not isinstance(point, dict):
            raise ValueError('This resource history contains an invalid interval.')
        keys = ('start_s', 'end_s', 'cpu_s', 'rss_peak_mb', 'processes_peak', 'observed', 'unavailable')
        row = {key: point.get(key) for key in keys}
        for key, value in row.items():
            if value is None and key in {'rss_peak_mb', 'processes_peak'}:
                continue
            if type(value) not in {int, float} or not math.isfinite(value) or value < 0:
                raise ValueError('This resource history contains an invalid measurement.')
        if row['end_s'] < row['start_s'] or row['start_s'] < previous:
            raise ValueError('This resource history contains overlapping or reversed intervals.')
        previous = row['end_s']
        cleaned.append(row)
    return {'id': jid, 'summary': summary, 'points': cleaned,
            'history_updated_at': history.get('updated_at') if valid else None}


def download(store, jid, format):
    if not isinstance(format, str) or format not in {'json', 'csv', 'zip'}:
        raise ValueError('Choose JSON, CSV or ZIP.')
    data = inspect(store, jid)
    text = json.dumps(data, indent=2, allow_nan=False) + '\n'
    if len(text.encode()) > RECORD_LIMIT:
        raise ValueError('This resource record exceeds the download limit.')
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(['interval_start_s', 'interval_end_s', 'observed_cpu_s', 'cpu_percent_mean',
                     'peak_process_rss_sum_mb', 'peak_process_count', 'observed_samples', 'unavailable_samples'])
    for point in data['points']:
        duration = point['end_s'] - point['start_s']
        percent = 100 * point['cpu_s'] / duration if duration > .1 and point['observed'] else ''
        writer.writerow([point['start_s'], point['end_s'], point['cpu_s'], percent,
                         point['rss_peak_mb'], point['processes_peak'], point['observed'], point['unavailable']])
    csv_text = stream.getvalue()
    name = jid + '-resource-use.' + format
    if format != 'zip':
        return {'name': name, 'text': text if format == 'json' else csv_text,
                'type': 'application/json' if format == 'json' else 'text/csv'}
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('resource-use.json', text)
        archive.writestr('resource-use.csv', csv_text)
        archive.writestr('README.txt', 'Virologix resource-use record\nJob: ' + jid + '\nStatus: ' + data['summary']['job_status'] +
                         '\n\n' + '\n\n'.join(NOTES) + '\n\nOne record describes one job attempt. A resumed run creates another job record.\n')
    return {'name': name, 'base64': base64.b64encode(output.getvalue()).decode(), 'type': 'application/zip'}
