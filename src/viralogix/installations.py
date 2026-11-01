"""Reuse existing caches and remove unused, managed source snapshots."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from .local import git_read, local_path


def cache_choices(store, item):
    candidates = {}
    def add(path, label):
        if not path:
            return
        root = local_path(str(path))
        if not root.is_dir() or (root / 'conda-meta').exists():
            return
        key = str(root)
        if key in candidates:
            candidates[key]['labels'].append(label)
            return
        count = 0
        with os.scandir(root) as entries:
            for index, entry in enumerate(entries):
                if index >= 2000:
                    break
                if entry.is_dir(follow_symlinks=False) and Path(entry.path, 'conda-meta/history').is_file():
                    count += 1
        candidates[key] = {'path': key, 'labels': [label], 'environments': count}
    for other in store.all('installs'):
        if other['tool'] != item['tool']:
            continue
        label = other['version']['ref'] + ' · ' + other['version']['commit'][:8]
        for path in (other.get('rule_cache'), Path(other['source']) / '.snakemake/conda',
                     Path(other['original_source']) / '.snakemake/conda' if other.get('original_source') else None):
            try:
                add(path, label)
            except (OSError, ValueError):
                continue
    try:
        add(store.home / 'envs' / item['tool'], 'Shared Virologix cache')
    except (OSError, ValueError):
        pass
    return list(candidates.values())


def uninstall_plan(store, key):
    item = store.get('installs', key)
    if not item:
        raise ValueError('This version is no longer installed.')
    reasons = []
    active = store.get('settings', 'active-' + item['tool'])
    runs = [r['id'] for r in store.all('runs') if r.get('installation') == key]
    downloads = [d['id'] for d in store.all('database_downloads')
                 if d.get('installation') == key and d.get('status') != 'completed']
    busy = [j['id'] for j in store.jobs() if j['status'] in {'queued', 'running'}]
    if active == key:
        reasons.append('Select another active version before uninstalling this one.')
    if runs:
        reasons.append(f'{len(runs)} saved run(s), including archived runs, still depend on this installation.')
    if downloads:
        reasons.append('An unfinished database download still needs this installation for resume.')
    if busy:
        reasons.append('Finish queued or running jobs before uninstalling a version.')
    source = Path(item['source'])
    expected = store.home / 'sources' / key
    owned = source == expected and source.parent.resolve() == store.home / 'sources' and not source.is_symlink()
    if not owned:
        reasons.append('Only a Virologix-managed source snapshot can be removed here.')
    exists = source.exists()
    identity = None
    if owned and exists:
        stat = source.stat()
        identity = [stat.st_dev, stat.st_ino]
        protected = [store.home / 'envs', store.home / 'controllers', store.home / 'resources', store.home / 'runs']
        for other in store.all('installs'):
            protected.extend(Path(other[name]).resolve() for name in ('rule_cache', 'controller', 'original_source') if other.get(name))
            if other['id'] != key:
                protected.append(Path(other['source']).resolve())
        protected.extend(Path(r[name]).resolve() for r in store.all('runs') for name in ('folder', 'rule_cache') if r.get(name))
        if any(p == source or p.is_relative_to(source) for p in protected):
            reasons.append('This source folder contains a retained cache, runner, checkout or run folder.')
        try:
            if (git_read(source, 'rev-parse', 'HEAD') != item['version']['commit']
                    or git_read(source, 'status', '--porcelain', '--untracked-files=all', '--ignored')):
                reasons.append('The source has changes or extra files. Preserve them before uninstalling.')
        except ValueError:
            reasons.append('The source snapshot cannot be verified as an unchanged Git checkout.')
    signature = hashlib.sha256(json.dumps([item, active, sorted(runs), sorted(downloads), sorted(busy), identity, reasons], sort_keys=True).encode()).hexdigest()
    return {'id': key, 'tool': item['tool'], 'version': item['version']['ref'], 'source': str(source),
            'source_exists': exists, 'blocked': reasons, 'runs': runs, 'signature': signature,
            'controller': item.get('controller'), 'cache': item.get('rule_cache') or str(store.home / 'envs' / item['tool'])}


def uninstall(store, key, signature):
    staged = None
    source = None
    try:
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            plan = uninstall_plan(store, key)
            if plan['blocked']:
                raise ValueError(' '.join(plan['blocked']))
            if plan['signature'] != signature:
                raise ValueError('This installation changed. Review uninstall again.')
            source = Path(plan['source'])
            if plan['source_exists']:
                staged = Path(tempfile.mkdtemp(prefix='uninstall-', dir=store.home))
                source.rename(staged / 'source')
            db.execute("DELETE FROM items WHERE kind IN ('installs','environment_checks') AND id=?", (key,))
    except BaseException:
        if staged:
            if (staged / 'source').exists():
                (staged / 'source').rename(source)
            staged.rmdir()
        raise
    cleanup = ''
    if staged:
        try:
            shutil.rmtree(staged)
        except OSError:
            cleanup = f' Source cleanup is incomplete at {staged}.'
    return 'Version uninstalled. Runners, tool environments, databases, runs and original checkouts were retained.' + cleanup
