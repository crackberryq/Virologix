"""Manager integration: immutable drafts, revisions, menus and retained work."""
import base64
import io
from pathlib import Path
import zipfile
import pytest
from viralogix.store import Store
from viralogix import migration, runs, run_revisions, default_config, methods, maintenance
from viralogix.ui_backend import dispatch
from test_pipeline_manager import attached

@pytest.fixture
def workspace(tmp_path):
    store=Store(tmp_path/'workspace');old=attached(store);migration.migrate(store)
    sample=runs.register_sample(store,'user-label',str(Path(old['source'])/'examples'))
    run=runs.create_run(store,'flupop',sample,'synthetic_demo: true\n',1,1024)
    return store,run

def test_save_is_separate_from_execution_and_demo_label(workspace):
    store,run=workspace
    assert not store.jobs()
    assert run['sample']['id']=='user-label' and Path(run['output']).name=='DEMO'
    runs.check_run_files(run)
    with pytest.raises(ValueError,match='dry-run'):runs.validate_launch(store,run['id'],'run')
    assert 'viralogix_version' in run

def test_revision_preserves_parent_and_blocks_stale_editor(workspace):
    store,run=workspace
    editor=run_revisions.editor(store,run['id'])
    payload={'id':run['id'],'signature':editor['edit_run']['signature'],
             'config':{'tool':'flupop','text':run['submitted']},'cores':2,'memory_mb':2048}
    child=run_revisions.apply(store,payload)
    assert child['parent']==run['id'] and child['folder']!=run['folder']
    assert store.get('runs',run['id'])==run and child['cores']==2
    changed={**run,'cores':3};store.put('runs',run['id'],changed)
    with pytest.raises(ValueError,match='changed while'):run_revisions.apply(store,payload)

def test_staged_symlink_and_content_changes_block_execution(workspace,tmp_path):
    store,run=workspace;path=Path(run['folder'])/run['input_layout'][0]['path']
    raw=path.read_bytes();path.write_bytes(raw+b'changed')
    with pytest.raises(ValueError,match='Staged inputs changed'):runs.check_run_files(run)
    outside=tmp_path/'same-bytes';outside.write_bytes(raw);path.unlink();path.symlink_to(outside)
    with pytest.raises(ValueError,match='Staged inputs changed'):runs.check_run_files(run)

def test_archive_restore_and_sample_removal_retain_files(workspace):
    store,run=workspace
    runs.archive_runs(store,[run['id']],True)
    with pytest.raises(ValueError,match='Restore'):runs.validate_launch(store,run['id'],'dry-run')
    runs.archive_runs(store,[run['id']],False)
    runs.validate_launch(store,run['id'],'dry-run')
    runs.remove_sample(store,run['sample']['id'],run['sample'])
    assert Path(run['folder']).is_dir() and store.get('runs',run['id'])==run
    assert store.get('run_visibility',run['id'])['archived']

def test_defaults_optimistic_save_and_methods_exports(workspace):
    store,run=workspace;first=default_config.edit(store,'flupop',{})['default_config']
    saved=default_config.edit(store,'flupop',{'text':first['text'],'revision':first['revision']},save=True)
    assert saved['default_config_saved']
    store.put('configs','flupop','synthetic_demo: true\n')
    with pytest.raises(ValueError,match='changed while'):default_config.edit(store,'flupop',{'text':first['text'],'revision':first['revision']},save=True)
    for fmt in ('txt','md','html'):assert methods.download(store,run,fmt)['text']
    exported=methods.download(store,run,'zip')
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(exported['base64']))) as archive:
        assert {'config.yaml','methods-provenance.json','methods.html'} <= set(archive.namelist())
    assert store.get('runs',run['id'])==run

def test_environment_and_readonly_panels(workspace):
    store,run=workspace
    item=store.get('installs',run['installation'])
    assert maintenance.recipes(item)[0]['id']=='runner'
    for action,payload in [('inspect_run',{'id':run['id']}),('inspect_methods',{'id':run['id']}),
                           ('inspect_storage',{}),('inspect_compatibility',{}),('inspect_results',{'id':run['id']})]:
        assert dispatch(store,action,payload)
    assert not store.jobs()

def test_legacy_migration_is_idempotent(workspace):
    store,run=workspace
    store.put('cloud_runs','old-draft',{'id':'old-draft','sample':run['sample']['id'],'status':'draft','synthetic_demo':True})
    migration.migrate(store);migration.migrate(store)
    assert len(store.all('runs'))==2
    assert store.get('cloud_runs','old-draft') and store.get('legacy_migrations','old-draft')
