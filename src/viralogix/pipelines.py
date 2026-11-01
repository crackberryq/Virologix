"""Manager-only installation, process launch and result access for FluPop."""
import base64
from io import BytesIO
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from zipfile import ZipFile, ZIP_DEFLATED
from .store import identifier, now

REPOSITORY = 'crackberryq/Viromics_FluPop'
MAX_INPUT = 10 * 1024 * 1024
REPORT_FILES = ('population.cfasta','consensus.fasta','viral-cloud.html','viral-cloud.json','evidence.json','manifest.json')


def text_input(value):
    if not isinstance(value,str) or len(value.encode('utf-8')) > MAX_INPUT:
        raise ValueError('Each input must be UTF-8 text no larger than 10 MiB.')
    return value


def active_jobs(store):
    return [j for j in store.jobs() if j['kind'].startswith('flupop_') and j['status'] in ('queued','running')]


def enqueue(store,kind,payload,request_id):
    """Serialize operations and reject replayed submissions across UI sessions."""
    jid=identifier('flupop')
    payload={**payload,'request_id':request_id}
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if request_id:
            previous=db.execute("SELECT id FROM jobs WHERE json_extract(payload,'$.request_id')=?",(request_id,)).fetchone()
            if previous:return previous[0]
        if db.execute("SELECT 1 FROM jobs WHERE status IN ('queued','running')").fetchone():
            raise ValueError('A task is already active. Wait for it to finish before starting another.')
        rid=payload.get('run_id') or payload.get('resume',{}).get('id')
        if rid:
            row=db.execute("SELECT body FROM items WHERE kind='cloud_runs' AND id=?",(rid,)).fetchone()
            run=json.loads(row[0]) if row else {}
            expected='failed' if 'resume' in payload else 'draft'
            if run.get('status')!=expected or run.get('archived'):
                raise ValueError('The saved run changed. Refresh before starting it.')
            if payload.get('draft') and payload['draft']!=run:
                raise ValueError('The draft changed while preparing inputs. Refresh and start again.')
            run.update(status='queued',job_id=jid)
            db.execute("UPDATE items SET body=? WHERE kind='cloud_runs' AND id=?",(json.dumps(run),rid))
        db.execute('INSERT INTO jobs(id,kind,payload,status,created) VALUES(?,?,?,?,?)',
                   (jid,kind,json.dumps(payload),'queued',now()))
    try:
        with (store.home/'logs'/f'{jid}.log').open('ab') as log:
            subprocess.Popen([sys.executable,'-m','viralogix.pipeline_worker','--home',str(store.home),'--job',jid],
                             stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,
                             cwd=store.home,start_new_session=True)
    except OSError as exc:
        with store.connect() as db:
            db.execute("UPDATE jobs SET status='failed',finished=?,error=? WHERE id=?",(now(),str(exc),jid))
        if rid:
            run=store.get('cloud_runs',rid)
            run.update(status=expected,error=str(exc))
            store.put('cloud_runs',rid,run)
        raise
    return jid


def installation(store):
    record=store.get('pipelines','flupop')
    if record and not (Path(record['python']).is_file() and (Path(record['source'])/'workflow/Snakefile').is_file()):
        return {**record,'ready':False}
    return {**record,'ready':True} if record else {'ready':False}


def queue_run(store,args,request_id,demo=False):
    from .updates import assert_current
    assert_current(store)
    installed=installation(store)
    if not installed['ready']:raise ValueError('Install FluPop from Install & update before starting a run.')
    sample='DEMO' if demo else args.get('sample','')
    if not isinstance(sample,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*',sample):
        raise ValueError('Sample ID must start with a letter or digit and use letters, digits, dots, underscores or hyphens.')
    payload={'sample':sample,'demo':demo,'installation':installed}
    if not demo:
        payload['inputs']={name:text_input(args.get(name,'')) for name in ('consensus','haplotypes','evidence')}
        if not payload['inputs']['consensus'] or not payload['inputs']['haplotypes']:
            raise ValueError('Select consensus FASTA and reviewed haplotype TSV files.')
    jid=enqueue(store,'flupop_run',payload,request_id)
    return {'message':'FluPop run started. Progress and logs appear below.','job_id':jid}


def task_snapshot(store):
    tasks=[]
    for j in store.jobs():
        if not (j['kind'].startswith('flupop_') or j['kind']=='app_update'):continue
        path=store.home/'logs'/f'{j["id"]}.log'
        tail=''
        if path.is_file():
            with path.open('rb') as stream:
                stream.seek(max(0,path.stat().st_size-6000))
                tail=stream.read().decode('utf-8',errors='replace')
        tasks.append({k:j[k] for k in ('id','kind','status','created','error') } | {'log':tail})

    return tasks


def open_result(store,run_id):
    run=store.get('cloud_runs',str(run_id))
    if not run:raise ValueError('Saved run not found.')
    if run.get('status','succeeded')!='succeeded':raise ValueError('This run has not completed successfully.')
    base=(store.home/'runs').resolve()
    folder=Path(run.get('report_path') or base/run['id']).resolve()
    if not folder.is_relative_to(base):raise ValueError('Report path is outside this workspace.')
    if any(not (folder/name).resolve().is_relative_to(base) for name in REPORT_FILES):
        raise ValueError('Report file is outside this workspace.')
    if sum((folder/name).stat().st_size for name in REPORT_FILES)>100*1024*1024:
        raise ValueError('Report bundle exceeds the interactive limit. Open its saved folder instead.')
    buffer=BytesIO()
    with ZipFile(buffer,'w',ZIP_DEFLATED) as archive:
        for name in REPORT_FILES:archive.writestr(name,(folder/name).read_bytes())
    return {'run':run,'html':(folder/'viral-cloud.html').read_text(encoding='utf-8'),
            'archive':base64.b64encode(buffer.getvalue()).decode('ascii'),
            'message':'Viral Cloud report opened.'}


def handle_pipeline(store,action,args,request_id):
    if action!='cloud-open':
        from .updates import assert_current
        assert_current(store)
    if action=='flupop-install':
        jid=enqueue(store,'flupop_install',{},request_id)
        return {'message':'FluPop installation started in its own environment. See progress below.','job_id':jid}
    if action=='cloud-open':return open_result(store,args.get('run_id',''))
    if action=='flupop-resume':
        run=store.get('cloud_runs',str(args.get('run_id','')))
        if not run or run.get('pipeline')!='flupop' or run.get('status')!='failed':
            raise ValueError('Only failed FluPop runs can be resumed.')
        if not run.get('path') or not (Path(run['path'])/'config.json').is_file():
            raise ValueError('This run stopped before setup finished. Create a new draft from its saved settings.')
        jid=enqueue(store,'flupop_run',{'resume':run},request_id)
        return {'message':'Resuming FluPop with its original inputs and environment.','job_id':jid}
    return queue_run(store,args,request_id,demo=action=='cloud-demo')
