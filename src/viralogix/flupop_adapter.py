"""FluPop boundary for the shared manager. No sequence processing occurs here."""
from pathlib import Path
import copy
import hashlib
import json
import shutil
import sys
import yaml
from .store import identifier, now
from . import __version__


def prepare_controller(ctx, record, repair=False):
    from .engine import find_conda, bootstrap, check_controller, controller_key
    from .controllers import controller_requirements
    source=Path(record['source'])
    requirements=controller_requirements((source/'environment.yml').read_bytes())
    conda=find_conda(ctx.store)
    if not conda:
        bootstrap(ctx);conda=find_conda(ctx.store)
    digest=controller_key('flupop',(source/'environment.yml').read_bytes())
    # Pipeline code is installed in the runner: do not share across source revisions.
    prefix=ctx.store.home/'controllers'/('flupop-'+digest+'-'+record['version']['commit'][:12])
    if repair:prefix=Path(str(prefix)+'-'+ctx.job['id'])
    if not prefix.exists():
        ctx.command([conda,'create','--yes','--prefix',str(prefix),'--override-channels','-c','conda-forge',
                     'python='+requirements['python'],'pip','--no-default-packages'])
        ctx.command([str(prefix/'bin/python'),'-m','pip','install','snakemake=='+requirements['snakemake'],str(source)])
    check_controller(ctx,conda,prefix,'flupop',requirements)
    ctx.command([str(prefix/'bin/python'),'-c','import flupop; print("FluPop import verified")'])
    record.update(controller=str(prefix),conda=conda,controller_digest=digest,controller_origin='managed',
                  ready=True,checked=now(),controller_requirements=requirements,setup_completed=now(),setup_phase='complete')
    ctx.store.put('installs',record['id'],record)
    ctx.store.activate_installation(record['id'])


def create_run(store,tool,sample,config_text,cores=4,memory_mb=16000,parent=None,label=None,installation=None,expected_inputs=None,register=True):
    from .runs import parse_config,snapshot_files,tree_digest
    from .catalog import supported
    if tool!='flupop':raise ValueError('Choose FluPop.')
    install_id=installation or store.get('settings','active-flupop')
    installed=store.get('installs',install_id)
    if not installed or not installed.get('ready') or not supported(tool,installed['version']['commit'],store):
        raise ValueError('Set up a supported pipeline runner first.')
    cfg=copy.deepcopy(parse_config(config_text))
    from .run_config import validate
    validate(tool,config_text)
    cores,memory_mb=int(cores),int(memory_mb)
    if not 1<=cores<=512 or not 512<=memory_mb<=2000000:raise ValueError('CPU or memory budget is outside the supported range.')
    source=Path(installed['source'])
    folder=store.home/'runs'/identifier('run');folder.mkdir()
    try:
        shutil.copytree(source,folder/'workflow',ignore=shutil.ignore_patterns('.git','.snakemake','__pycache__','*.pyc','*.egg-info'))
        input_root=source/'examples' if cfg.get('synthetic_demo') else Path(sample['path'])
        paths={}
        for key,default in [('consensus','consensus.fasta'),('haplotypes','haplotypes.tsv'),('evidence','evidence.json')]:
            value=default if cfg.get('synthetic_demo') else cfg.get('inputs',{}).get(key,default if key!='evidence' else '')
            if not value:continue
            path=(input_root/value).expanduser().resolve()
            if not path.is_file() or not path.stat().st_size:raise ValueError(f'{key}: missing or empty file: {path}')
            if path.stat().st_size>10*1024*1024:raise ValueError('Each input must be no larger than 10 MiB.')
            paths[key]=path
        if not {'consensus','haplotypes'}<=paths.keys():raise ValueError('Consensus and reviewed record files are required.')
        inputs=snapshot_files(paths.values())
        if expected_inputs is not None and inputs!=expected_inputs:raise ValueError('Original inputs differ from the parent run. Create a new run for changed inputs.')
        incoming=folder/'inputs';incoming.mkdir()
        staged={}
        for key,path in paths.items():
            target=incoming/(key+path.suffix);shutil.copyfile(path,target);staged[key]=str(target)
        frozen=[{'path':str(Path(v).relative_to(folder)),'sha256':hashlib.sha256(Path(v).read_bytes()).hexdigest()} for v in staged.values()]
        pipeline_sample = 'DEMO' if cfg.get('synthetic_demo') else sample['id']
        cfg.update(samples={pipeline_sample:staged},output_dir=str(folder/'outputs'),threads=cores,memory_mb=memory_mb)
        text=yaml.safe_dump(cfg,sort_keys=False)
        (folder/'config.yaml').write_text(text);(folder/'submitted.yaml').write_text(config_text)
        (folder/'samples.tsv').write_text('sample_id\tpath\n'+sample['id']+'\t'+sample['path']+'\n')
        run={'id':folder.name,'tool':tool,'sample':copy.deepcopy(sample),'folder':str(folder),'output':str(folder/'outputs'/pipeline_sample),
             'installation':install_id,'controller':installed['controller'],'commit':installed['version']['commit'],
             'rule_cache':installed.get('rule_cache') or str(store.home/'envs'/tool),'config':text,'submitted':config_text,
             'config_sha256':hashlib.sha256(text.encode()).hexdigest(),'workflow_sha256':tree_digest(folder/'workflow'),
             'inputs':inputs,'input_layout':frozen,'cores':cores,'memory_mb':memory_mb,'parent':parent,
             'label':label or sample['id'],'viralogix_version':__version__,'created':now(),'dry_run_ok':False,'reuse':'independent outputs; frozen input copies'}
        (folder/'viralogix-run.json').write_text(json.dumps(run,indent=2))
        if register:store.register_run(run)
        return run
    except BaseException:
        shutil.rmtree(folder);raise


