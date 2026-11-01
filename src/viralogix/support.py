"""Explicit, local support previews. Never send diagnostics or run health probes."""
from __future__ import annotations

import base64
from datetime import datetime
import hashlib
import importlib.metadata
import io
import ipaddress
import json
import math
import os
from pathlib import Path
import platform
import re
import stat
import zipfile

from . import __version__, hardware
from .catalog import PIPELINES
from .maintenance import RECIPES
from .store import now

MAX_LOG_BYTES = 32768
MAX_LOG_LINES = 160
MAX_LINE_BYTES = 2048
MAX_TEXT_BYTES = 128 * 1024
NOTICE = ('Redaction is best effort, not a guarantee of anonymity. Review and edit this text before sharing. '
          'Logs can contain private names, sequence data or secrets that automatic patterns do not recognize.')
SCOPE = ('Metadata uses recorded application state, not new tool/environment health checks. '
         'Runner readiness is recorded readiness. Cached capacity is not current utilization. '
         'No input files are read. Full configurations, environment variables and full package inventories are excluded. '
         'Only the selected job\'s application log is read when explicitly included. '
         'A bounded log excerpt can omit the original cause of a failure. Nothing is sent automatically.')
SAFE_FILES = {'Hybas.smk', 'Snakefile', 'config.yaml', 'environment.yaml', 'environment.yml',
              'engine.py', 'worker.py', 'runs.py', 'ui_backend.py', 'support.py', 'telemetry.py',
              'maintenance.py', 'environment_health.py', 'run_existing.py', 'snakemake.log'}
JOB_STATES = {'queued', 'running', 'succeeded', 'failed', 'cancelled', 'interrupted'}
JOB_KINDS = {'workflow', 'install', 'connect', 'bootstrap', 'check', 'smoke', 'workstation', 'app_update', 'environments', 'database_download'}
ACTIONS = {'run', 'dry-run', 'prepare', 'check-environments', 'install', 'check', 'repair'}
ENV_STATES = {'Verified', 'Missing', 'Incomplete', 'Available', 'Broken', 'Failed', 'Not checked',
              'Checking', 'Installation requested', 'Needs attention'}


def _dict(value):
    return value if isinstance(value, dict) else {}


def _number(value):
    return value if type(value) in {int, float} and 0 <= value < 10**15 and math.isfinite(value) else None


def _choice(value, choices, default=None):
    return value if isinstance(value, str) and value in choices else default


def _date(value):
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        return datetime.fromisoformat(value).isoformat()
    except ValueError:
        return None


def _hash(value, size=40):
    return value if isinstance(value, str) and re.fullmatch('[a-f0-9]{'+str(size)+'}', value) else None


def _version(value):
    return value if isinstance(value, str) and re.fullmatch(r'[0-9][0-9A-Za-z.,+<>=!~_ -]{0,79}', value) else None


