"""Bounded metadata-only accounting of known storage; never a cleanup authority."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import stat
import time

from . import databases
from .runs import parse_config
from .store import now

MAX_LOCATIONS = 500
MAX_ENTRIES = 100000
MAX_DEPTH = 64
MAX_SECONDS = 8
BACKUPS = '.viralogix-repair-backups'
NOTICE = ('File sizes are a live observation, not a filesystem snapshot or reclaimable space. '
          'Regular-file logical bytes and allocated blocks exclude directory/filesystem overhead. '
          'Hard links are counted once per scan at the first encountered location; reflinks, compression '
          'and filesystem snapshots may share physical storage that this scan cannot identify. '
          'Links and special files are skipped. Cross-device entries are skipped unless registered as scan roots; '
          'same-device bind mounts are not distinguished. '
          'Registered paths and backup-folder names do not prove exclusive ownership. No files are deleted.')


def catalog(store):
    locations, omitted = {}, 0
    home = store.home

    def add(value, category, label, target=None):
        nonlocal omitted
        if not value or not isinstance(value, (str, Path)):
            return
        path = Path(value).expanduser()
        # Resolve neither links nor relative configuration paths against an invented base.
        if not path.is_absolute() or '..' in path.parts or '\x00' in str(path):
            omitted += 1
            return
        key = str(path)
        if key not in locations:
            if len(locations) >= MAX_LOCATIONS:
                omitted += 1
                return
            locations[key] = {'id': hashlib.sha256(key.encode()).hexdigest()[:20], 'path': key,
                              'category': category, 'references': [],
                              'external': not path.is_relative_to(home)}
        row = locations[key]
        if row['category'] != category:
            row['category'] = 'shared'
        ref = {'label': str(label), **(target or {})}
        if ref not in row['references']:
            row['references'].append(ref)

    add(home, 'workspace', 'Workspace remainder')
    for folder, category in [('runs', 'runs'), ('envs', 'environments'), ('controllers', 'environments'),
                             ('resources', 'databases'), ('sources', 'sources'), ('logs', 'logs')]:
        add(home / folder, category, folder.capitalize())
    archived = {r['id'] for r in store.all('run_visibility') if r.get('archived')}

    def environment(value, label, target):
        add(value, 'environments', label, target)
        if isinstance(value, (str, Path)) and value:
            add(Path(value) / BACKUPS, 'backups', 'Retained repair folders · ' + label, target)

    def configured(tool, cfg, label, target):
        if tool == 'hybas':
            raw = cfg.get('db_root')
            if raw:
                root = home / 'resources/hybas/db' if raw == 'db' else Path(str(raw)).expanduser()
                add(root / str(cfg.get('kraken_db_name', 'standard')), 'databases', label + ' · Kraken2', target)
                add(root / 'busco' / str(cfg.get('busco_lineage', 'bacteria_odb10')), 'databases', label + ' · BUSCO', target)
        else:
            for spec in databases.CATALOG.get(tool, []):
                for key in spec.get('fields', []):
                    if key.endswith(('database_version', 'prot_t5_identity')):
                        continue
                    add(databases._get(cfg, key), 'databases', label + ' · ' + spec['name'], target)

    for item in store.all('installs'):
        target = {'view': 'install'}
        add(item.get('source'), 'sources', item['id'], target)
        add(item.get('original_source'), 'sources', item['id'] + ' · original checkout', target)
        add(item.get('controller'), 'environments', item['id'] + ' · runner', target)
        environment(item.get('rule_cache') or home / 'envs' / item['tool'], item['id'] + ' · tool cache', target)
    for run in store.all('runs'):
        label = str(run.get('label', run['id'])) + (' (archived)' if run['id'] in archived else '')
        target = {'view': 'run', 'run_id': run['id']}
        add(run.get('folder'), 'runs', label + ' · saved files', target)
        add(run.get('output'), 'runs', label + ' · outputs', target)
        add(run.get('controller'), 'environments', label + ' · recorded runner', target)
        environment(run.get('rule_cache'), label + ' · tool cache', target)
        try:
            configured(run['tool'], parse_config(run['config']), label, target)
        except (ValueError, KeyError, TypeError):
            omitted += 1
    for tool in ('hybas', 'basis'):
        text = store.get('configs', tool)
        if text:
            try:
                configured(tool, parse_config(text), tool + ' · saved defaults', {'view': 'configure'})
            except (ValueError, TypeError):
                omitted += 1
        for key, value in store.get('database_locations', tool, {}).items():
            add(value.get('path'), 'databases', tool + ' · ' + key, {'view': 'resources'})
    for row in store.all('database_downloads'):
        add(row.get('destination'), 'databases', row['id'] + ' · download', {'view': 'resources'})
    rows = sorted(locations.values(), key=lambda r: r['path'])
    revision = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
    return {'locations': rows, 'revision': revision, 'omitted': omitted}


@contextmanager
def _open(path):
    """No-follow descriptor traversal, including every parent directory."""
    path = Path(path)
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for index, part in enumerate(path.parts[1:], 1):
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            if index < len(path.parts) - 1:
                flags |= os.O_DIRECTORY
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def panel(store):
    current = catalog(store)
    saved = store.get('storage', 'latest')
    return {**current, 'last_scan': saved,
            'scope_changed': bool(saved and saved['revision'] != current['revision']),
            'limits': {'seconds': MAX_SECONDS, 'entries': MAX_ENTRIES, 'depth': MAX_DEPTH}, 'notice': NOTICE}


def scan(store, revision, include_external=False):
    if type(include_external) is not bool:
        raise ValueError('Choose whether to include registered external locations.')
    current = catalog(store)
    if revision != current['revision']:
        raise ValueError('Registered locations changed. Refresh storage before scanning.')
    start = time.monotonic()
    counters = dict(entries=0, links=0, special=0, mounts=0, inaccessible=0, hardlinks=0, depth=0)
    seen_files, seen_dirs, devices = set(), set(), {}
    rows = [{**r, 'logical_bytes': 0, 'allocated_bytes': 0, 'files': 0, 'state': 'not_scanned',
             'allocation_known': True} for r in current['locations']]
    active = [j['id'] for j in store.jobs() if j['status'] == 'running']
    limits = set()

    def bound():
        if counters['entries'] >= MAX_ENTRIES:
            limits.add('entry limit')
        if time.monotonic() - start >= MAX_SECONDS:
            limits.add('time limit')
        return bool(limits)

    def count(st, row):
        key = (st.st_dev, st.st_ino)
        if key in seen_files:
            counters['hardlinks'] += 1
            return
        seen_files.add(key)
        row['files'] += 1
        row['logical_bytes'] += st.st_size
        blocks = getattr(st, 'st_blocks', None)
        if blocks is None:
            row['allocation_known'] = False
        else:
            row['allocated_bytes'] += blocks * 512

    def walk(fd, path, row, depth, device):
        if bound():
            row['state'] = 'partial'
            return
        st = os.fstat(fd)
        key = (st.st_dev, st.st_ino)
        if key in seen_dirs: return
        seen_dirs.add(key)
        if depth >= MAX_DEPTH:
            counters['depth'] += 1
            row['state'] = 'partial'
            return
        with os.scandir(fd) as entries:
            for entry in entries:
                if bound():
                    row['state'] = 'partial'
                    return
                counters['entries'] += 1
                try:
                    st = entry.stat(follow_symlinks=False)
                    if stat.S_ISLNK(st.st_mode):
                        counters['links'] += 1
                    elif st.st_dev != device:
                        counters['mounts'] += 1
                    elif stat.S_ISREG(st.st_mode):
                        count(st, row)
                    elif stat.S_ISDIR(st.st_mode):
                        child = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                        try:
                            actual = os.fstat(child)
                            if (actual.st_dev, actual.st_ino) != (st.st_dev, st.st_ino):
                                raise OSError('Directory changed')
                            # Recognize orphaned retained repair folders without reading receipts.
                            target = row
                            if entry.name == BACKUPS and row['category'] != 'backups':
                                backup_path = str(path / entry.name)
                                target = next((r for r in rows if r['path'] == backup_path), None)
                                if target is None and len(rows) < MAX_LOCATIONS:
                                    target = {**row, 'id': hashlib.sha256(backup_path.encode()).hexdigest()[:20],
                                              'path': backup_path, 'category': 'backups', 'references': [{'label': 'Retained repair folders (path convention)'}],
                                              'logical_bytes': 0, 'allocated_bytes': 0, 'files': 0, 'state': 'measured'}
                                    rows.append(target)
                                if target is None:
                                    limits.add('location limit')
                                    row['state'] = 'partial'
                                    return
                            walk(child, path / entry.name, target, depth + 1, device)
                        finally:
                            os.close(child)
                    else:
                        counters['special'] += 1
                except OSError:
                    counters['inaccessible'] += 1
                    row['state'] = 'partial'

    # Specific locations first; ancestor walks skip directories already visited.
    for row in sorted(rows.copy(), key=lambda r: (-len(Path(r['path']).parts), r['path'])):
        path = Path(row['path'])
        if row['external'] and not include_external:
            row['state'] = 'not_selected'
            continue
        if str(path) == '/' or path in store.home.parents or any(path.is_relative_to(p) for p in ('/proc', '/sys', '/dev', '/run')):
            row['state'] = 'refused'
            continue
        if bound(): continue
        try:
            with _open(path) as fd:
                st = os.fstat(fd)
                row['state'] = 'measured'
                if stat.S_ISDIR(st.st_mode) or stat.S_ISREG(st.st_mode):
                    if st.st_dev not in devices:
                        try:
                            v = os.fstatvfs(fd)
                            devices[st.st_dev] = {'device': st.st_dev, 'path': str(path),
                                'total_bytes': v.f_blocks * v.f_frsize, 'available_bytes': v.f_bavail * v.f_frsize}
                        except OSError: pass
                    if stat.S_ISDIR(st.st_mode): walk(fd, path, row, 0, st.st_dev)
                    else: count(st, row)
                else:
                    row['state'] = 'unavailable'
                    counters['special'] += 1
        except FileNotFoundError:
            row['state'] = 'missing'
        except OSError:
            row['state'] = 'unavailable'
            counters['inaccessible'] += 1
    result = {'schema': 1, 'created_at': now(), 'revision': current['revision'],
              'include_external': include_external, 'locations': rows, 'devices': list(devices.values()),
              'logical_bytes': sum(r['logical_bytes'] for r in rows),
              'allocated_bytes': sum(r['allocated_bytes'] for r in rows),
              'allocation_known': all(r['allocation_known'] for r in rows),
              'partial': bool(limits or current['omitted'] or counters['inaccessible'] or counters['depth'] or counters['mounts']
                              or any(r['state'] in {'refused', 'unavailable', 'not_scanned', 'partial'} for r in rows)),
              'limits_reached': sorted(limits), 'counters': counters, 'omitted': current['omitted'],
              'active_jobs_at_start': active, 'elapsed_s': round(time.monotonic() - start, 3), 'notice': NOTICE}
    store.put('storage', 'latest', result)
    return result


def download(store):
    saved = store.get('storage', 'latest')
    if not saved:
        raise ValueError('Measure storage before downloading an overview.')
    return {'name': 'viralogix-storage.json', 'type': 'application/json',
            'text': json.dumps(saved, ensure_ascii=False, indent=2) + '\n'}