def check_run_files(run):
    from .runs import check_inputs
    from .variants import verify
    verify(run,full=False)
    folder=Path(run['folder'])
    if hashlib.sha256((folder/'config.yaml').read_bytes()).hexdigest()!=run['config_sha256']:
        raise ValueError('Saved configuration changed. Create a new draft.')
    check_inputs(run)
    for row in run['input_layout']:
        original=folder/row['path']
        linked=any(p.is_symlink() for p in (original,*original.parents))
        path=original.resolve()
        if not path.is_relative_to(folder.resolve()) or linked or hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:
            raise ValueError('Staged inputs changed. Create a new draft.')


def command(store,run,action):
    from .runs import current_controller
    folder=Path(run['folder'])
    argv=[str(Path(current_controller(store,run))/'bin/python'),'-m','snakemake',
          '--snakefile',str(folder/'workflow/workflow/Snakefile'),'--directory',str(folder),
          '--configfile',str(folder/'config.yaml'),'--cores',str(run['cores']),
          '--resources','mem_mb='+str(run['memory_mb']),'--rerun-incomplete']
    if action=='dry-run':argv.append('--dry-run')
    elif action=='check-environments':argv.append('--list-conda-envs')
    elif action=='prepare':argv.append('--conda-create-envs-only')
    elif action!='run':raise ValueError('Unsupported workflow action.')
    return argv


def execute_workflow(ctx):
    from .runs import validate_launch,current_controller,tree_digest
    from . import results,methods
    store=ctx.store;action=ctx.job['payload']['action']
    run=validate_launch(store,ctx.job['payload']['run_id'],action,check_busy=False)
    if tree_digest(Path(run['folder'])/'workflow')!=run['workflow_sha256']:raise ValueError('Saved workflow source changed.')
    if action in ('prepare','check-environments'):
        prefix=Path(current_controller(store,run))
        ctx.command([str(prefix/'bin/python'),'-m','pip','check'])
        ctx.command([str(prefix/'bin/python'),'-c','import snakemake, flupop; print(snakemake.__version__)'])
        from .readiness import identity
        store.put('run_environment_checks',run['id'],{'id':run['id'],'identity':identity(store,run),'status':'checked',
            'checked_at':now(),'job':ctx.job['id'],'rows':[]})
        ctx.write('FluPop uses its installed runner; this release declares no separate rule environments.')
        return
    run['last_controller']=current_controller(store,run)
    if action=='dry-run':run['dry_run_ok']=False
    elif run.get('completed'):run['previous_completed']=run.pop('completed')
    store.put('runs',run['id'],run)
    results.observe(ctx,run,'before')
    try:ctx.command(command(store,run,action),cwd=Path(run['folder']))
    finally:results.observe(ctx,run,'after')
    if action=='dry-run':run.update(dry_run_ok=True,validated=now(),validated_controller=run['last_controller'])
    else:
        from .pipelines import REPORT_FILES
        if not all((Path(run['output'])/'report'/name).is_file() for name in REPORT_FILES):raise ValueError('Workflow exited without expected report files.')
        run['completed']=now()
    run['last_action']=action;store.put('runs',run['id'],run)
    if action=='run':methods.capture(store,run,ctx.job['id'])


def report_candidates(store,run):return [('Viral Cloud','report/viral-cloud.html')]


def clone_runs(store,parent_id,aware_free=False,strategies=None):
    parent=store.get('runs',parent_id)
    if not parent:raise ValueError('Choose a saved run.')
    return [create_run(store,'flupop',parent['sample'],parent['submitted'],parent['cores'],parent['memory_mb'],parent_id,parent['label']+' · copy',parent['installation'],parent['inputs'])]


def environment_rows(item):
    path=Path(item['source'])/'environment.yml'
    return [{'id':'runner','name':'FluPop and Snakemake runner','recipe':str(path),'hook':'',
             'definition':hashlib.sha256(path.read_bytes()).hexdigest()}]


def environment_execute(ctx):
    from .engine import check_controller
    store=ctx.store;payload=ctx.job['payload'];item=store.get('installs',payload['installation'])
    from .maintenance import environment_request
    fresh=environment_request(store,item['id'],list(payload['definitions']),payload['action'])
    if fresh!=payload:raise ValueError('Environment selection changed. Review it again.')
    row=environment_rows(item)[0]
    receipt={**row,'path':item['controller'],'cache':payload['cache'],'checked_at':now(),'job':ctx.job['id']}
    try:
        if payload['action'] in ('repair','install'):prepare_controller(ctx,item,repair=payload['action']=='repair')
        else:check_controller(ctx,item.get('conda'),item['controller'],'flupop',item['controller_requirements'])
        receipt.update(status='Available',path=item['controller'],message='Runner import, pinned versions and dependency checks passed.')
    except Exception as exc:
        receipt.update(status='Needs attention',message=str(exc));raise
    finally:store.put('environment_checks',item['id'],{'runner':receipt})
