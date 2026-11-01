"""Reviewed imports are bounded, stale-safe and atomic across registration writers."""
import concurrent.futures
import csv
import io
import json
import threading
import pytest
from viralogix import sample_imports as imports
from viralogix.runs import import_samples, register_sample
from viralogix.store import Store
from viralogix.ui_backend import dispatch


def table(rows, delimiter=',', headers=('sample_id', 'input_folder', 'read_mode')):
    out = io.StringIO(newline='')
    writer = csv.writer(out, delimiter=delimiter)
    writer.writerow(headers); writer.writerows(rows)
    return out.getvalue()


def test_review_defaults_quotes_bom_and_no_writes(tmp_path):
    store = Store(tmp_path/'workspace'); folder = tmp_path/'folder, with spaces'; folder.mkdir()
    payload = folder/'original'; payload.write_bytes(b'unchanged')
    text = '\ufeff' + table([['sample', folder, ''], ['other', folder, 'ont_only']])
    plan = imports.review(store, text)
    assert plan['can_import'] and plan['ready_count'] == 2 and plan['invalid_count'] == 0
    assert [r['mode'] for r in plan['rows']] == ['supplied_records', 'ont_only']
    assert [r['line'] for r in plan['rows']] == [2, 3]
    assert plan['rows'][0]['path'] == str(folder)
    assert store.all('samples') == [] and not store.jobs() and payload.read_bytes() == b'unchanged'
    assert imports.review(store, text)['token'] == plan['token']
    assert [r['id'] for r in imports.commit(store, text, plan['token'])] == ['sample', 'other']
    assert payload.read_bytes() == b'unchanged' and not store.jobs()


def test_tsv_optional_mode_and_blank_lines(tmp_path):
    store = Store(tmp_path/'workspace')
    text = table([['one', tmp_path]], '\t', ('sample_id','input_folder')) + '\r\n'
    plan = imports.review(store, text)
    assert plan['can_import'] and plan['rows'][0]['mode'] == 'supplied_records'
    assert len(import_samples(store, text)) == 1


def test_all_row_errors_and_casefold_duplicates(tmp_path):
    store = Store(tmp_path/'workspace'); register_sample(store, 'Registered', str(tmp_path))
    text = table([['new', tmp_path, 'supplied_records'], ['NEW', tmp_path, 'supplied_records'],
                  ['registered', tmp_path, 'bad_mode'], ['bad id', '/does-not-exist-viralogix', 'supplied_records'],
                  ['missing', '', ''], ['wrong_fields', str(tmp_path)]])
    plan = imports.review(store, text)
    assert not plan['can_import'] and plan['invalid_count'] == 6 and plan['token'] is None
    assert all('Duplicate sample ID' in r['errors'][0] for r in plan['rows'][:2])
    assert len(plan['rows'][2]['errors']) == 2 and len(plan['rows'][3]['errors']) == 2
    assert 'Field count' in plan['rows'][5]['errors'][0]
    with pytest.raises(ValueError, match='needs review'): imports.commit(store, text)
    assert [s['id'] for s in store.all('samples')] == ['Registered']


@pytest.mark.parametrize('text', ['', 'sample_id\na\n', 'sample_id,input_folder,input_folder\na,/tmp,/tmp\n',
    'sample_id,input_folder,typo\na,/tmp,x\n', 'sample_id,input_folder\na,"unterminated\n',
    'sample_id,input_folder\n'])
def test_malformed_headers_or_csv_are_review_errors(tmp_path, text):
    store = Store(tmp_path/'workspace'); plan = imports.review(store, text)
    assert plan['errors'] and not plan['can_import'] and plan['token'] is None
    with pytest.raises(ValueError): imports.commit(store, text)
    assert not store.all('samples')


def test_limits(tmp_path, monkeypatch):
    store = Store(tmp_path/'workspace')
    with pytest.raises(ValueError, match='2 MB'): imports.review(store, 'x'*(2*1024*1024+1))
    with pytest.raises(ValueError, match='2 MB'): imports.review(store, None)
    monkeypatch.setattr(imports, 'MAX_ROWS', 2)
    text = table([[str(i), tmp_path, 'supplied_records'] for i in range(3)])
    plan = imports.review(store, text)
    assert len(plan['rows']) == 2 and '500 sample rows' in plan['errors'][0]
    with pytest.raises(ValueError): imports.commit(store, text)
    assert not store.all('samples')