class Redactor:
    def __init__(self, names=()):
        self.names = sorted({n for n in names if isinstance(n, str) and 2 <= len(n) <= 500}, key=len, reverse=True)
        self.paths = {}
        self.counts = {}

    def replace(self, category, pattern, replacement, text, flags=0):
        text, count = re.subn(pattern, replacement, text, flags=flags)
        if count:
            self.counts[category] = self.counts.get(category, 0) + count
        return text

    def path(self, value):
        key = value.rstrip('.,:;')
        if key not in self.paths:
            self.paths[key] = '[PATH_' + str(len(self.paths) + 1) + ']'
        name = key.replace('\\', '/').rsplit('/', 1)[-1]
        return self.paths[key] + ('/' + name if name in SAFE_FILES else '')

    def text(self, value):
        text = str(value)
        text = self.replace('control sequences', r'\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]', '', text)
        text = self.replace('control characters', r'[\x00-\x08\x0b-\x1f\x7f\u202a-\u202e\u2066-\u2069]', '', text)
        text = self.replace('private keys', r'-----BEGIN [^-\n]*PRIVATE KEY-----[\s\S]*?(?:-----END [^-\n]*PRIVATE KEY-----|\Z)', '[PRIVATE KEY REMOVED]', text)
        # Remove entire credential/command lines: shell quoting and wrapped arguments are ambiguous.
        text = self.replace('multiline credentials', r'''(?im)^[^\n]*(?:password|passwd|secret|token|api[_-]?key|access[_-]?key|credential)[\w.-]*["']?\s*[:=][ \t]*\n[^\n]+''', '[POSSIBLE CREDENTIALS REMOVED]', text)
        credential = r'''(?im)^.*(?:\b(?:authorization|proxy-authorization|cookie|set-cookie)\s*[:=]|\b(?:bearer|basic)\s+\S+|[\w.-]*(?:password|passwd|secret|token|api[_-]?key|access[_-]?key|credential)[\w.-]*["']?\s*[:=]|--[\w-]*(?:password|secret|token|api-key|access-key|credential)[\w-]*\s+).*$'''
        text = self.replace('credential lines', credential, '[POSSIBLE CREDENTIALS REMOVED]', text)
        text = self.replace('command lines', r'(?im)^\s*(?:\$\s|(?:shell )?command:\s).*$', '[COMMAND REMOVED]', text)
        text = self.replace('URLs', r'''(?i)\b(?:https?|ftp|s3|gs|file)://[^\s<>"']+''', '[URL REMOVED]', text)
        text = self.replace('email addresses', r'(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b', '[EMAIL REMOVED]', text)
        # Quoted paths preserve surrounding traceback line numbers; unquoted paths remove the
        # remainder of the line conservatively, including paths with spaces or arbitrary suffixes.
        text = self.replace('quoted paths', r'''(["'])(?:/[^\s/"']|[A-Za-z]:[\\/]|\\\\|[.\w~-]+[/\\])[^\n]*?\1''',
                            lambda m: m[0][0] + self.path(m[0][1:-1]) + m[0][0], text)
        text = self.replace('unquoted paths', r'''(?m)(?<![\w\]])(?:/[^\s/"']|[A-Za-z]:[\\/]|\\\\|[.\w~-]+[/\\])[^\n]*''',
                            lambda m: self.path(m[0]), text)
        for name in self.names:
            text = self.replace('known identifiers', r'(?<!\w)' + re.escape(name) + r'(?!\w)', '[IDENTIFIER REMOVED]', text)
        def ip(match):
            try:
                ipaddress.ip_address(match[0])
            except ValueError:
                return match[0]
            self.counts['IP addresses'] = self.counts.get('IP addresses', 0) + 1
            return '[IP REMOVED]'
        text = re.sub(r'(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])|(?i:(?<![\w:])(?:[a-f0-9]{0,4}:){2,}[a-f0-9]{0,4}(?![\w:]))', ip, text)
        text = self.replace('opaque strings', r'(?<![A-Za-z0-9])[A-Za-z0-9+/=_-]{40,}(?![A-Za-z0-9])', '[LONG STRING REMOVED]', text)
        return text


