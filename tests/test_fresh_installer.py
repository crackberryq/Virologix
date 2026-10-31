import importlib.util
from pathlib import Path
import pytest
spec = importlib.util.spec_from_file_location('fresh_installer', Path(__file__).parents[1] / 'scripts/install_viralogix.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def release(tag, date, pre=False, draft=False):
    return {'tag_name':tag,'published_at':date,'prerelease':pre,'draft':draft,'assets':[{'name':'viralogix-1-py3-none-any.whl'}]}


def test_channels_and_drafts():
    rows=[release('stable','2026-01-01'),release('alpha','2026-02-01',True),release('draft','2026-03-01',draft=True)]
    assert installer.select_release(rows,'stable')['tag_name']=='stable'
    assert installer.select_release(rows,'prerelease')['tag_name']=='alpha'
    with pytest.raises(ValueError):installer.select_release([rows[1]],'stable')


def test_unverified_asset_never_downloaded(tmp_path, monkeypatch):
    monkeypatch.setattr(installer,'urlopen',lambda *a,**k:pytest.fail('Network used before validation'))
    with pytest.raises(ValueError):installer.download({'name':'wheel'},tmp_path/'wheel')
    with pytest.raises(ValueError):installer.download({'name':'wheel','digest':'sha256:'+'0'*64,'browser_download_url':'http://unsafe'},tmp_path/'wheel')


def test_conda_detection_does_not_guess_nonexistent_executable(monkeypatch, tmp_path):
    monkeypatch.setenv('CONDA_EXE',str(tmp_path/'absent'))
    monkeypatch.setattr(installer.shutil,'which',lambda name:None)
    monkeypatch.setattr(installer.Path,'home',lambda:tmp_path)
    assert installer.find_conda() is None


@pytest.mark.parametrize('launch', [False, True])
@pytest.mark.parametrize('environment,existing', [(None, False), ('app-env', False), ('app-env', True)])
def test_install_and_reuse(tmp_path, monkeypatch, environment, existing, launch):
    import json
    from types import SimpleNamespace
    monkeypatch.setattr(installer.Path, 'home', lambda: tmp_path)
    monkeypatch.setattr(installer.os, 'geteuid', lambda: 1000)
    monkeypatch.setattr(installer.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(installer.platform, 'machine', lambda: 'x86_64')
    monkeypatch.setattr(installer.shutil, 'disk_usage', lambda p: SimpleNamespace(free=10 * 2**30))
    monkeypatch.setattr(installer, 'find_conda', lambda: '/fixture/conda')
    monkeypatch.setattr(installer.sys, 'argv', ['installer'] + ([] if launch else ['--no-launch']))
    prefix = tmp_path/'.local/share/viralogix/app-env'
    if environment:
        (prefix/'bin').mkdir(parents=True)
        (prefix/'bin/python').touch()
    envs = [str(tmp_path/'miniconda3/envs/viralogix')]
    Path(envs[0]).mkdir(parents=True)
    (Path(envs[0])/'unrelated-tools').write_text('preserve')
    commands = []
    def run(argv, log, capture=False):
        argv = list(map(str, argv)); commands.append(argv)
        if argv[1:3] == ['env', 'list']: return json.dumps({'envs':envs})
        if argv[1] == 'create':
            assert argv[2:4] == ['--prefix', str(prefix)]
            assert '--no-default-packages' in argv
        if 'importlib.util' in argv[-1]: return str(existing)
        return ''
    monkeypatch.setattr(installer, 'run', run)
    monkeypatch.setattr(installer, 'get_json', lambda url: [release('alpha', '2026-01-01', True)])
    monkeypatch.setattr(installer, 'download', lambda a,p:p.write_bytes(b'fixture'))
    def launch_app(argv):
        assert not (tmp_path/'.local/share/viralogix/install.lock').exists()
        assert argv == [str(prefix/'bin/viralogix'), 'serve']
        return 0
    monkeypatch.setattr(installer.subprocess, 'call', launch_app)
    assert installer.main() == 0
    assert any('install' in cmd for cmd in commands) is not existing
    assert any('create' in cmd for cmd in commands) is (environment is None)
    assert not (tmp_path/'.local/share/viralogix/install.lock').exists()
    assert (Path(envs[0])/'unrelated-tools').read_text() == 'preserve'
    assert not any(str(Path(envs[0])/'bin/python') in cmd for cmd in commands)


def test_download_integrity_and_interruption(tmp_path, monkeypatch):
    import io, hashlib
    payload = b'verified fixture'
    asset = {'name':'fixture','size':len(payload),'digest':'sha256:'+hashlib.sha256(payload).hexdigest(),'browser_download_url':'https://github.com/example/repo/releases/download/v1/fixture'}
    monkeypatch.setattr(installer, 'urlopen', lambda *a,**k:io.BytesIO(payload))
    target = tmp_path/'download'
    installer.download(asset, target)
    assert target.read_bytes() == payload
    with pytest.raises(ValueError, match='verification failed'):
        installer.download({**asset,'size':1},target)
    monkeypatch.setattr(installer, 'urlopen', lambda *a,**k:io.BytesIO(b'corrupt'))
    with pytest.raises(ValueError, match='verification failed'):installer.download(asset,target)
    def interrupted(*a,**k):raise OSError('connection interrupted')
    monkeypatch.setattr(installer, 'urlopen', interrupted)
    with pytest.raises(OSError):installer.download(asset,target)


@pytest.mark.parametrize('has_conda', [False, True])
@pytest.mark.parametrize('check', [False, True])
def test_preflight_low_disk_has_no_install_side_effects(tmp_path, monkeypatch, check, has_conda):
    from types import SimpleNamespace
    monkeypatch.setattr(installer.Path,'home',lambda:tmp_path)
    monkeypatch.setattr(installer.os,'geteuid',lambda:1000)
    monkeypatch.setattr(installer.platform,'system',lambda:'Linux')
    monkeypatch.setattr(installer.platform,'machine',lambda:'x86_64')
    monkeypatch.setattr(installer.shutil,'disk_usage',lambda p:SimpleNamespace(free=1))
    monkeypatch.setattr(installer,'find_conda',lambda:'/fixture/conda' if has_conda else None)
    monkeypatch.setattr(installer.sys,'argv',['installer']+(['--check'] if check else []))
    monkeypatch.setattr(installer,'get_json',lambda *a:pytest.fail('Network request during failed preflight'))
    if check:assert installer.main()==1
    else:
        with pytest.raises(SystemExit):installer.main()
    assert not (tmp_path/'.local').exists()


def test_command_error_exposes_dependency_details(tmp_path, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(installer.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=1, stdout='multiqc requires boto3', stderr=''))
    with pytest.raises(RuntimeError, match='multiqc requires boto3'):
        installer.run(['python', '-m', 'pip', 'check'], tmp_path/'setup.log')
