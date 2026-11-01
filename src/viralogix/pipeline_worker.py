"""Background manager worker. All analysis runs in the external FluPop process."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.request import Request, urlopen
from zipfile import ZipFile
from .store import Store, now
from .pipelines import REPOSITORY, REPORT_FILES


def fetch(url):
    with urlopen(Request(url,headers={'User-Agent':'Virologix','Accept':'application/vnd.github+json'}),timeout=120) as response:
        data=response.read(100*1024*1024+1)
    if len(data)>100*1024*1024:raise ValueError('Source download exceeds 100 MiB.')
    return data


def checked_manifest(source):
    data=json.loads((source/'pipeline.json').read_text())
    if data.get('id')!='flupop' or data.get('engine')!='snakemake' or data.get('snakefile')!='workflow/Snakefile':
        raise ValueError('Unsupported FluPop manifest.')
    if not re.fullmatch(r'\d+\.\d+\.\d+',str(data.get('engine_version',''))):
        raise ValueError('FluPop must declare an exact Snakemake version.')
    if not (source/'workflow/Snakefile').is_file():raise ValueError('FluPop Snakefile is missing.')
    return data


def extract_source(archive,destination):
    """Accept only ordinary files underneath one ZIP root; no links or traversal."""
    with ZipFile(archive) as z:
        if sum(x.file_size for x in z.infolist())>200*1024*1024:raise ValueError('Source archive is too large.')
        roots=set()
        for info in z.infolist():
            parts=PurePosixPath(info.filename).parts
            if not parts or info.filename.startswith('/') or '..' in parts or '\\' in info.filename:
                raise ValueError('Unsafe source archive path.')
            if (info.external_attr>>16)&0o170000 == 0o120000:raise ValueError('Source symlinks are not supported.')
            roots.add(parts[0])
        if len(roots)!=1:raise ValueError('Expected one source archive root.')
        destination.mkdir(parents=True,exist_ok=False)
        for info in z.infolist():
            parts=PurePosixPath(info.filename).parts[1:]
            if not parts:continue
            target=destination.joinpath(*parts)
            if info.is_dir():target.mkdir(parents=True,exist_ok=True)
            else:
                target.parent.mkdir(parents=True,exist_ok=True)
                with z.open(info) as src,target.open('wb') as dst:shutil.copyfileobj(src,dst)


def run_command(argv,cwd=None):
    print('Running: '+subprocess.list2cmdline([str(a) for a in argv]),flush=True)
    subprocess.run([str(a) for a in argv],cwd=cwd,check=True,stdin=subprocess.DEVNULL)


def find_conda():
    candidates=[os.environ.get('CONDA_EXE'),shutil.which('conda')]
    for root in ('miniconda3','miniforge3','anaconda3','.local/share/viralogix/conda','.local/share/bactomics/conda'):
        candidates.append(str(Path.home()/root/'bin/conda'))
    candidates.extend(str(parent/'bin/conda') for parent in Path(sys.executable).resolve().parents)
    for item in candidates:
        if item and Path(item).is_file() and os.access(item,os.X_OK):return item
    raise ValueError('Conda was not found. Rerun Virologix Setup to repair the application prerequisites.')


def install(store,jid):
    sha=json.loads(fetch(f'https://api.github.com/repos/{REPOSITORY}/commits/main'))['sha']
    if not re.fullmatch('[0-9a-f]{40}',sha):raise ValueError('Invalid source revision.')
    current=store.get('pipelines','flupop')
    if current and current['revision']==sha and Path(current['python']).is_file():
        try:
            run_command([current['python'],'-c',f'import snakemake; assert snakemake.__version__ == {current["engine_version"]!r}'])
            run_command([current['python'],'-m','pip','check'])
            checked_manifest(Path(current['source']))
            print('FluPop is already installed and current.',flush=True)
            return
        except (OSError,ValueError,subprocess.CalledProcessError):
            print('Existing installation needs repair; preparing a separate replacement.',flush=True)
    source=store.home/'sources'/'flupop'/f'{sha[:12]}-{jid}'
    prefix=store.home/'envs'/'flupop'/f'{sha[:12]}-{jid}'
    conda=find_conda()
    raw=fetch(f'https://codeload.github.com/{REPOSITORY}/zip/{sha}')
    with tempfile.TemporaryDirectory() as temp:
        archive=Path(temp)/'source.zip';archive.write_bytes(raw)
        extract_source(archive,source)
    manifest=checked_manifest(source)
    prefix.parent.mkdir(parents=True,exist_ok=True)
    run_command([conda,'create','--yes','--prefix',prefix,'--no-default-packages','--override-channels','--channel','conda-forge','python=3.12','pip'])
    python=prefix/'bin/python'
    run_command([python,'-m','pip','install',f'snakemake=={manifest["engine_version"]}',str(source)])
    run_command([python,'-m','pip','check'])
    run_command([python,'-c',f'import snakemake; assert snakemake.__version__ == {manifest["engine_version"]!r}'])
    record={'version':manifest['version'],'revision':sha,'source':str(source),'python':str(python),
            'engine_version':manifest['engine_version'],'installed':now(),
            'source_sha256':hashlib.sha256(raw).hexdigest()}
    (prefix/'.virologix-flupop').write_text(json.dumps(record,indent=2))
    store.put('pipelines','flupop',record)
    print('FluPop ready. Manager environment and previous installations were preserved.',flush=True)


def execute_run(store,jid,payload):
    if 'resume' in payload:
        run=payload['resume'];folder=Path(run['path']);installed=run['installation']
        run={**run,'status':'running','job_id':jid}
    else:
        installed=payload['installation'];sample=payload['sample']
        folder=store.home/'runs'/jid;folder.mkdir(exist_ok=False)
        source=Path(installed['source'])
        if payload['demo']:
            inputs={k:str(source/'examples'/n) for k,n in [('consensus','consensus.fasta'),('haplotypes','haplotypes.tsv'),('evidence','evidence.json')]}
        else:
            incoming=folder/'inputs';incoming.mkdir()
            inputs={}
            for key,text in payload['inputs'].items():
                if text:
                    path=incoming/(key+{'consensus':'.fasta','haplotypes':'.tsv','evidence':'.json'}[key])
                    path.write_text(text,encoding='utf-8');inputs[key]=str(path)
        config={'output_dir':str(folder/'outputs'),'synthetic_demo':payload['demo'],'samples':{sample:inputs}}
        (folder/'config.json').write_text(json.dumps(config,indent=2))
        run={'id':jid,'pipeline':'flupop','sample':sample,'created':now(),'synthetic_demo':payload['demo'],
             'status':'running','path':str(folder),'report_path':str(folder/'outputs'/sample/'report'),
             'installation':installed,'job_id':jid}
    store.put('cloud_runs',run['id'],run)
    try:
        argv=[installed['python'],'-m','snakemake','--snakefile',str(Path(installed['source'])/'workflow/Snakefile'),
              '--directory',str(folder),'--configfile',str(folder/'config.json'),'--cores','1','--rerun-incomplete']
        run_command(argv,cwd=folder)
        report=Path(run['report_path'])
        if not all((report/n).is_file() for n in REPORT_FILES):raise ValueError('FluPop exited without all expected outputs.')
        run.update(status='succeeded',finished=now(),error=None)
    except Exception as exc:
        run.update(status='failed',finished=now(),error=str(exc))
        raise
    finally:store.put('cloud_runs',run['id'],run)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--home',required=True);parser.add_argument('--job',required=True)
    args=parser.parse_args();store=Store(args.home);job=store.job(args.job)
    if not job or job['status']!='queued':return
    with store.connect() as db:
        changed=db.execute("UPDATE jobs SET status='running',started=? WHERE id=? AND status='queued'",(now(),args.job)).rowcount
    if not changed:return
    try:
        if job['kind']=='flupop_install':install(store,args.job)
        elif job['kind']=='flupop_run':execute_run(store,args.job,job['payload'])
        else:raise ValueError('Unknown pipeline job.')
        status,error='succeeded',None
    except Exception as exc:
        import traceback;traceback.print_exc()
        status,error='failed',str(exc)
    with store.connect() as db:
        db.execute('UPDATE jobs SET status=?,finished=?,error=? WHERE id=?',(status,now(),error,args.job))
    if status=='failed':raise SystemExit(1)

if __name__=='__main__':main()
