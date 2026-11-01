"""Saved manager drafts and local input references; execution stays external."""
import json
from pathlib import Path
import re
from .store import identifier, now
from .pipelines import enqueue, installation, text_input


def local_path(value):
    value = str(value).strip()
    if re.match(r'^[A-Za-z]:[\\/]', value):
        value = '/mnt/' + value[0].lower() + '/' + value[3:].replace('\\', '/')
    return Path(value).expanduser().resolve()


def register_folder(store, args):
    sample = str(args.get('sample', '')).strip()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', sample):
        raise ValueError('Use a sample ID containing letters, digits, dots, underscores or hyphens.')
    if not args.get('path'):raise ValueError('Choose a sample folder.')
    path = local_path(args['path'])
    if not path.is_dir():raise ValueError('Sample folder does not exist on this computer.')
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute("SELECT 1 FROM items WHERE kind='samples' AND id=?", (sample,)).fetchone():
            raise ValueError('This sample ID is already registered.')
        record = dict(id=sample, path=str(path), created=now(), status='registered')
        db.execute('INSERT INTO items VALUES(?,?,?)', ('samples',sample,json.dumps(record)))
    return {'message':'Sample registered. Input files remain in their original locations.'}


def save_draft(store, args):
    from .updates import assert_current
    assert_current(store)
    demo = args.get('demo') is True
    sample = 'DEMO' if demo else str(args.get('sample', ''))
    if not demo and not store.get('samples', sample):raise ValueError('Choose a registered sample first.')
    label = str(args.get('label','')).strip()
    if not label or len(label)>160:raise ValueError('Enter a run name of 1–160 characters.')
    inputs = {k:str(args.get(k,'')).strip() for k in ('consensus','haplotypes','evidence')}
    if not demo and not all(inputs[k] for k in ('consensus','haplotypes')):
        raise ValueError('Choose consensus FASTA and reviewed haplotype TSV paths.')
    for key,value in inputs.items():
        if value:
            path=local_path(value)
            if not path.is_file():raise ValueError(f'{key}: file does not exist.')
            inputs[key]=str(path)
    rid = str(args.get('run_id') or identifier('run'))
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute("SELECT body FROM items WHERE kind='cloud_runs' AND id=?",(rid,)).fetchone()
        prior=json.loads(row[0]) if row else {}
        if args.get('run_id') and not prior:raise ValueError('Run not found.')
        if prior and (prior.get('status')!='draft' or prior.get('archived')):
            raise ValueError('Only current drafts can be edited. Create a new draft to preserve this run.')
        record={**prior,'id':rid,'label':label,'pipeline':'flupop','sample':sample,'status':'draft',
                'synthetic_demo':demo,'input_paths':inputs,'created':prior.get('created',now()),'updated':now()}
        db.execute('INSERT INTO items VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body',
                   ('cloud_runs',rid,json.dumps(record)))
    return {'message':'Run draft saved. No job has been started.','run_id':rid}


def start_run(store, args, request_id):
    from .updates import assert_current
    assert_current(store)
    run=store.get('cloud_runs',str(args.get('run_id','')))
    if not run or run.get('status')!='draft' or run.get('archived'):raise ValueError('Choose a current saved draft.')
    installed=installation(store)
    if not installed['ready']:raise ValueError('Install FluPop from Install & update first.')
    payload={'run_id':run['id'],'draft':run,'sample':run['sample'],'demo':run['synthetic_demo'],'installation':installed}
    if not payload['demo']:
        payload['inputs']={}
        for key,value in run['input_paths'].items():
            if value:
                with Path(value).open('rb') as stream:data=stream.read(10*1024*1024+1)
                payload['inputs'][key]=text_input(data.decode('utf-8'))
    jid=enqueue(store,'flupop_run',payload,request_id)
    return {'message':'Run queued. Follow it in Jobs & progress.','job_id':jid,'run_id':run['id']}


def archive_run(store,args):
    rid=str(args.get('run_id',''))
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute("SELECT body FROM items WHERE kind='cloud_runs' AND id=?",(rid,)).fetchone()
        if not row:raise ValueError('Run not found.')
        run=json.loads(row[0])
        if run.get('status') in ('running','queued'):raise ValueError('Wait for the active run to finish before archiving.')
        run['archived']=args.get('archived') is True
        db.execute("UPDATE items SET body=? WHERE kind='cloud_runs' AND id=?",(json.dumps(run),rid))
    return {'message':'Run archived. Files and reports are kept.' if run['archived'] else 'Run restored.'}


def browse_folder(args):
    path=local_path(args.get('path') or Path.home())
    if path.is_file():path=path.parent
    if not path.is_dir():raise ValueError('Choose an existing folder.')
    entries=[]
    for child in path.iterdir():
        if child.name.startswith('.'):continue
        try:
            if child.is_dir() or child.is_file():
                entries.append({'name':child.name,'path':str(child),'directory':child.is_dir()})
        except OSError:continue
    entries.sort(key=lambda x:(not x['directory'],x['name'].casefold()))
    return {'folder':str(path),'parent':str(path.parent),'entries':entries[:500],
            'truncated':len(entries)>500}