def test_ui_requires_review_and_exact_current_plan(tmp_path):
    store = Store(tmp_path/'workspace'); text = table([['one', tmp_path, 'supplied_records']])
    with pytest.raises(ValueError, match='Preview'): dispatch(store, 'import_samples', {'text': text})
    response = dispatch(store, 'preview_samples', {'text': text}); plan = response['sample_import']
    assert response['keep_modal'] and not store.all('samples')
    with pytest.raises(ValueError, match='changed'):
        dispatch(store, 'import_samples', {'text': text + '\n', 'token': plan['token']})
    # A registration elsewhere also requires review again, even without a conflicting ID.
    register_sample(store, 'other', str(tmp_path))
    with pytest.raises(ValueError, match='changed'):
        dispatch(store, 'import_samples', {'text': text, 'token': plan['token']})
    plan = dispatch(store, 'preview_samples', {'text': text})['sample_import']
    response = dispatch(store, 'import_samples', {'text': text, 'token': plan['token']})
    assert response['navigate'] == 'samples' and len(store.all('samples')) == 2
    with pytest.raises(ValueError, match='already registered'):
        dispatch(store, 'import_samples', {'text': text, 'token': plan['token']})
    assert len(store.all('samples')) == 2


def test_folder_removed_or_symlink_retargeted_after_review(tmp_path):
    store = Store(tmp_path/'workspace'); folder = tmp_path/'first'; folder.mkdir()
    link = tmp_path/'link'; link.symlink_to(folder, target_is_directory=True)
    text = table([['one', link, 'supplied_records']]); plan = imports.review(store, text)
    assert plan['rows'][0]['path'] == str(folder)
    second = tmp_path/'second'; second.mkdir(); link.unlink(); link.symlink_to(second, target_is_directory=True)
    with pytest.raises(ValueError, match='changed'): imports.commit(store, text, plan['token'])
    plan = imports.review(store, text); second.rmdir()
    with pytest.raises(ValueError, match='folder'): imports.commit(store, text, plan['token'])
    assert not store.all('samples')


def test_database_failure_rolls_back_entire_batch(tmp_path):
    store = Store(tmp_path/'workspace'); text = table([['first', tmp_path, 'supplied_records'], ['second', tmp_path, 'supplied_records']])
    with store.connect() as db:
        db.execute("CREATE TRIGGER fail_second BEFORE INSERT ON items WHEN NEW.kind='samples' AND NEW.id='second' BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError): imports.commit(store, text)
    assert not store.all('samples')


@pytest.mark.parametrize('other_writer', ['import', 'register'])
def test_concurrent_writers_cannot_create_case_collisions(tmp_path, other_writer):
    store = Store(tmp_path/'workspace'); barrier = threading.Barrier(2)
    def write(i):
        barrier.wait()
        try:
            if i and other_writer == 'register': return register_sample(store, 'SAMPLE', str(tmp_path))
            return imports.commit(store, table([['SAMPLE' if i else 'sample', tmp_path, 'supplied_records']]))
        except ValueError as exc:
            return str(exc)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(write, (0, 1)))
    assert len(store.all('samples')) == 1 and store.all('samples')[0]['id'].casefold() == 'sample'
    assert any(not isinstance(r, str) for r in outcomes)
    assert not store.jobs()


def test_preview_stays_read_only_during_application_update(tmp_path, monkeypatch):
    store = Store(tmp_path/'workspace'); text = table([['one', tmp_path, 'supplied_records']])
    from viralogix import updates
    def forbidden(*a, **k): raise AssertionError('mutation check used')
    monkeypatch.setattr(updates, 'assert_current', forbidden)
    monkeypatch.setattr(store, 'put', forbidden); monkeypatch.setattr(store, 'submit', forbidden)
    assert dispatch(store, 'preview_samples', {'text': text})['sample_import']['can_import']
    assert not store.all('samples')
