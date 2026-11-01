"""Saved values are compared without defaults, file reads, probes or mutations."""
import copy
import hashlib
import json
import subprocess
import pytest
from viralogix import comparisons as c
from viralogix.store import Store
from viralogix.ui_backend import dispatch


def saved(store, rid, config, **extra):
    row = dict(id=rid, label=rid, tool='flupop', config=config, commit='a'*40,
               cores=4, memory_mb=16000, sample={'id': 'fixture', 'path': '/never/read', 'mode': 'hybrid'}, **extra)
    store.put('runs', rid, row)
    return row


def rows(doc):
    return {(r['scope'], tuple(r['path'])): r for r in doc['rows']}


def test_types_missing_null_order_and_literal_paths(tmp_path):
    store = Store(tmp_path)
    left = saved(store, 'a', 'bool: true\ninteger: 1\nnumber: 1.0\nnullish: null\nempty: {}\nlist: [1, 2]\na.b: literal\na: {b: nested}\n')
    right = saved(store, 'b', 'bool: 1\ninteger: 1.0\nnumber: 1\nempty: null\nlist: [2, 1]\na.b: literal\na: {b: changed}\n')
    d = c.panel(store, ['a', 'b']); r = rows(d)
    for key in ['bool', 'integer', 'number', 'nullish', 'empty', 'list']:
        assert r['configuration', (key,)]['changed']
    assert [v['type'] for v in r['configuration', ('nullish',)]['cells']] == ['null', 'missing']
    assert not r['configuration', ('a.b',)]['changed']
    assert r['configuration', ('a', 'b')]['changed']
    assert d['reference_id'] == 'a' and d['runs'][0]['config_sha256'] == hashlib.sha256(left['config'].encode()).hexdigest()
    assert store.get('runs', 'a') == left and store.get('runs', 'b') == right


def test_mapping_order_formatting_and_lists_of_mappings(tmp_path):
    store = Store(tmp_path)
    saved(store, 'a', '# comment\nvalue: [{x: 1, y: 2}]\nempty: {}\n')
    saved(store, 'b', 'empty: {}\nvalue:\n  - y: 2\n    x: 1\n')
    d = c.panel(store, ['a', 'b'])
    assert d['changed_rows'] == 0
    assert d['runs'][0]['config_sha256'] != d['runs'][1]['config_sha256']
    assert d['runs'][0]['value_sha256'] == d['runs'][1]['value_sha256']


def test_nested_nonstring_keys_remain_typed(tmp_path):
    store = Store(tmp_path)
    saved(store, 'a', 'custom: {1: integer, "1": string}\n')
    saved(store, 'b', 'custom: {"1": string}\n')
    r = rows(c.panel(store, ['a', 'b']))['configuration', ('custom',)]
    assert r['changed'] and '1: integer' in r['cells'][0]['yaml']
    assert "'1': string" in r['cells'][0]['yaml']


def test_empty_mapping_missing_subtrees_and_scalar_replacement(tmp_path):
    store = Store(tmp_path)
    saved(store, 'a', 'empty: {}\nnested: {x: 1}\nchanged: {x: 1}\n')
    saved(store, 'b', 'changed: false\n')
    r = rows(c.panel(store, ['a', 'b']))
    assert r['configuration', ('empty',)]['cells'][1]['type'] == 'missing'
    assert r['configuration', ('nested', 'x')]['cells'][1]['type'] == 'missing'
    assert [v['type'] for v in r['configuration', ('changed',)]['cells']] == ['mapping', 'boolean']


def test_four_runs_reference_provenance_and_archived_records(tmp_path):
    store = Store(tmp_path)
    for i in range(4): saved(store, str(i), f'value: {i % 2}\n')
    changed = store.get('runs', '2'); changed.update(tool='basis', cores=8, commit='b'*40)
    store.put('runs', '2', changed)
    store.put('run_visibility', '2', {'archived': True})
    d = c.panel(store, ['2', '0', '1', '3']); r = rows(d)
    assert d['reference_id'] == '2' and d['runs'][0]['archived']
    assert [v['differs_from_reference'] for v in r['configuration', ('value',)]['cells']] == [False, False, True, True]
    assert r['provenance', ('cores',)]['changed'] and r['provenance', ('tool',)]['changed']
    assert 'different meanings' in d['notice']


@pytest.mark.parametrize('ids', [None, 'ab', [], ['a'], ['a']*2, ['a','b','c','d','e'], ['a',None]])
def test_invalid_selection(tmp_path, ids):
    with pytest.raises(ValueError, match='2 and 4 distinct'):
        c.panel(Store(tmp_path), ids)


@pytest.mark.parametrize('text', [None, 'broken: [', 'value: .nan', 'value: &x [*x]', 'value: 2026-10-28'])
def test_missing_or_invalid_saved_yaml_not_reported_as_missing_keys(tmp_path, text):
    store = Store(tmp_path); saved(store, 'a', text); saved(store, 'b', 'value: 1\n')
    with pytest.raises(ValueError, match='run.? a'):
        c.panel(store, ['a', 'b'])


def test_missing_run_and_bounds(tmp_path, monkeypatch):
    store = Store(tmp_path); saved(store, 'a', 'nested: {x: 1}\n')
    with pytest.raises(ValueError, match='no longer registered'): c.panel(store, ['a', 'b'])
    saved(store, 'b', 'nested: {x: 1}\n')
    monkeypatch.setattr(c, 'MAX_ROWS', 1)
    with pytest.raises(ValueError, match='5000 rows'): c.panel(store, ['a', 'b'])
    monkeypatch.setattr(c, 'MAX_ROWS', 5000); monkeypatch.setattr(c, 'MAX_EXPORT_BYTES', 10)
    with pytest.raises(ValueError, match='16 MB'): c.panel(store, ['a', 'b'])
    monkeypatch.setattr(c, 'MAX_EXPORT_BYTES', 16*1024*1024); monkeypatch.setattr(c, 'MAX_DEPTH', 1)
    with pytest.raises(ValueError, match='nesting'): c.panel(store, ['a', 'b'])


def test_dispatch_export_exact_snapshot_and_read_only(tmp_path, monkeypatch):
    store = Store(tmp_path); saved(store, 'a', 'custom: "<script>fixture</script>"\n'); saved(store, 'b', 'custom: false\n')
    before = copy.deepcopy(store.all('runs'))
    def forbidden(*args, **kwargs): raise AssertionError('unexpected operation')
    monkeypatch.setattr(subprocess, 'run', forbidden); monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(store, 'put', forbidden); monkeypatch.setattr(store, 'submit', forbidden)
    # Read-only exports stay available even when app replacement blocks mutations.
    from viralogix import updates
    monkeypatch.setattr(updates, 'assert_current', forbidden)
    r = dispatch(store, 'download_comparison', {'ids': ['a', 'b']})
    assert json.loads(r['download']['text']) == r['comparison']
    assert dispatch(store, 'compare_saved_runs', {'ids': ['b','a']})['comparison']['reference_id'] == 'b'
    assert store.all('runs') == before and not store.jobs()
