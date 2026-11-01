import base64
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import time
from zipfile import ZipFile
import pytest
from viralogix.store import Store
from viralogix.pipelines import enqueue, handle_pipeline, open_result, installation, REPORT_FILES
from viralogix.pipeline_worker import extract_source, install


def attached(store):
    source=os.environ.get('FLUPOP_TEST_SOURCE')
    python=os.environ.get('FLUPOP_TEST_PYTHON')
    if not source or not python:pytest.skip('External FluPop integration fixture not configured')
    record={'source':str(Path(source).resolve()),'python':str(Path(python).absolute()),
            'revision':'180d6a6f9759c1a078e8ea8337025f1d3ee7a0d9','version':'0.1.0a1','engine_version':'9.27.0'}
    store.put('pipelines','flupop',record)
    return record


def wait(store,jid):
    end=time.monotonic()+90
    while time.monotonic()<end:
        job=store.job(jid)
        if job['status'] not in ('queued','running'):return job
        time.sleep(.2)
    pytest.fail('Worker did not finish')


def test_legacy_report_and_safe_paths(tmp_path):
    store=Store(tmp_path);folder=store.home/'runs'/'legacy';folder.mkdir()
    for name in REPORT_FILES:(folder/name).write_text('<h1>Legacy report</h1>')
    store.put('cloud_runs','legacy',{'id':'legacy','sample':'OLD'})
    result=open_result(store,'legacy')
    assert 'Legacy report' in result['html']
    with ZipFile(BytesIO(base64.b64decode(result['archive']))) as z:assert set(z.namelist())==set(REPORT_FILES)
    store.put('cloud_runs','bad',{'id':'bad','report_path':str(tmp_path.parent)})
    with pytest.raises(ValueError):open_result(store,'bad')


def test_missing_install_and_input_validation(tmp_path):
    store=Store(tmp_path)
    assert not installation(store)['ready']
    with pytest.raises(ValueError,match='Install FluPop'):handle_pipeline(store,'cloud-demo',{},'request')


def test_duplicate_requests_and_active_lock(tmp_path,monkeypatch):
    store=Store(tmp_path)
    monkeypatch.setattr(subprocess,'Popen',lambda *a,**k:None)
    jid=enqueue(store,'flupop_install',{},'req')
    assert enqueue(store,'flupop_install',{},'req')==jid
    with pytest.raises(ValueError,match='already active'):enqueue(store,'flupop_install',{},'other')
    assert len(store.jobs())==1


def test_archive_traversal_rejected(tmp_path):
    path=tmp_path/'bad.zip'
    with ZipFile(path,'w') as z:z.writestr('root/../../escape','bad')
    with pytest.raises(ValueError):extract_source(path,tmp_path/'source')
    assert not (tmp_path/'source').exists()


def test_install_commits_only_after_environment_checks(tmp_path,monkeypatch):
    from viralogix import pipeline_worker as worker
    store=Store(tmp_path);sha='a'*40
    buffer=BytesIO()
    with ZipFile(buffer,'w') as z:
        z.writestr('root/pipeline.json',json.dumps({'id':'flupop','version':'0.1.0a1','engine':'snakemake','engine_version':'9.27.0','snakefile':'workflow/Snakefile'}))
        z.writestr('root/workflow/Snakefile','rule all:\n    input: []\n')
    monkeypatch.setattr(worker,'fetch',lambda url: json.dumps({'sha':sha}).encode() if '/commits/' in url else buffer.getvalue())
    monkeypatch.setattr(worker,'find_conda',lambda:'/test/conda')
    calls=[]
    def command(argv,cwd=None):
        calls.append([str(x) for x in argv])
        if 'create' in argv:
            prefix=Path(argv[argv.index('--prefix')+1]);(prefix/'bin').mkdir(parents=True)
            (prefix/'bin/python').touch()
    monkeypatch.setattr(worker,'run_command',command)
    install(store,'one')
    record=store.get('pipelines','flupop')
    assert record['revision']==sha
    assert calls[0][0]=='/test/conda' and '--prefix' in calls[0]
    assert all('viromics' not in ' '.join(c) for c in calls)
    assert any('snakemake==9.27.0' in c for c in calls)
    monkeypatch.setattr(worker,'run_command',lambda *a,**k: (_ for _ in ()).throw(OSError('simulated failure')))
    with pytest.raises(OSError):install(store,'two')
    assert store.get('pipelines','flupop')==record


def test_external_snakemake_demo_and_resume(tmp_path):
    store=Store(tmp_path);record=attached(store)
    response=handle_pipeline(store,'cloud-demo',{},'actual-demo')
    job=wait(store,response['job_id'])
    assert job['status']=='succeeded',job.get('error')
    result=open_result(store,job['id'])
    assert 'SYNTHETIC' in result['html']
    run=result['run']
    assert run['installation']['python']==record['python']
    assert (Path(run['path'])/'outputs/DEMO/benchmarks/report.tsv').is_file()
    config=json.loads((Path(run['path'])/'config.json').read_text())
    assert config['synthetic_demo'] is True
    # Resume a recorded failure with unchanged original environment and inputs.
    run['status']='failed';store.put('cloud_runs',run['id'],run)
    result=handle_pipeline(store,'flupop-resume',{'run_id':run['id']},'resume')
    assert wait(store,result['job_id'])['status']=='succeeded'
    assert len(store.all('cloud_runs'))==1


def test_invalid_supplied_records_fail_in_pipeline(tmp_path):
    store=Store(tmp_path);attached(store)
    args={'sample':'BROKEN','consensus':'>SEG\nACGT\n','haplotypes':'invalid\n','evidence':''}
    response=handle_pipeline(store,'cloud-package',args,'invalid')
    job=wait(store,response['job_id'])
    assert job['status']=='failed'
    assert store.get('cloud_runs',job['id'])['status']=='failed'
    with pytest.raises(ValueError):open_result(store,job['id'])


def test_conda_discovery_matches_desktop_installer(tmp_path,monkeypatch):
    from viralogix import pipeline_worker as worker
    monkeypatch.delenv('CONDA_EXE',raising=False)
    monkeypatch.setattr(worker.shutil,'which',lambda name:None)
    monkeypatch.setattr(Path,'home',lambda:tmp_path)
    conda=tmp_path/'.local/share/viralogix/conda/bin/conda'
    conda.parent.mkdir(parents=True);conda.write_text('#!/bin/sh\n');conda.chmod(0o755)
    assert worker.find_conda()==str(conda)


def test_download_does_not_receive_api_token(monkeypatch):
    from viralogix import pipeline_worker as worker
    monkeypatch.setenv('GH_TOKEN','test-only-placeholder')
    seen=[]
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,n):return b'{}'
    def open_(request,timeout):seen.append(request);return Response()
    monkeypatch.setattr(worker,'urlopen',open_)
    worker.fetch('https://api.github.com/repos/crackberryq/Viromics_FluPop/commits/main')
    worker.fetch('https://codeload.github.com/crackberryq/Viromics_FluPop/zip/'+'a'*40)
    assert seen[0].get_header('Authorization')=='Bearer test-only-placeholder'
    assert seen[1].get_header('Authorization') is None