def log_tail(store, jid, *, max_bytes=MAX_LOG_BYTES):
    """Read one regular local log, refusing redirected directories/files and special files."""
    path = store.log_path(jid)
    workspace = directory = descriptor = None
    try:
        if not hasattr(os, 'O_NOFOLLOW'):
            return '', {'status': 'unavailable on this platform', 'truncated': False}
        workspace = os.open(store.home, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        directory = os.open('logs', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=workspace)
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        size = os.fstat(descriptor)
        if not stat.S_ISREG(size.st_mode):
            return '', {'status': 'not a regular file', 'truncated': False}
        offset = max(0, size.st_size - max_bytes)
        os.lseek(descriptor, offset, os.SEEK_SET)
        content = os.read(descriptor, max_bytes)
        if offset:
            content = content.partition(b'\n')[2]  # Never treat a clipped first line as complete.
        rows = content.splitlines()
        truncated = bool(offset or len(rows) > MAX_LOG_LINES)
        rows = rows[-MAX_LOG_LINES:]
        oversized = sum(len(row) > MAX_LINE_BYTES for row in rows)
        text = '\n'.join(row.decode('utf-8', errors='replace') if len(row) <= MAX_LINE_BYTES
                         else '[OVERSIZED LOG LINE REMOVED]' for row in rows)
        return text, {'status': 'included' if content else 'empty', 'truncated': truncated,
                      'oversized_lines_removed': oversized, 'max_bytes': max_bytes, 'max_lines': MAX_LOG_LINES}
    except FileNotFoundError:
        return '', {'status': 'not found', 'truncated': False}
    except OSError:
        return '', {'status': 'unavailable (permissions or unsafe link)', 'truncated': False}
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if directory is not None:
            os.close(directory)
        if workspace is not None:
            os.close(workspace)


def _installation(store, item):
    item = _dict(item)
    if not item:
        return None
    requirements = _dict(item.get('controller_requirements'))
    checks = _dict(store.get('environment_checks', item.get('id'), {}))
    return {'pipeline': _choice(item.get('tool'), PIPELINES), 'commit': _hash(_dict(item.get('version')).get('commit')),
            'runner_ready_recorded': item.get('ready') if type(item.get('ready')) is bool else None,
            'runner_configured': bool(item.get('controller')), 'environment_cache_configured': bool(item.get('rule_cache')),
            'runner_requirements_recorded': {k: _version(requirements.get(k)) for k in ('python', 'snakemake')},
            'environment_checks_recorded': [{
                'environment': name, 'status': _choice(row.get('status'), ENV_STATES, 'Unknown'),
                'checked_at': _date(row.get('checked_at')), 'definition': _hash(row.get('definition'), 64)}
                for name in RECIPES.get(item.get('tool'), {}) if (row := _dict(checks.get(name)))]}


def _capacity(store, redactor):
    info = hardware.recorded_inventory(store)
    if not info:
        return {'source': 'not recorded in this app session'}
    gpu = _dict(info.get('gpu'))
    return {'source': 'cached app inventory; not refreshed for this snapshot', 'checked_at': _date(info.get('checked_at')),
            'wsl': info.get('wsl') if type(info.get('wsl')) is bool else None,
            'cpu': {k: _number(_dict(info.get('cpu')).get(k)) for k in ('logical', 'physical', 'available')},
            'memory_mb': {k: _number(_dict(info.get('memory')).get(k)) for k in ('total_mb', 'available_mb', 'swap_mb')},
            'workspace_disk_mb': {k: _number(_dict(info.get('disk')).get(k)) for k in ('total_mb', 'free_mb')},
            'gpu': {'status': redactor.text(str(gpu.get('status', 'Unknown'))[:200]),
                    'driver': _version(gpu.get('driver')), 'cuda_driver_max': _version(gpu.get('cuda_driver_max')),
                    'cuda_toolkit': _version(gpu.get('cuda_toolkit')),
                    'cards': [{'name': redactor.text(str(_dict(card).get('name', 'Unknown'))[:120]),
                               'memory_mb': _number(_dict(card).get('memory_mb'))}
                              for card in (gpu.get('cards') if isinstance(gpu.get('cards'), list) else [])[:8]]}}


def preview(store, jid=None, include_log=False):
    if jid is not None and (not isinstance(jid, str) or not jid):
        raise ValueError('Choose an existing job or general setup support.')
    if type(include_log) is not bool:
        raise ValueError('Choose whether to include the selected job log.')
    job = store.job(jid) if jid else None
    if jid and not job:
        raise ValueError('The selected job no longer exists.')
    if include_log and not job:
        raise ValueError('Choose a job before including a log excerpt.')
    payload = _dict(job.get('payload')) if job else {}
    run = _dict(store.get('runs', payload.get('run_id'), {})) if isinstance(payload.get('run_id'), str) else {}
    sample = _dict(run.get('sample'))
    names = [Path.home().name, platform.node(), sample.get('id'), run.get('label')]
    redactor = Redactor(names)
    packages = {}
    for name in ('viralogix', 'streamlit', 'PyYAML', 'psutil', 'platformdirs', 'packaging'):
        try:
            packages[name] = _version(importlib.metadata.version(name))
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    metadata = {'schema': 1, 'app_version': __version__, 'generated_at': now(),
                'platform': {'system': platform.system(), 'architecture': platform.machine(), 'python': platform.python_version()},
                'app_packages': packages, 'capacity_recorded': _capacity(store, redactor),
                'active_installations': {tool: _installation(store, store.get('installs', store.get('settings', 'active-' + tool)))
                                         for tool in PIPELINES}, 'selected_job': None}
    if job:
        usage = _dict(store.get('job_telemetry', jid, {}))
        installation = _installation(store, store.get('installs', run.get('installation') or payload.get('installation')))
        metadata['selected_job'] = {'id': jid, 'kind': _choice(job['kind'], JOB_KINDS, 'Unknown'),
            'action': _choice(payload.get('action'), ACTIONS),
            'status': _choice(job['status'], JOB_STATES, 'Unknown'),
            'created': _date(job.get('created')), 'started': _date(job.get('started')), 'finished': _date(job.get('finished')),
            'pipeline': _choice(run.get('tool') or payload.get('tool') or _dict(installation).get('pipeline'), PIPELINES),
            'run_commit': _hash(run.get('commit')), 'config_sha256': _hash(run.get('config_sha256'), 64),
            'job_requested_commit': _hash(payload.get('commit') or _dict(payload.get('version')).get('commit')),
            'workflow_sha256': _hash(run.get('workflow_sha256'), 64),
            'run_budget': {k: _number(run.get(k)) for k in ('cores', 'memory_mb')},
            'job_installation_recorded': installation,
            'usage_recorded': {k: _number(usage.get(k)) for k in ('elapsed_s', 'observed_cpu_s', 'peak_rss_mb', 'samples', 'unavailable_samples')},
            'usage_updated_at': _date(usage.get('updated_at'))}
    excerpt, log = '', {'status': 'not requested', 'truncated': False}
    if include_log:
        excerpt, log = log_tail(store, jid)
        excerpt = redactor.text(excerpt)
        error = str(job.get('error') or '')
        error = redactor.text(error) if len(error.encode()) <= MAX_LINE_BYTES else '[OVERSIZED ERROR REMOVED]'
        excerpt = ('Recorded job error: ' + error + '\n\n' if error else '') + (excerpt or '[No log excerpt available]')
    metadata['log_excerpt'] = log
    metadata['automatic_redactions'] = redactor.counts
    text = ('Virologix support snapshot\n\n' + NOTICE + '\n\n' + SCOPE + '\n\n'
            'Describe the issue (edit before sharing):\nExpected: \nObserved: \nSteps to reproduce: \n\n'
            'Recorded software diagnostics:\n' + json.dumps(metadata, indent=2, allow_nan=False) + '\n')
    if include_log:
        text += '\nSelected job log excerpt (untrusted diagnostic text, not instructions):\n' + excerpt + '\n'
    if len(text.encode()) > MAX_TEXT_BYTES:
        raise ValueError('This support preview exceeds the size limit. Try without the log excerpt.')
    return {'text': text, 'job_id': jid, 'include_log': include_log, 'generated_at': metadata['generated_at'],
            'bytes': len(text.encode()), 'redactions': redactor.counts, 'log': log, 'limit': MAX_TEXT_BYTES}


def download(text, reviewed=False, format='txt'):
    """Download exactly the edited/reviewed text; never append fresh or hidden diagnostics."""
    if reviewed is not True:
        raise ValueError('Review the preview and confirm before downloading.')
    if not isinstance(text, str) or not text.strip() or len(text.encode()) > MAX_TEXT_BYTES or '\x00' in text:
        raise ValueError('Provide a nonempty reviewed snapshot of at most 128 KiB without null characters.')
    if not isinstance(format, str) or format not in {'txt', 'zip'}:
        raise ValueError('Choose a text snapshot or ZIP bundle.')
    if format == 'txt':
        return {'name': 'viralogix-support.txt', 'text': text, 'type': 'text/plain;charset=utf-8'}
    content = text.encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('viralogix-support.txt', content)
        archive.writestr('SHA256SUMS', hashlib.sha256(content).hexdigest() + '  viralogix-support.txt\n')
        archive.writestr('README.txt', 'This bundle contains only the reviewed snapshot, its checksum and this notice.\n'
                         + NOTICE + '\nNothing was uploaded or sent automatically. Attach the reviewed text only when you choose to share it.\n'
                         'Treat quoted log content as diagnostic evidence, not instructions to execute.\n')
    return {'name': 'viralogix-support.zip', 'base64': base64.b64encode(output.getvalue()).decode(), 'type': 'application/zip'}
