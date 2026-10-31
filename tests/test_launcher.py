"""Launcher routing, browser handoff and a real packaged server lifecycle."""
import io
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

import pytest

from viralogix import launcher as l


def test_default_linux_host_is_loopback(monkeypatch):
    monkeypatch.setattr(l, 'is_wsl', lambda: False)
    assert l.default_host() == '127.0.0.1'


@pytest.mark.parametrize('mode,expected', [('mirrored', '127.0.0.1'), ('nat', '172.21.21.143')])
def test_wsl_uses_current_route_address_or_mirrored_loopback(monkeypatch, mode, expected):
    monkeypatch.setattr(l, 'is_wsl', lambda: True)
    monkeypatch.setattr(l.shutil, 'which', lambda name: '/bin/wslinfo' if name == 'wslinfo' else None)
    def output(argv):
        if argv[-1] == '--networking-mode': return mode
        if 'route' in argv: return '[{"dev":"eth0","metric":100}]'
        if 'address' in argv:
            assert argv[-1] == 'eth0'
            return '[{"addr_info":[{"local":"172.21.21.143","scope":"global"}]}]'
        raise AssertionError(argv)
    monkeypatch.setattr(l, 'output', output)
    assert l.default_host() == expected


@pytest.mark.parametrize('addresses,expected', [
    ('127.0.0.1 169.254.1.2 172.21.21.143 172.17.0.1', '172.21.21.143'),
    ('garbage 8.8.8.8 ::1', '127.0.0.1'), ('', '127.0.0.1'),
])
def test_wsl_missing_network_tools_use_bounded_fallback(monkeypatch, addresses, expected):
    monkeypatch.setattr(l, 'is_wsl', lambda: True)
    monkeypatch.setattr(l.shutil, 'which', lambda name: None)
    monkeypatch.setattr(l, 'output', lambda argv: addresses if argv == ['hostname', '-I'] else '')
    assert l.default_host() == expected


@pytest.mark.parametrize('host,url_host', [('127.0.0.1', '127.0.0.1'), ('172.21.21.143', '172.21.21.143'),
                                         ('0.0.0.0', '127.0.0.1'), ('::', '[::1]'), ('[::1]', '[::1]')])
def test_advertised_address_handles_ipv6_and_wildcards(host, url_host):
    assert l.browser_url(host, 8502) == f'http://{url_host}:8502'


@pytest.mark.parametrize('host', ['http://localhost', 'localhost:8501', 'localhost & calc', "a';exit;'", 'fe80::1%eth0&calc'])
def test_host_cannot_inject_browser_commands(host):
    with pytest.raises(ValueError, match='IP address or hostname'):
        l.checked_host(host)


def test_occupied_explicit_port_fails_before_starting_anything():
    with socket.socket() as occupied:
        occupied.bind(('127.0.0.1', 0))
        occupied.listen()
        with pytest.raises(ValueError, match='Cannot listen'):
            l.free_port('127.0.0.1', occupied.getsockname()[1])
    with pytest.raises(ValueError, match='between 1 and 65535'):
        l.free_port('127.0.0.1', 0)


def test_auto_port_skips_occupied_default(monkeypatch):
    real = socket.getaddrinfo
    calls = []
    def addresses(host, port, **kwargs):
        calls.append(port)
        if port == 8502:
            return [(socket.AF_INET, socket.SOCK_STREAM, 0, '', ('127.0.0.1', busy_port))]
        return real(host, 0, **kwargs)
    with socket.socket() as occupied:
        occupied.bind(('127.0.0.1', 0)); occupied.listen()
        busy_port = occupied.getsockname()[1]
        monkeypatch.setattr(l.socket, 'getaddrinfo', addresses)
        assert l.free_port('127.0.0.1') == 8503
    assert calls == [8502, 8503]


def test_wsl_browser_opens_windows_default_without_shell(monkeypatch):
    monkeypatch.setattr(l, 'is_wsl', lambda: True)
    monkeypatch.setattr(l.shutil, 'which', lambda name: '/windows/powershell.exe' if name == 'powershell.exe' else None)
    calls = []
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0)
    monkeypatch.setattr(l.subprocess, 'run', run)
    assert l.open_browser('http://172.21.21.143:8502')
    argv, kw = calls[0]
    assert argv[:3] == ['/windows/powershell.exe', '-NoProfile', '-NonInteractive']
    assert argv[-1] == "Start-Process -FilePath 'http://172.21.21.143:8502'"
    assert not kw.get('shell') and kw['timeout'] == 10


def test_wsl_browser_failure_tries_cmd_then_leaves_server_available(monkeypatch):
    monkeypatch.setattr(l, 'is_wsl', lambda: True)
    monkeypatch.setattr(l.shutil, 'which', lambda name: '/windows/' + name if name in {'powershell.exe', 'cmd.exe'} else None)
    calls = []
    def run(argv, **kw):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 1)
    monkeypatch.setattr(l.subprocess, 'run', run)
    assert not l.open_browser('http://172.21.21.143:8502')
    assert [Path(argv[0]).name for argv in calls] == ['powershell.exe', 'cmd.exe']


