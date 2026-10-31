from pathlib import Path
from viralogix.store import Store
from viralogix.ui_backend import snapshot, handle_request, MAX_PREVIEW_BYTES
from viralogix.cfasta import parse, export_consensus


def test_registration_preserves_files_and_rejects_duplicate(tmp_path):
    store = Store(tmp_path / 'workspace')
    read = tmp_path / 'input.fastq'
    read.write_text('@fixture\nA\n+\nI\n')
    args = dict(sample='fixture', r1=str(read))
    assert handle_request(store, dict(id='1', action='register', args=args))['ok']
    assert read.read_text() == '@fixture\nA\n+\nI\n'
    assert snapshot(store)['samples'][0]['r1'] == str(read)
    assert not handle_request(store, dict(id='2', action='register', args=args))['ok']
    assert len(store.all('samples')) == 1
    assert store.jobs() == []


def test_inspection_uses_existing_export(tmp_path):
    store = Store(tmp_path)
    text = (Path(__file__).parents[1] / 'examples/demo.cfasta').read_text()
    result = handle_request(store, dict(id='preview', action='inspect', args=dict(text=text, name='demo.cfasta')))
    assert result['ok'] and result['id'] == 'preview'
    assert result['consensus'] == export_consensus(parse(text))
    assert result['filename'] == 'demo.consensus.fasta'
    assert store.jobs() == []
    assert not handle_request(store, dict(action='inspect', args=dict(text='invalid')))['ok']
    assert not handle_request(store, dict(action='inspect', args=dict(text='a'*(MAX_PREVIEW_BYTES+1))))['ok']


def test_browser_restart_unavailable_outside_desktop(tmp_path, monkeypatch):
    monkeypatch.delenv('VIRALOGIX_DESKTOP_SESSION', raising=False)
    assert not handle_request(Store(tmp_path), dict(action='restart-as-browser'))['ok']
