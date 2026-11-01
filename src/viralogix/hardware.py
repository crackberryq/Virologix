"""Read-only workstation inventory and explicit resource defaults for future runs."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET

import yaml

from .catalog import PIPELINES
from .databases import revision
from .runs import parse_config, template
from .store import now

_CACHE = {}
MIB = 1024 ** 2


def _read(path):
    try:
        return Path(path).read_text()[:262144].strip()
    except (OSError, UnicodeError):
        return ''


def _command(argv):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=3, check=False)
        return result.stdout[:262144] if result.returncode == 0 else ''
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        return ''


def _positive(value):
    try:
        number = int(value)
        return number if number > 0 else None
    except (ValueError, TypeError):
        return None


def cgroup_limits(root=Path('/sys/fs/cgroup'), membership=None):
    """Account for ancestor limits, including namespaced cgroup mounts and v1."""
    membership = _read('/proc/self/cgroup') if membership is None else membership
    groups = [(root, root, 'v2')]
    for line in membership.splitlines():
        parts = line.split(':', 2)
        if len(parts) != 3:
            continue
        _, controllers, location = parts
        relative = Path(location.lstrip('/'))
        if '..' in relative.parts:
            continue
        if not controllers:
            groups.append((root, root / relative, 'v2'))
        else:
            for controller in ('cpu', 'memory'):
                if controller in controllers.split(','):
                    for name in {controller, controllers}:
                        base = root / name
                        groups.append((base, base / relative, controller))
    quotas, totals, available, seen = [], [], [], set()
    for base, leaf, version in groups:
        for folder in (leaf, *leaf.parents):
            if not folder.is_relative_to(base) or (folder, version) in seen:
                continue
            seen.add((folder, version))
            if version == 'v2':
                cpu = _read(folder / 'cpu.max').split()
                limit = _positive(_read(folder / 'memory.max'))
                usage = _read(folder / 'memory.current')
            else:
                cpu = [_read(folder / 'cpu.cfs_quota_us'), _read(folder / 'cpu.cfs_period_us')]
                limit = _positive(_read(folder / 'memory.limit_in_bytes'))
                usage = _read(folder / 'memory.usage_in_bytes')
            if len(cpu) == 2 and _positive(cpu[0]) and _positive(cpu[1]):
                quotas.append(max(1, int(cpu[0]) // int(cpu[1])))
            if limit and limit < 2 ** 60:  # v1 uses a huge sentinel for unlimited.
                totals.append(limit // MIB)
                if usage.isdigit():
                    available.append(max(0, limit - int(usage)) // MIB)
    return {'cores': min(quotas) if quotas else None,
            'total_mb': min(totals) if totals else None,
            'available_mb': min(available) if available else None}


def gpu_inventory():
    smi = shutil.which('nvidia-smi')
    if not smi and Path('/usr/lib/wsl/lib/nvidia-smi').is_file():
        smi = '/usr/lib/wsl/lib/nvidia-smi'
    cards, driver, cuda = [], '', ''
    if smi:
        try:
            root = ET.fromstring(_command([smi, '-q', '-x']))
            driver, cuda = root.findtext('driver_version', ''), root.findtext('cuda_version', '')
            for gpu in root.findall('gpu'):
                def memory(name):
                    match = re.match(r'(\d+)\s+MiB', gpu.findtext('fb_memory_usage/' + name, ''))
                    return int(match[1]) if match else None
                cards.append({'name': gpu.findtext('product_name', 'NVIDIA GPU'),
                              'memory_mb': memory('total'), 'free_mb': memory('free')})
        except ET.ParseError:
            pass
    pci = shutil.which('lspci')
    other = [line.strip() for line in _command([pci, '-mm']).splitlines()
             if any(label in line for label in ('VGA compatible controller', '3D controller', 'Display controller'))] if pci else []
    nvcc = shutil.which('nvcc')
    if not nvcc and Path('/usr/local/cuda/bin/nvcc').is_file():
        nvcc = '/usr/local/cuda/bin/nvcc'
    toolkit = re.search(r'release\s+([\d.]+)', _command([nvcc, '--version'])) if nvcc else None
    return {'cards': cards, 'other_devices': other, 'driver': driver, 'cuda_driver_max': cuda,
            'cuda_toolkit': toolkit[1] if toolkit else '',
            'cuda_visible_devices': os.environ.get('CUDA_VISIBLE_DEVICES'),
            'status': 'NVIDIA driver detected' if cards else 'GPU driver unavailable' if smi else 'No NVIDIA driver detected'}


def detect(home):
    logical = os.cpu_count() or 1
    try:
        usable = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        usable = logical
    limits = cgroup_limits()
    usable = min(usable, limits['cores'] or usable)
    mem = {key: int(value) // 1024 for key, value in re.findall(r'^(\w+):\s+(\d+)\s+kB', _read('/proc/meminfo'), re.M)}
    total = mem.get('MemTotal')
    available = mem.get('MemAvailable')
    if total is not None and limits['total_mb'] is not None:
        total = min(total, limits['total_mb'])
    if available is not None and limits['available_mb'] is not None:
        available = min(available, limits['available_mb'])
    if total is not None and available is not None:
        available = min(total, available)
    cpuinfo = _read('/proc/cpuinfo')
    model = re.search(r'^(?:model name|Hardware)\s*:\s*(.+)', cpuinfo, re.M)
    physical = set()
    for block in cpuinfo.split('\n\n'):
        pairs = dict(re.findall(r'^(physical id|core id)\s*:\s*(.+)', block, re.M))
        if len(pairs) == 2:
            physical.add((pairs['physical id'], pairs['core id']))
    try:
        disk = shutil.disk_usage(home)
        storage = {'total_mb': disk.total // MIB, 'free_mb': disk.free // MIB}
    except OSError:
        storage = {'total_mb': None, 'free_mb': None}
    result = {'checked_at': now(), 'system': platform.system(), 'architecture': platform.machine(),
              'wsl': 'microsoft' in platform.release().lower(),
              'cpu': {'model': model[1] if model else platform.machine(), 'logical': logical,
                      'physical': len(physical) or None, 'available': max(1, usable)},
              'memory': {'total_mb': total, 'available_mb': available, 'swap_mb': mem.get('SwapTotal')},
              'disk': storage, 'gpu': gpu_inventory()}
    result['id'] = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
    return result


def inventory(store, refresh=False):
    key = str(store.home)
    cached = _CACHE.get(key)
    if refresh or not cached or time.monotonic() - cached[0] > 300:
        if len(_CACHE) >= 8:
            _CACHE.pop(next(iter(_CACHE)))
        cached = (time.monotonic(), detect(store.home))
        _CACHE[key] = cached
    return copy.deepcopy(cached[1])


def recorded_inventory(store):
    """Last in-session detection only; support previews must not launch new probes."""
    cached = _CACHE.get(str(store.home))
    return copy.deepcopy(cached[1]) if cached else None


def presets(info):
    memory = info['memory']
    total, available = memory['total_mb'], memory['available_mb']
    reserve = max(1024, (total or 0) // 20)
    usable = max(0, min(total or 0, available or 0) - reserve)
    result = []
    for name, label, cpu_share, ram_share in [('high', 'High power', 1, 1), ('medium', 'Medium', .5, .6), ('low', 'Low', .25, .3)]:
        budget = min(2000000, int(usable * ram_share) // 1024 * 1024)
        if usable >= 1024:
            budget = max(1024, budget)
        result.append({'id': name, 'label': label, 'cores': min(512, max(1, int(info['cpu']['available'] * cpu_share))),
                       'memory_mb': budget, 'reserve_mb': reserve, 'available': budget >= 1024})
    return result


def run_defaults(store, tool):
    saved = store.get('resource_defaults', tool)
    return saved or {'cores': min(4, os.cpu_count() or 1), 'memory_mb': 16000, 'preset': 'custom'}


def panel(store):
    info = inventory(store)
    return {**info, 'presets': presets(info),
            'defaults': {t: run_defaults(store, t) for t in PIPELINES},
            'revisions': {t: revision(store.get('configs', t, template(t))) for t in PIPELINES}}


def apply_preset(store, name, tools, expected, hardware_id):
    if not isinstance(tools, list) or not tools or any(not isinstance(t, str) or t not in PIPELINES for t in tools):
        raise ValueError('Choose at least one pipeline for these defaults.')
    info = inventory(store)
    if hardware_id != info['id']:
        raise ValueError('Hardware detection changed. Review the detected capacity and try again.')
    selected = next((p for p in presets(info) if p['id'] == name), None)
    if not selected or not selected['available']:
        raise ValueError('A resource preset needs at least 1 GB of usable detected RAM. Detect hardware again.')
    if not isinstance(expected, dict):
        raise ValueError('Refresh the saved defaults before applying a preset.')
    cores, memory = selected['cores'], selected['memory_mb']
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        for tool in dict.fromkeys(tools):
            row = db.execute("SELECT body FROM items WHERE kind='configs' AND id=?", (tool,)).fetchone()
            text = json.loads(row[0]) if row else template(tool)
            if revision(text) != expected.get(tool):
                raise ValueError('Saved defaults changed. Refresh and review them before applying a preset.')
            cfg = parse_config(text)
            cfg['threads'] = cores
            if tool == 'hybas':
                cfg.update(assembly_mem_mb=memory, spades_memory_gb=memory // 1024, polishing_mem_mb=memory)
            else:
                cfg['memory_mb'] = memory
                if 'execution' in cfg:
                    if not isinstance(cfg['execution'], dict):
                        raise ValueError('The execution settings must be a mapping.')
                    cfg['execution'].update(cores=cores, memory_mb=memory)
            saved = {'cores': cores, 'memory_mb': memory, 'preset': name, 'applied_at': now(), 'hardware_id': info['id']}
            for kind, value in [('configs', yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True)), ('resource_defaults', saved)]:
                db.execute('INSERT INTO items VALUES (?,?,?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body',
                           (kind, tool, json.dumps(value)))
    return {'message': selected['label'] + ' saved for future drafts.', 'resource_defaults_saved': list(dict.fromkeys(tools))}
