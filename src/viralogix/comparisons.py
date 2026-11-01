"""Read-only, typed comparisons of saved records; never infer runtime defaults."""
from __future__ import annotations

import hashlib
import json

import yaml

from . import __version__
from .runs import parse_config
from .store import now

MAX_ROWS = 5000
MAX_DEPTH = 64
MAX_EXPORT_BYTES = 16 * 1024 * 1024
MISSING = object()
NOTICE = ('Compares stored configuration values and recorded provenance only. Missing keys are not '
          'resolved from pipeline defaults. Mapping order and YAML comments/formatting are ignored; '
          'list order and scalar types are significant. Different pipelines may give the same key '
          'different meanings. This does not compare results, verify files or recommend settings. '
          'Exports contain saved values, local paths and identifiers; review before sharing.')


def typed(value, depth=0):
    """Stable identity without Python bool/int equality or stringified-key collisions."""
    if depth > MAX_DEPTH:
        raise ValueError('Configuration nesting exceeds the comparison limit of 64 levels.')
    if isinstance(value, dict):
        pairs = [[typed(k, depth + 1), typed(v, depth + 1)] for k, v in value.items()]
        return ['mapping', sorted(pairs, key=lambda p: json.dumps(p[0], sort_keys=True))]
    if isinstance(value, list):
        return ['list', [typed(v, depth + 1) for v in value]]
    return [type(value).__name__, value]


def fingerprint(value):
    return json.dumps(typed(value), ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def cell(value):
    if value is MISSING:
        return {'present': False, 'type': 'missing', 'yaml': None}
    kinds = {dict: 'mapping', list: 'list', str: 'string', bool: 'boolean', int: 'integer', float: 'number', type(None): 'null'}
    return {'present': True, 'type': kinds[type(value)],
            'yaml': yaml.safe_dump(value, sort_keys=False, allow_unicode=True).removesuffix('...\n').rstrip('\n')}


def panel(store, ids):
    if (not isinstance(ids, list) or not 2 <= len(ids) <= 4
            or any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids)):
        raise ValueError('Choose between 2 and 4 distinct saved runs.')
    runs, configs, identities = [], [], []
    for rid in ids:
        run = store.get('runs', rid)
        if not isinstance(run, dict):
            raise ValueError('Saved run is no longer registered: ' + rid)
        text = run.get('config')
        if not isinstance(text, str):
            raise ValueError('Saved configuration is unavailable for run: ' + rid)
        try:
            cfg = parse_config(text)
            identity = fingerprint(cfg)
        except (ValueError, TypeError, RecursionError, yaml.YAMLError) as exc:
            raise ValueError('Cannot compare the saved configuration for run ' + rid + ': ' + str(exc)) from exc
        runs.append(run); configs.append(cfg); identities.append(identity)
    rows = []

    def add(scope, path, values):
        if len(rows) >= MAX_ROWS:
            raise ValueError('Comparison exceeds 5000 rows. Download individual saved YAML files instead.')
        keys = [None if value is MISSING else fingerprint(value) for value in values]
        rows.append({'scope': scope, 'path': path, 'changed': len(set(keys)) > 1,
                     'cells': [dict(cell(value), differs_from_reference=key != keys[0]) for value, key in zip(values, keys)]})

    def walk(path, values):
        present = [v for v in values if v is not MISSING]
        if all(isinstance(v, dict) and all(isinstance(k, str) for k in v) for v in present):
            keys = sorted({k for v in present for k in v})
            # Empty mappings are values, not absent descendants.
            if keys and all(v for v in present):
                for key in keys:
                    walk([*path, key], [v.get(key, MISSING) if isinstance(v, dict) else MISSING for v in values])
                return
        add('configuration', path, values)

    for key in sorted({k for cfg in configs for k in cfg}):
        walk([key], [cfg.get(key, MISSING) for cfg in configs])
    for key in ('tool', 'commit', 'installation', 'controller', 'run_type', 'parent', 'output', 'cores', 'memory_mb'):
        add('provenance', [key], [r.get(key, MISSING) for r in runs])
    for key in ('id', 'path', 'mode'):
        add('provenance', ['sample', key], [(r.get('sample') or {}).get(key, MISSING) for r in runs])
    doc = {'schema': 1, 'created_at': now(), 'app_version': __version__, 'reference_id': ids[0],
           'runs': [{'id': r['id'], 'label': r.get('label', r['id']), 'tool': r.get('tool'),
                     'archived': bool(store.get('run_visibility', r['id'], {}).get('archived')),
                     'config_sha256': hashlib.sha256(r['config'].encode()).hexdigest(),
                     'value_sha256': hashlib.sha256(identity.encode()).hexdigest()}
                    for r, identity in zip(runs, identities)],
           'rows': rows, 'changed_rows': sum(row['changed'] for row in rows), 'notice': NOTICE}
    if len(export(doc)['text'].encode()) > MAX_EXPORT_BYTES:
        raise ValueError('Comparison exceeds 16 MB. Download individual saved YAML files instead.')
    return doc


def export(doc):
    return {'name': 'viralogix-saved-comparison.json', 'type': 'application/json',
            'text': json.dumps(doc, ensure_ascii=False, indent=2) + '\n'}
