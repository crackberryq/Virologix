"""Bounded, read-only host checks. These are not estimates of analysis requirements."""
from __future__ import annotations

import os
from pathlib import Path
import shutil

from . import hardware
from .runs import parse_config
from .store import now

MIB = 1024 ** 2


def destination(path, label):
    """Inspect the closest existing directory without creating probe files."""
    result = {'label': label, 'path': str(path), 'level': 'info', 'free_mb': None}
    try:
        target = Path(path).expanduser()
        if not target.is_absolute():
            raise ValueError('Use an absolute destination path.')
        folder = target
        while not folder.exists():
            if folder.is_symlink():
                raise ValueError('A destination symlink has no accessible target.')
            if folder == folder.parent:
                raise ValueError('No accessible parent directory.')
            folder = folder.parent
        if not folder.is_dir():
            raise ValueError('The destination or its parent is a file, not a directory.')
        if not os.access(folder, os.W_OK | os.X_OK):
            raise ValueError('The app has no write/search permission here.')
        if hasattr(os, 'statvfs') and os.statvfs(folder).f_flag & getattr(os, 'ST_RDONLY', 1):
            raise ValueError('The destination filesystem is read-only.')
        result.update(checked_parent=str(folder), free_mb=shutil.disk_usage(folder).free // MIB)
        result['text'] = 'Directory permissions allow writing; actual writes are checked by the workflow.'
    except (OSError, ValueError, TypeError, RuntimeError) as exc:
        result.update(level='error', text=str(exc))
    return result


def destinations(run, action='run'):
    cfg = parse_config(run['config'])
    paths = [(run['folder'], 'Run folder'), (str(Path(run['folder']) / 'workflow'), 'Workflow working folder')]
    if action == 'run':
        paths.append((run['output'], 'Results folder'))
        # Only explicit additional write destinations; never probe database inputs as writable.
        if run['tool'] == 'basis':
            for section, key, label in [('storage', 'native_results_directory', 'Native results folder'),
                                        ('deep', 'placement_cache_dir', 'Placement cache')]:
                value = cfg.get(section, {})
                if isinstance(value, dict) and value.get(key):
                    paths.append((value[key], label))
    if action == 'prepare' and run.get('rule_cache'):
        paths.append((run['rule_cache'], 'Tool environment cache'))
    seen, result = set(), []
    for path, label in paths:
        if str(path) not in seen:
            result.append(destination(path, label))
            seen.add(str(path))
    return result


def budget(run, info):
    """Report oversubscription; never rewrite a frozen configuration or tune thresholds."""
    cores, memory = run['cores'], run['memory_mb']
    issues = []
    available_cpu = info['cpu']['available']
    total, available = info['memory']['total_mb'], info['memory']['available_mb']
    if cores > available_cpu:
        issues.append(f'The run requests {cores} CPU threads; {available_cpu} are available to this app.')
    if total is None:
        issues.append('RAM capacity could not be detected.')
    elif memory > total:
        issues.append(f'The {memory:,} MB run budget exceeds the detected {total:,} MB RAM capacity.')
    elif available is not None and memory > available:
        issues.append(f'The {memory:,} MB run budget exceeds the {available:,} MB RAM currently available.')
    cfg = parse_config(run['config'])
    # Report explicit tool limits only. Native defaults/dynamic rules are validated by Snakemake.
    if run['tool'] == 'hybas':
        limits = [('assembly_mem_mb', cfg.get('assembly_mem_mb'), 1)]
        limits.append(('spades_memory_gb', cfg.get('spades_memory_gb'), 1024))
        if str(cfg.get('polish_mode', '')).lower() not in {'', 'none'}:
            limits.append(('polishing_mem_mb', cfg.get('polishing_mem_mb'), 1))
        if cfg.get('run_kraken') is not False and cfg.get('kraken_decision_mode') != 'off':
            limits.append(('kraken_mem_mb', cfg.get('kraken_mem_mb'), 1))
    else:
        limits = []
        modules = cfg.get('modules', {})
        for name, values in (modules.items() if isinstance(modules, dict) else []):
            if isinstance(values, dict) and values.get('enabled') is not False:
                limits.append((f'modules.{name}.memory_mb', values.get('memory_mb'), 1))
        deep = cfg.get('deep', {})
        if isinstance(deep, dict) and deep.get('enabled') is True:
            limits.append(('deep.memory_mb', deep.get('memory_mb'), 1))
    for name, value, scale in limits:
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value * scale > memory:
            issues.append(f'{name} ({value}) exceeds the {memory:,} MB run budget. Review this limit in a revised draft.')
    return issues


def panel(store, run):
    checked_at = now()
    locations = destinations(run)
    invalid = [x for x in locations if x['level'] == 'error']
    measured = [x for x in locations if x['free_mb'] is not None]
    full = [x for x in locations if x['free_mb'] == 0]
    low = [x for x in locations if x['free_mb'] is not None and x['free_mb'] < 5120]
    info = hardware.inventory(store)
    warnings = budget(run, info)
    def row(key, title, state, text, level, **extra):
        return dict(id=key, title=title, state=state, text=text, level=level, checked_at=checked_at, **extra)
    rows = [row('destinations', 'Output permissions', 'Needs attention' if invalid else 'Permissions checked',
                ' '.join(x['label'] + ': ' + x['text'] for x in invalid) if invalid else
                'The results and working folders, or their nearest existing parents, pass read-only permission checks. No probe files were created.',
                'error' if invalid else 'info', action='paths'),
            row('storage', 'Disk space', 'Less than 1 MB free' if full else 'Low free space' if low else 'Partly checked' if invalid and measured else 'Free space checked' if measured else 'Unavailable',
                (' '.join(f"{x['label']}: {x['free_mb'] / 1024:.1f} GB free." for x in measured) if measured else 'Disk space could not be checked for these destinations.') +
                ' Output, temporary-file and database growth cannot be predicted here. Below 5 GB is a warning, not an analysis size estimate.',
                'error' if full else 'warning' if low else 'info' if measured else 'pending', action='paths'),
            row('resources', 'CPU and RAM budget', 'Review budget' if warnings else 'Within detected capacity',
                ' '.join(warnings) if warnings else f"{run['cores']} CPU threads / {run['memory_mb']:,} MB. Tool requirements and concurrent memory use still apply.",
                'warning' if warnings else 'info', action='budget', inventory_checked_at=info['checked_at'])]
    rows[-1]['checked_at'] = info['checked_at']
    return {'rows': rows, 'destinations': locations, 'blocked': bool(invalid or full)}


def assert_launch(run, action):
    # Rechecked when queued AND when the worker starts; warnings do not prevent dry-runs.
    problems = []
    for item in destinations(run, action):
        if item['level'] == 'error':
            problems.append(item['label'] + ': ' + item['text'] + ' ' + item['path'])
        elif item['free_mb'] == 0:
            problems.append(item['label'] + ': less than 1 MB free disk space. ' + item['path'])
    if problems:
        raise ValueError('Pre-run checks: ' + ' '.join(problems) + ' Restore access/free space, then refresh run checks.')
