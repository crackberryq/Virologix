"""Fresh Conda installation through the shared manager and external demo."""
from pathlib import Path
import tempfile
from viralogix.store import Store
from viralogix.engine import Context, execute
from viralogix.catalog import versions
from viralogix.runs import create_run, register_sample
from viralogix.results import inspect

with tempfile.TemporaryDirectory(prefix='virologix-install-') as tmp:
    store=Store(Path(tmp)/'workspace')
    def run_job(kind,payload):
        jid=store.submit(kind,payload)
        job=store.claim();assert job['id']==jid
        ctx=Context(store,job)
        try:execute(ctx)
        except BaseException:
            ctx.log.flush()
            print(store.log_path(jid).read_text(),flush=True)
            raise
        finally:ctx.log.close()
        store.update_job(jid,status='succeeded')
    version=versions(store,'flupop')['versions'][0]
    run_job('install',{'tool':'flupop','version':version})
    item=store.get('installs',store.get('settings','active-flupop'))
    assert item['ready'] and Path(item['controller']).is_relative_to(store.home/'controllers')
    sample=register_sample(store,'DEMO',str(Path(item['source'])/'examples'))
    run=create_run(store,'flupop',sample,'synthetic_demo: true\n',1,1024)
    for action in ('dry-run','check-environments','run'):
        run_job('workflow',{'run_id':run['id'],'action':action})
    result=inspect(store,run['id'])
    assert result['status']=='completed' and result['reports'][0]['state']=='available'
    assert 'SYNTHETIC' in Path(result['reports'][0]['path']).read_text()
    run_job('check',{'installation':item['id']})
    print('Shared-manager fresh installation, validation, runner check, execution and report passed.')
