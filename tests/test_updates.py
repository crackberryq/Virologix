import copy
import hashlib
import io
import json
import subprocess
import sys
import time
from types import SimpleNamespace
from zipfile import ZipFile
import pytest
from viralogix import __version__, updates, restart
from viralogix.store import Store, now


def wheel_bytes(version='99.0.0a1', python='>=3.11', name='viralogix'):
    stream=io.BytesIO()
    with ZipFile(stream,'w') as wheel:
        wheel.writestr(f'{name}-{version}.dist-info/METADATA',f'Metadata-Version: 2.4\nName: {name}\nVersion: {version}\nRequires-Python: {python}\n')
    return stream.getvalue()


def release(version='99.0.0a1', content=None):
    if content is None:content=wheel_bytes(version)
    name=f'viralogix-{version}-py3-none-any.whl'
    return {'id':77,'tag_name':'v'+version,'prerelease':True,'draft':False,'body':'Test release notes',
            'assets':[{'id':88,'name':name,'state':'uploaded','size':len(content),
            'digest':'sha256:'+hashlib.sha256(content).hexdigest(),
            'browser_download_url':f'https://github.com/{updates.REPO}/releases/download/v{version}/{name}'}]}


def job(store,kind='app_update',status='succeeded'):
    with store.connect() as db:
        db.execute('INSERT INTO jobs(id,kind,payload,status,created) VALUES(?,?,?,?,?)',('test',kind,'{}',status,now()))
    return 'test'


@pytest.mark.parametrize('bad',['url','digest','duplicate','draft'])
def test_release_rejects_unverifiable_asset(bad):
    value=release()
    if bad=='url':value['assets'][0]['browser_download_url']='https://example.org/wheel'
    if bad=='digest':value['assets'][0]['digest']=''
    if bad=='duplicate':value['assets'].append(copy.deepcopy(value['assets'][0]))
    if bad=='draft':value['draft']=True
    record=updates.release_record(value)
    assert record is None or not record['available']


def test_download_checks_checksum_and_metadata(tmp_path,monkeypatch):
    data=wheel_bytes();record=updates.release_record(release(content=data))
    def response(*a,**kw):
        result=io.BytesIO(data);result.url=record['wheel_url'];return result
    monkeypatch.setattr(updates,'urlopen',response)
    assert updates.download_wheel(record,tmp_path).read_bytes()==data
    record['sha256']='0'*64
    with pytest.raises(ValueError):updates.download_wheel(record,tmp_path)
    assert not (tmp_path/record['wheel_name']).exists()
    bad=tmp_path/'wrong.whl';bad.write_bytes(wheel_bytes(name='other'))
    with pytest.raises(ValueError):updates.validate_wheel(bad,'99.0.0a1')
    bad.write_bytes(wheel_bytes(python='>=999'))
    with pytest.raises(ValueError):updates.validate_wheel(bad,'99.0.0a1')


def test_update_blocks_active_pipeline_and_older_release(tmp_path,monkeypatch):
    store=Store(tmp_path)
    record=updates.release_record(release())
    store.put('app_catalog','releases',{'releases':[record]})
    job(store,'flupop_run','running')
    with pytest.raises(ValueError,match='active work'):updates.request_update(store,77,'req')
    with store.connect() as db:db.execute("UPDATE jobs SET status='succeeded'")
    record['version']='0.0.1';store.put('app_catalog','releases',{'releases':[record]})
    with pytest.raises(ValueError,match='newer'):updates.request_update(store,77,'req')


def test_changed_release_never_installs(tmp_path,monkeypatch):
    store=Store(tmp_path);record=updates.release_record(release())
    changed=release();changed['assets'][0]['digest']='sha256:'+'0'*64
    monkeypatch.setattr(updates,'api',lambda path:changed)
    monkeypatch.setattr(updates.subprocess,'run',lambda *a,**k:pytest.fail('Must not call pip'))
    ctx=SimpleNamespace(store=store,job={'id':'update','payload':{'release':record}},write=lambda x:None)
    with pytest.raises(ValueError,match='changed'):updates.install_update(ctx)


@pytest.mark.parametrize('fail',[False,True])
def test_install_targets_manager_and_marks_restart(tmp_path,monkeypatch,fail):
    store=Store(tmp_path);value=release();record=updates.release_record(value)
    monkeypatch.setattr(updates,'api',lambda path:value)
    monkeypatch.setattr(updates,'download_wheel',lambda record,directory:directory/record['wheel_name'])
    calls=[]
    def run(argv,**kwargs):
        calls.append(argv)
        if fail:raise subprocess.CalledProcessError(1,argv)
    monkeypatch.setattr(updates.subprocess,'run',run)
    ctx=SimpleNamespace(store=store,job={'id':'update','payload':{'release':record}},log=io.StringIO(),lock_fds=[],write=lambda x:None)
    if fail:
        with pytest.raises(subprocess.CalledProcessError):updates.install_update(ctx)
    else:updates.install_update(ctx)
    assert calls[0][:4]==[sys.executable,'-m','pip','--isolated']
    assert '--no-user' in calls[0]
    assert store.get('settings','app-update')['status']==('failed' if fail else 'installed')
    assert updates.status(store)['restart_required']


def test_restart_requires_successful_owned_job(tmp_path,monkeypatch):
    store=Store(tmp_path);item=restart.register(store,'http://127.0.0.1:8502');restart.mark_ready(store,item)
    jid=job(store)
    state={'job':jid,'version':__version__,'launcher_id':item['id'],'environment':sys.prefix,'pip_started_at':time.time(),'status':'installed'}
    store.put('settings','app-update',state)
    assert restart.pending(store,item)==state
    monkeypatch.setattr(restart.subprocess,'run',lambda *a,**k:None)
    assert restart.verify_and_mark(store,item,state)
    restart.mark_ready(store,item)
    assert restart.pending(store,item) is None
    assert store.get('settings','app-update')['restart_status']=='ready'
