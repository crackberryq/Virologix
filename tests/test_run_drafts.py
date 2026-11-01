from pathlib import Path
import subprocess
import pytest
from viralogix.store import Store
from viralogix.runs import register_folder, save_draft, start_run, archive_run, local_path
from viralogix.pipelines import open_result
from test_pipeline_manager import attached, wait


def test_sample_folder_and_draft_are_not_jobs(tmp_path):
    store=Store(tmp_path/'workspace')
    register_folder(store,{'sample':'S1','path':str(tmp_path)})
    with pytest.raises(ValueError,match='already registered'):
        register_folder(store,{'sample':'S1','path':str(tmp_path)})
    fasta=tmp_path/'consensus.fasta';fasta.write_text('fixture')
    table=tmp_path/'haplotypes.tsv';table.write_text('fixture')
    args={'label':'First run','sample':'S1','consensus':str(fasta),'haplotypes':str(table)}
    rid=save_draft(store,args)['run_id']
    assert not store.jobs()
    assert Store(store.home).get('cloud_runs',rid)['status']=='draft'
    save_draft(store,{**args,'run_id':rid,'label':'Edited'})
    assert store.get('cloud_runs',rid)['label']=='Edited'
    archive_run(store,{'run_id':rid,'archived':True})
    assert fasta.read_text()=='fixture'
    with pytest.raises(ValueError):save_draft(store,{**args,'run_id':rid})
    with pytest.raises(ValueError):start_run(store,{'run_id':rid},'start')
    archive_run(store,{'run_id':rid,'archived':False})
    assert not store.get('cloud_runs',rid)['archived']
    assert str(local_path(r'C:\data\sample'))=='/mnt/c/data/sample'


def test_queued_draft_is_immutable(tmp_path,monkeypatch):
    store=Store(tmp_path);attached(store)
    rid=save_draft(store,{'label':'Demo','demo':True})['run_id']
    monkeypatch.setattr(subprocess,'Popen',lambda *a,**k:None)
    start_run(store,{'run_id':rid},'start')
    assert store.get('cloud_runs',rid)['status']=='queued'
    with pytest.raises(ValueError):save_draft(store,{'run_id':rid,'label':'Overwrite','demo':True})
    with pytest.raises(ValueError):archive_run(store,{'run_id':rid,'archived':True})
    with pytest.raises(ValueError):start_run(store,{'run_id':rid},'again')
    assert len(store.jobs())==1


def test_saved_draft_execution_preserves_identity_and_history(tmp_path):
    store=Store(tmp_path);attached(store)
    rid=save_draft(store,{'label':'My demo','demo':True})['run_id']
    response=start_run(store,{'run_id':rid},'start')
    assert wait(store,response['job_id'])['status']=='succeeded'
    result=open_result(store,rid)
    assert result['run']['label']=='My demo'
    assert Path(result['run']['path']).name==rid
    with pytest.raises(ValueError):save_draft(store,{'run_id':rid,'label':'Changed','demo':True})
    archive_run(store,{'run_id':rid,'archived':True})
    assert open_result(store,rid)['html']==result['html']


def test_folder_browser_lists_local_paths_without_reading_contents(tmp_path):
    from viralogix.runs import browse_folder
    (tmp_path/'directory').mkdir()
    (tmp_path/'input.tsv').write_text('private test contents')
    listing=browse_folder({'path':str(tmp_path)})
    assert listing['folder']==str(tmp_path)
    assert [x['name'] for x in listing['entries']]==['directory','input.tsv']
    assert 'private test contents' not in str(listing)