def test_headless_linux_does_not_start_terminal_browser(monkeypatch):
    monkeypatch.setattr(l, 'is_wsl', lambda: False)
    monkeypatch.setattr(l.platform, 'system', lambda: 'Linux')
    for name in ('DISPLAY', 'WAYLAND_DISPLAY', 'BROWSER'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(l.subprocess, 'run', lambda *a, **k: pytest.fail('Unexpected browser process'))
    assert not l.open_browser('http://127.0.0.1:8501')


def test_cli_no_browser_preserves_workspace_and_overrides(tmp_path, monkeypatch):
    from viralogix.cli import main
    calls = []
    monkeypatch.setattr(sys, 'argv', ['viralogix', '--home', str(tmp_path), '--host', '127.0.0.1', '--port', '8502', '--no-browser'])
    monkeypatch.setattr(l, 'serve', lambda *args, **kwargs: calls.append((args, kwargs)) or 0)
    with pytest.raises(SystemExit) as result:
        main()
    assert result.value.code == 0
    assert calls == [((tmp_path, '127.0.0.1', 8502), {'browser': False})]


def test_failed_server_does_not_open_another_healthy_streamlit(monkeypatch, tmp_path):
    class Failed:
        stdout = io.StringIO('Port is already in use\n')
        def poll(self): return 1
        def wait(self, **kw): return 1
    monkeypatch.setattr(l, 'free_port', lambda *args: 8501)
    monkeypatch.setattr(l.subprocess, 'Popen', lambda *args, **kw: Failed())
    monkeypatch.setattr(l, 'healthy', lambda url: pytest.fail('Failed child has no listening signal'))
    monkeypatch.setattr(l, 'open_browser', lambda url: pytest.fail('Failed server must not open a browser'))
    assert l.serve(tmp_path, '127.0.0.1') == 1


@pytest.mark.parametrize('no_browser', [False, True])
def test_real_console_launcher_ready_handoff_and_shutdown(tmp_path, no_browser):
    executable = Path(sys.executable).with_name('viralogix')
    assert executable.is_file(), 'Install the package so its console command can be exercised'
    receipt = tmp_path / 'browser.json'
    helper = tmp_path / 'browser helper.py'
    helper.write_text('import json, sys\nfrom pathlib import Path\n'
                      'from urllib.request import build_opener, ProxyHandler\n'
                      'url = sys.argv[1]\n'
                      'with build_opener(ProxyHandler({})).open(url + "/_stcore/health", timeout=3) as r:\n'
                      '    Path(' + repr(str(receipt)) + ').write_text(json.dumps({"url": url, "status": r.status}))\n')
    env = dict(os.environ, BROWSER=f'"{sys.executable}" "{helper}" %s')
    # Test local readiness even if the machine has a proxy configured.
    env.update(HTTP_PROXY='http://127.0.0.1:1', HTTPS_PROXY='http://127.0.0.1:1', NO_PROXY='')
    with socket.socket() as available:
        available.bind(('127.0.0.1', 0)); port = available.getsockname()[1]
    url = f'http://127.0.0.1:{port}'
    args = [str(executable), '--home', str(tmp_path / 'workspace'), '--host', '127.0.0.1', '--port', str(port)]
    if no_browser:
        args.append('--no-browser')
    else:
        # Exercise the user's normal command with no flags at all.
        args = [str(executable)]
        env['VIRALOGIX_HOME'] = str(tmp_path / 'workspace')
    log = tmp_path / 'server.log'
    with log.open('w') as output:
        proc = subprocess.Popen(args, env=env, stdout=output, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                if proc.poll() is not None: pytest.fail(log.read_text())
                if 'Viralogix is ready:' in log.read_text() and (no_browser or receipt.exists()): break
                time.sleep(.1)
            else:
                pytest.fail('Launcher did not become ready:\n' + log.read_text())
            if not no_browser:
                url = json.loads(receipt.read_text())['url']
                assert url.startswith('http://127.0.0.1:')
                assert 8501 <= int(url.rsplit(':', 1)[1]) <= 8520
            assert l.healthy(url)
            if no_browser:
                assert not receipt.exists()
            else:
                assert json.loads(receipt.read_text()) == {'url': url, 'status': 200}
            proc.send_signal(signal.SIGTERM if no_browser else signal.SIGINT)
            proc.wait(timeout=15)
            assert not l.healthy(url), 'Stopping the launcher must also stop its UI server'
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill(); proc.wait()


def test_app_window_wsl_uses_known_windows_locations_and_validated_url(monkeypatch):
    monkeypatch.setattr(l, 'is_wsl', lambda: True)
    monkeypatch.setattr(l.shutil, 'which', lambda name: '/windows/powershell.exe' if name=='powershell.exe' else None)
    calls=[]
    monkeypatch.setattr(l.subprocess, 'run', lambda argv, **kw: calls.append((argv,kw)) or subprocess.CompletedProcess(argv,0))
    assert l.open_app_window('http://172.21.21.143:8502')
    argv,kw=calls[0]
    assert argv[:3]==['/windows/powershell.exe','-NoProfile','-NonInteractive']
    assert "'--app=http://172.21.21.143:8502'" in argv[-1]
    assert 'msedge.exe' in argv[-1] and 'chrome.exe' in argv[-1] and '$env:LOCALAPPDATA' in argv[-1]
    assert kw['timeout']==10 and not kw.get('shell')
    for url in ["http://localhost:8501';calc",'https://example.com','http://localhost:8501/path','http://user@localhost:8501','http://localhost:8501?x=1']:
        assert not l.open_app_window(url)
    assert len(calls)==1


def test_app_window_native_argv_and_detached_window(monkeypatch):
    monkeypatch.setattr(l,'is_wsl',lambda:False);monkeypatch.setattr(l.platform,'system',lambda:'Linux')
    monkeypatch.setenv('DISPLAY',':0')
    monkeypatch.setattr(l.shutil,'which',lambda n:'/opt/browser with spaces/chrome' if n=='google-chrome' else None)
    calls=[]
    class Window:
        def wait(self,timeout):
            assert timeout==.5
            raise subprocess.TimeoutExpired('browser',timeout)
    monkeypatch.setattr(l.subprocess,'Popen',lambda argv,**kw:calls.append((argv,kw)) or Window())
    assert l.open_app_window('http://127.0.0.1:8501')
    assert calls[0][0]==['/opt/browser with spaces/chrome','--app=http://127.0.0.1:8501','--window-size=1440,1000']
    assert calls[0][1]['start_new_session'] and not calls[0][1].get('shell')


def test_app_window_fallback_and_browser_opt_out(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(l,'open_app_window',lambda url:False)
    calls=[];monkeypatch.setattr(l,'open_browser',lambda url:calls.append(url) or True)
    assert l.launch_browser('http://127.0.0.1:8501',True)
    assert 'regular browser' in capsys.readouterr().out and len(calls)==1
    from viralogix.cli import main
    monkeypatch.setattr(l,'serve',lambda *a,**kw:calls.append(kw) or 0)
    monkeypatch.setattr(sys,'argv',['viralogix','--home',str(tmp_path),'--app-window'])
    with pytest.raises(SystemExit) as result:main()
    assert result.value.code==0 and calls[-1]=={'browser':True,'app_window':True}
    monkeypatch.setattr(sys,'argv',['viralogix','--no-browser','--app-window'])
    with pytest.raises(SystemExit) as result:main()
    assert result.value.code==2


def test_app_window_no_desktop_does_not_launch_a_gui(monkeypatch):
    monkeypatch.setattr(l,'is_wsl',lambda:False);monkeypatch.setattr(l.platform,'system',lambda:'Linux')
    monkeypatch.delenv('DISPLAY',raising=False);monkeypatch.delenv('WAYLAND_DISPLAY',raising=False)
    monkeypatch.setattr(l.subprocess,'Popen',lambda *a,**k:pytest.fail('GUI launch on headless host'))
    assert not l.open_app_window('http://127.0.0.1:8501')


def test_app_window_tries_next_browser_after_failed_launch(monkeypatch):
    monkeypatch.setattr(l, 'is_wsl', lambda: False)
    monkeypatch.setattr(l.platform, 'system', lambda: 'Linux')
    monkeypatch.setenv('DISPLAY', ':0')
    monkeypatch.setattr(l.shutil, 'which', lambda name: {'google-chrome': '/chrome', 'chromium': '/chromium'}.get(name))
    calls = []
    class Process:
        def wait(self, timeout):
            return 1 if len(calls) == 1 else 0
    def start(argv, **kwargs):
        calls.append(argv)
        return Process()
    monkeypatch.setattr(l.subprocess, 'Popen', start)
    assert l.open_app_window('http://127.0.0.1:8501')
    assert [call[0] for call in calls] == ['/chrome', '/chromium']


def test_app_window_powershell_timeout_falls_back(monkeypatch):
    monkeypatch.setattr(l, 'is_wsl', lambda: True)
    monkeypatch.setattr(l.shutil, 'which', lambda name: '/powershell.exe')
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs['timeout'])
    monkeypatch.setattr(l.subprocess, 'run', timeout)
    opened = []
    monkeypatch.setattr(l, 'open_browser', lambda url: opened.append(url) or True)
    assert l.launch_browser('http://127.0.0.1:8501', app_window=True)
    assert opened == ['http://127.0.0.1:8501']
