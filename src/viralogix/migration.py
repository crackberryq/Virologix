"""Idempotent, non-destructive import of earlier manager records."""
from pathlib import Path
from .store import now

def migrate(store):
    for sample in store.all('samples'):
        if 'mode' not in sample or 'path' not in sample:
            store.put('samples',sample['id'],{**sample,'mode':'supplied_records','path':sample.get('path') or str(Path(sample.get('r1',store.home)).parent)})
    previous=store.get('pipelines','flupop')
    if previous:
        key='flupop-legacy-'+previous['revision']
        if not store.get('installs',key):
            record={'id':key,'tool':'flupop','source':previous['source'],'controller':str(Path(previous['python']).parent.parent),
                'version':{'id':'legacy:'+key,'ref':previous.get('version','Earlier installation'),'commit':previous['revision'],'kind':'local'},
                'created':previous.get('installed',now()),'ready':Path(previous['python']).is_file(),'origin':'legacy',
                'rule_cache':str(store.home/'envs/flupop'),'setup_completed':now(),'setup_phase':'complete',
                'controller_requirements':{'python':'3.12','snakemake':previous.get('engine_version','9.27.0')}}
            store.put('installs',key,record)
            if not store.get('settings','active-flupop'):store.put('settings','active-flupop',key)
    for run in store.all('cloud_runs'):
        key='legacy-'+run['id']
        if run.get('status','succeeded')=='succeeded' and not store.get('reports',key):
            path=Path(run.get('report_path') or store.home/'runs'/run['id'])/'viral-cloud.html'
            if path.is_file():store.put('reports',key,{'id':key,'name':'Viral Cloud · '+run.get('label',run['sample']),
                'path':str(path),'run':run['id'],'sample':run['sample'],'run_status':'completed'})
    if any(j['kind'].startswith('flupop_') and j['status'] in ('queued','running') for j in store.jobs()):return
    if not store.get('settings','active-flupop'):return
    from .runs import create_run
    import yaml
    for old in store.all('cloud_runs'):
        if old.get('status') not in ('draft','failed') or store.get('legacy_migrations',old['id']):continue
        sample=store.get('samples',old['sample'])
        if not sample:
            sample={'id':old['sample'],'path':str(Path(previous['source'])/'examples') if old.get('synthetic_demo') and previous else str(store.home), 'mode':'supplied_records'}
        config={'synthetic_demo':bool(old.get('synthetic_demo')),'inputs':old.get('input_paths',{})}
        if not config['synthetic_demo'] and not config['inputs']:
            store.put('legacy_migration_issues',old['id'],{'id':old['id'],'message':'Earlier run inputs need to be selected in a new draft. Original record and files retained.'})
            continue
        try:
            run=create_run(store,'flupop',sample,yaml.safe_dump(config),1,1024,label=old.get('label') or old['sample'])
            run['legacy_run_id']=old['id'];store.put('runs',run['id'],run)
            if old.get('archived'):
                store.put('run_visibility',run['id'],{'id':run['id'],'archived':True,'reason':'Migrated archive'})
            store.put('legacy_migrations',old['id'],{'id':old['id'],'run_id':run['id'],'at':now()})
        except (OSError,ValueError,KeyError) as exc:
            store.put('legacy_migration_issues',old['id'],{'id':old['id'],'message':str(exc)})
