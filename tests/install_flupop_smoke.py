"""Clean Conda install plus external synthetic workflow, run by dedicated CI job."""
from pathlib import Path
import sys
import tempfile
from viralogix.store import Store
from viralogix.pipeline_worker import install, execute_run
from viralogix.pipelines import open_result

with tempfile.TemporaryDirectory(prefix='virologix-install-') as tmp:
    store=Store(Path(tmp)/'workspace')
    install(store,'clean-install')
    installed=store.get('pipelines','flupop')
    assert Path(installed['python']) != Path(sys.executable)
    assert str(store.home/'envs'/'flupop') in installed['python']
    execute_run(store,'clean-demo',{'installation':installed,'sample':'DEMO','demo':True})
    result=open_result(store,'clean-demo')
    assert result['run']['status']=='succeeded'
    assert 'SYNTHETIC' in result['html']
    install(store,'check-current')
    assert store.get('pipelines','flupop')==installed
    print('Clean isolated installation, demo, report and current-version check passed.')
