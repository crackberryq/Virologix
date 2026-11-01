"""Local support export: least-data selection, safe log reads and exact reviewed text."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import zipfile

import pytest

from viralogix import hardware, support as s
from viralogix.store import Store
from viralogix.ui_backend import dispatch, handle_request


def metadata(preview):
    text = preview['text'].split('Recorded software diagnostics:\n', 1)[1]
    return json.JSONDecoder().raw_decode(text)[0]


@pytest.fixture
def workspace(tmp_path):
    store = Store(tmp_path / 'Private Project/workspace')
    old = {'id': 'older', 'tool': 'flupop', 'version': {'commit': 'a'*40, 'ref': 'private branch'},
           'source': '/home/private/source', 'controller': '/home/private/runner', 'ready': True,
           'rule_cache': '/home/private/envs', 'controller_requirements': {'python': '3.11', 'snakemake': '9.6.2'}}
    newer = {**old, 'id': 'newer', 'version': {'commit': 'b'*40}}
    store.put('installs', 'older', old)
    store.put('installs', 'newer', newer)
    store.put('settings', 'active-flupop', 'newer')
    store.put('runs', 'run-private', {'id': 'run-private', 'tool': 'flupop', 'installation': 'older',
              'commit': 'a'*40, 'config_sha256': 'c'*64, 'workflow_sha256': 'd'*64, 'cores': 4, 'memory_mb': 8192,
              'sample': {'id': 'patient-007', 'path': '/private/sequence/inputs'}, 'label': 'Confidential Study',
              'config': 'api_key: do-not-include-config\n', 'output': '/private/results'})
    store.put('samples', 'other-patient', {'id': 'other-patient', 'path': '/private/unrelated'})
    store.put('environment_checks', 'older', {'runner': {'status': 'Verified', 'checked_at': '2026-10-27T00:00:00+00:00',
              'path': '/private/env/qc', 'definition': 'e'*64, 'message': 'private environment output'},
              'private-custom-env': {'status': 'Missing'}})
    jid = store.submit('workflow', {'run_id': 'run-private', 'action': 'run', 'secret': 'private payload'})
    store.update_job(jid, status='failed', error='patient-007: missing database at /home/private/databases with spaces')
    store.log_path(jid).write_text('patient-007 failed\nFile "/home/private/worker.py", line 40\nValueError: missing database\n')
    return store, jid


def test_preview_defaults_to_metadata_and_preserves_exact_run_commit(workspace, monkeypatch):
    store, jid = workspace
    def forbidden(*args, **kwargs): pytest.fail('Preview must not probe tools, read logs by default, or mutate the workspace')
    monkeypatch.setattr(s, 'log_tail', forbidden)
    monkeypatch.setattr(hardware, 'detect', forbidden)
    monkeypatch.setattr(store, 'put', forbidden)
    preview = s.preview(store, jid)
    data = metadata(preview)
    assert data['selected_job']['run_commit'] == 'a'*40
    assert data['active_installations']['flupop']['commit'] == 'b'*40
    assert data['selected_job']['job_installation_recorded']['runner_ready_recorded'] is True
    assert data['selected_job']['job_installation_recorded']['environment_checks_recorded'] == [
        {'environment': 'runner', 'status': 'Verified', 'checked_at': '2026-10-27T00:00:00+00:00', 'definition': 'e'*64}]
    assert data['log_excerpt']['status'] == 'not requested'
    for secret in ['patient-007', 'other-patient', 'Confidential Study', '/private', '/home/private',
                   'do-not-include-config', 'private payload', 'private branch', 'private environment', 'private-custom-env']:
        assert secret not in preview['text']
    assert data['capacity_recorded']['source'] == 'not recorded in this app session'
    general = metadata(s.preview(store))
    assert general['selected_job'] is None


def test_opt_in_redacts_error_and_only_reads_the_selected_job(workspace):
    store, jid = workspace
    other = store.submit('smoke', {})
    store.log_path(other).write_text('UNRELATED JOB MUST NOT APPEAR')
    preview = s.preview(store, jid, True)
    assert 'ValueError: missing database' in preview['text']
    assert '/worker.py", line 40' in preview['text']
    assert 'patient-007' not in preview['text'] and '/home/private' not in preview['text']
    assert 'databases with spaces' not in preview['text']
    assert 'UNRELATED JOB' not in preview['text']
    assert preview['log']['status'] == 'included' and preview['redactions']


@pytest.mark.parametrize('line,secret', [
    ('TOKEN=very-private-token', 'very-private-token'),
    ('Authorization: Bearer private-password', 'private-password'),
    ('{"apiKey": "secret-value", "other": "same-line"}', 'secret-value'),
    ('--password private-secret', 'private-secret'),
    ('--access-key private-secret', 'private-secret'),
    ('"api_key":\n    "multiline-secret"', 'multiline-secret'),
    ('$ curl https://host.test --data private-argument', 'private-argument'),
    ('Shell command: run --name private-argument', 'private-argument'),
    ('download https://user:password@host.test/private?token=key', 'host.test'),
    ('contact jimi@example.test', 'jimi@example.test'),
    ('server 172.21.21.143 or 2001:db8::1', '172.21.21.143'),
    ('File "/home/jimi/Private Project/worker.py", line 40', 'Private Project'),
    (r'File "C:\Users\Jimi\Private Project\worker.py", line 40', 'Private Project'),
    (r'path \\private-server\share\Secret Folder\file.txt', 'private-server'),
    ('missing at /home/jimi/Private Project/db', 'Private Project'),
    ('missing at ./Private-Project/data', 'Private-Project'),
    ('missing at /秘密/私人的数据', '秘密'),
    ('token: '+('A'*50), 'A'*50),
    ('-----BEGIN PRIVATE KEY-----\nshortsecret\n-----END PRIVATE KEY-----', 'shortsecret'),
    ('-----BEGIN PRIVATE KEY-----\nshortsecret', 'shortsecret'),
    ('\x1b[31mPASSWORD=hidden-secret\x1b[0m', 'hidden-secret'),
])
def test_redaction_patterns(line, secret):
    redactor = s.Redactor()
    result = redactor.text(line)
    assert secret not in result and redactor.counts


def test_redaction_keeps_software_tracebacks_and_stable_path_aliases():
    r = s.Redactor(['private-machine', 'patient-007'])
    result = r.text('private-machine patient-007\nFile "/a/b/worker.py", line 40\n'
                    'File "/a/b/worker.py", line 45\nValueError: missing BUSCO database\n')
    assert result.count('[PATH_1]/worker.py') == 2
    assert 'line 40' in result and 'line 45' in result and 'ValueError: missing BUSCO database' in result
    assert 'private-machine' not in result and 'patient-007' not in result
    assert '2001:db8::1' not in r.text('address 2001:db8::1')


def test_tail_is_bounded_and_skips_clipped_or_oversized_lines(workspace, monkeypatch):
    store, jid = workspace
    path = store.log_path(jid)
    path.write_text('x'*200+'DO-NOT-INCLUDE-CLIPPED\n'+'short\n'*20+'ValueError: latest error\n')
    monkeypatch.setattr(s, 'MAX_LOG_BYTES', 200)
    monkeypatch.setattr(s, 'MAX_LOG_LINES', 4)
    text, info = s.log_tail(store, jid)
    assert 'DO-NOT-INCLUDE-CLIPPED' not in text
    assert text.endswith('ValueError: latest error') and len(text.splitlines()) == 4
    assert info['truncated']
    path.write_text('x'*150+'\nend\n')
    monkeypatch.setattr(s, 'MAX_LINE_BYTES', 80)
    text, info = s.log_tail(store, jid)
    assert '[OVERSIZED LOG LINE REMOVED]' in text and info['oversized_lines_removed'] == 1


@pytest.mark.parametrize('kind', ['file-link', 'directory-link', 'fifo', 'missing'])
def test_logs_cannot_follow_links_or_read_special_files(workspace, tmp_path, kind):
    store, jid = workspace
    path = store.log_path(jid)
    path.unlink()
    outside = tmp_path / 'outside'
    outside.mkdir()
    target = outside / path.name
    target.write_text('OUTSIDE SECRET')
    if kind == 'file-link': path.symlink_to(target)
    if kind == 'directory-link':
        path.parent.rmdir()
        path.parent.symlink_to(outside, target_is_directory=True)
    if kind == 'fifo': os.mkfifo(path)
    text, info = s.log_tail(store, jid)
    assert not text and info['status'] != 'included'
    assert 'OUTSIDE SECRET' not in s.preview(store, jid, True)['text']


def test_log_reader_refuses_replaced_workspace_directory(workspace, tmp_path):
    store, jid = workspace
    original = store.home.with_name('original-workspace')
    store.home.rename(original)
    outside = tmp_path / 'redirected-workspace'
    (outside / 'logs').mkdir(parents=True)
    (outside / 'logs' / (jid+'.log')).write_text('PRIVATE OUTSIDE CONTENT')
    store.home.symlink_to(outside, target_is_directory=True)
    text, info = s.log_tail(store, jid)
    assert not text and info['status'].startswith('unavailable')


def test_capacity_uses_only_allowlisted_cached_values(workspace, monkeypatch):
    store, jid = workspace
    hardware._CACHE[str(store.home)] = (0, {'checked_at': '2026-01-01T00:00:00+00:00', 'wsl': True,
        'cpu': {'model': 'private CPU note', 'logical': 16, 'physical': 8, 'available': 8},
        'memory': {'total_mb': 16000, 'available_mb': 8000}, 'disk': {'free_mb': 50000},
        'gpu': {'cards': [{'name': 'NVIDIA fixture GPU', 'memory_mb': 4000, 'serial': 'PRIVATE SERIAL'}],
                'driver': '570.1', 'cuda_driver_max': '12.8', 'cuda_toolkit': '12.6',
                'cuda_visible_devices': 'PRIVATE UUID', 'other_devices': ['PRIVATE PCI'], 'status': 'NVIDIA driver detected'}})
    def forbidden(*args, **kwargs): pytest.fail('No new capacity probes')
    monkeypatch.setattr(hardware, 'detect', forbidden)
    try:
        preview = s.preview(store, jid)
        data = metadata(preview)['capacity_recorded']
        assert data['checked_at'].startswith('2026-01-01') and data['cpu']['available'] == 8
        assert data['gpu']['cuda_toolkit'] == '12.6'
        assert 'PRIVATE' not in preview['text'] and 'private CPU' not in preview['text']
    finally:
        hardware._CACHE.pop(str(store.home), None)


def test_missing_run_is_unknown_and_never_borrows_active_commit(workspace):
    store, _ = workspace
    jid = store.submit('workflow', {'run_id': 'run-missing', 'action': 'run'})
    job = metadata(s.preview(store, jid))['selected_job']
    assert job['run_commit'] is None and job['pipeline'] is None and job['job_installation_recorded'] is None


def test_environment_setup_identifies_selected_installation_without_inventing_a_run(workspace):
    store, _ = workspace
    jid = store.submit('environments', {'installation': 'older', 'action': 'check', 'commit': 'a'*40})
    job = metadata(s.preview(store, jid))['selected_job']
    assert job['pipeline'] == 'flupop' and job['job_installation_recorded']['commit'] == 'a'*40
    assert job['job_requested_commit'] == 'a'*40 and job['run_commit'] is None


@pytest.mark.parametrize('payload', [{'job_id': []}, {'job_id': 'job-missing'}, {'include_log': 'yes'}, {'include_log': True}])
def test_invalid_preview_selection_is_rejected(workspace, payload):
    store, _ = workspace
    with pytest.raises(ValueError): dispatch(store, 'support_preview', payload)


def test_download_requires_review_and_contains_exact_edited_text(workspace, monkeypatch):
    store, jid = workspace
    monkeypatch.setattr('viralogix.updates.assert_current', lambda s: pytest.fail('Support remains read-only during an app update'))
    preview = dispatch(store, 'support_preview', {'job_id': jid, 'include_log': False})['support']
    edited = preview['text'].replace('Expected: ', 'Expected: installation should complete')+'\nUser-reviewed note: café\n'
    with pytest.raises(ValueError, match='Review the preview'):
        dispatch(store, 'download_support', {'text': edited})
    with pytest.raises(ValueError, match='Review the preview'):
        s.download(edited, 'true')
    text = dispatch(store, 'download_support', {'text': edited, 'reviewed': True})['download']
    assert text['text'] == edited and text['name'] == 'viralogix-support.txt'
    # Changing underlying jobs after review must not change either download.
    store.update_job(jid, status='succeeded')
    store.log_path(jid).write_text('NEW PRIVATE CONTENT')
    bundle = dispatch(store, 'download_support', {'text': edited, 'reviewed': True, 'format': 'zip'})['download']
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(bundle['base64']))) as archive:
        assert set(archive.namelist()) == {'viralogix-support.txt', 'SHA256SUMS', 'README.txt'}
        assert archive.read('viralogix-support.txt') == edited.encode()
        assert archive.read('SHA256SUMS').decode() == hashlib.sha256(edited.encode()).hexdigest()+'  viralogix-support.txt\n'
        assert all(b'NEW PRIVATE CONTENT' not in archive.read(name) for name in archive.namelist())
    assert not store.all('support_previews') and not store.all('support_bundles')


@pytest.mark.parametrize('text', ['', '   ', None, [], 'abc\0def', 'é'*65537])
def test_invalid_or_oversized_download_is_rejected(text):
    with pytest.raises(ValueError, match='128 KiB'): s.download(text, True)


def test_invalid_format_and_size_are_bounded(workspace, monkeypatch):
    with pytest.raises(ValueError, match='ZIP'): s.download('reviewed', True, [])
    store, jid = workspace
    monkeypatch.setattr(s, 'MAX_TEXT_BYTES', 10)
    with pytest.raises(ValueError, match='size limit'): s.preview(store, jid)


def test_request_deduplication_keeps_reviewed_text_and_no_workspace_exports(workspace):
    store, jid = workspace
    session = {}
    request = {'id': 'reviewed-download', 'kind': 'download_support', 'payload': {'text': 'Exact reviewed snapshot', 'reviewed': True}}
    first = handle_request(store, request, session)
    second = handle_request(store, request, session)
    assert first == second and first['download']['text'] == 'Exact reviewed snapshot'
    assert not (store.home / 'viralogix-support.txt').exists()
