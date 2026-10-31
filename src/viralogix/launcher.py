"""Start the local UI and open its ready address on Linux, macOS or WSL."""
from __future__ import annotations

import ipaddress
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import ProxyHandler, build_opener
from .store import Store
from . import restart


def is_wsl():
    return bool(os.environ.get('WSL_DISTRO_NAME') or 'microsoft' in platform.release().lower())


def output(argv):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=3, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ''


def private_ipv4(values):
    for value in values:
        try:
            ip = ipaddress.ip_address(value)
        except ValueError:
            continue
        if ip.version == 4 and ip.is_private and not (ip.is_loopback or ip.is_link_local or ip.is_unspecified):
            return str(ip)
    return None


def default_host():
    if not is_wsl():
        return '127.0.0.1'
    info = shutil.which('wslinfo')
    if not info and Path('/usr/lib/wsl/wslinfo').is_file():
        info = '/usr/lib/wsl/wslinfo'
    if info and output([info, '--networking-mode']).lower() in {'mirrored', 'none'}:
        return '127.0.0.1'
    # Prefer the default-route interface over Docker/VPN interfaces in hostname -I.
    try:
        routes = json.loads(output(['ip', '-j', '-4', 'route', 'show', 'default']) or '[]')
        for route in sorted(routes, key=lambda r: r.get('metric', 0)):
            dev = route.get('dev')
            if not isinstance(dev, str) or not re.fullmatch(r'[A-Za-z0-9_.:@-]+', dev):
                continue
            addresses = json.loads(output(['ip', '-j', '-4', 'address', 'show', 'dev', dev]) or '[]')
            found = private_ipv4(a.get('local', '') for interface in addresses
                                 for a in interface.get('addr_info', []) if a.get('scope') == 'global')
            if found:
                return found
    except (ValueError, TypeError, AttributeError):
        pass
    return private_ipv4(output(['hostname', '-I']).split()) or '127.0.0.1'


def checked_host(host):
    if not re.fullmatch(r'[A-Za-z0-9.:\[\]-]+', host):
        raise ValueError('Use an IP address or hostname for --host, without a URL, port or shell characters.')
    host = host.removeprefix('[').removesuffix(']')
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        if (len(host) <= 253 and all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label)
                                    for label in host.rstrip('.').split('.'))):
            return host
    raise ValueError('Use an IP address or hostname for --host, without a URL, port or shell characters.')


def browser_url(host, port):
    host = checked_host(host)
    host = {'0.0.0.0': '127.0.0.1', '::': '::1'}.get(host, host)
    if ':' in host:
        host = '[' + host + ']'
    return f'http://{host}:{port}'


def free_port(host, requested=None):
    if requested is not None and not 1 <= requested <= 65535:
        raise ValueError('--port must be between 1 and 65535.')
    for port in ([requested] if requested is not None else range(8502, 8522)):
        try:
            addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            for family, socktype, protocol, _, address in addresses:
                try:
                    with socket.socket(family, socktype, protocol) as probe:
                        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                        probe.bind(address)
                    return port
                except OSError:
                    continue
        except OSError:
            break
    if requested is not None:
        raise ValueError(f'Cannot listen on {host}:{requested}. Stop the app using it or omit --port to choose an available port.')
    raise ValueError(f'No available port on {host} between 8502 and 8521. Check the address or choose --host / --port explicitly.')


def server_command(host, port, app=None):
    argv = [sys.executable, '-m', 'streamlit', 'run', str(app or Path(__file__).with_name('app.py')),
            '--server.address', host, '--server.port', str(port), '--server.headless', 'true',
            '--server.fileWatcherType', 'none', '--browser.gatherUsageStats', 'false',
            '--server.baseUrlPath', '', '--logger.hideWelcomeMessage', 'false', '--server.enableStaticServing', 'true']
    if host not in {'0.0.0.0', '::'}:
        argv += ['--browser.serverAddress', host]
    return argv


def healthy(url):
    # Local health checks must not be redirected through HTTP(S)_PROXY.
    try:
        with build_opener(ProxyHandler({})).open(url + '/_stcore/health', timeout=.5) as response:
            return response.status == 200 and response.read(32).strip() == b'ok'
    except OSError:
        return False


def open_folder(path):
    """Request the desktop file manager without passing paths through a shell."""
    folder = Path(path).resolve(strict=True)
    if not folder.is_dir():
        raise ValueError('Report folder no longer exists')
    try:
        if is_wsl():
            converted = subprocess.run(['wslpath', '-w', str(folder)], check=True,
                                       capture_output=True, text=True, timeout=5).stdout.strip()
            if not converted:
                raise ValueError('Could not translate the report folder for Windows Explorer')
            argv = ['explorer.exe', converted]
        elif sys.platform == 'darwin':
            argv = ['open', str(folder)]
        elif sys.platform == 'win32':
            argv = ['explorer.exe', str(folder)]
        else:
            if not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
                raise ValueError('No desktop session is available. Open this folder manually: ' + str(folder))
            argv = ['xdg-open', str(folder)]
        subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError('Could not open the file manager. Open this folder manually: ' + str(folder)) from exc
    return str(folder)


def open_browser(url):
    """Use Windows' default browser in WSL; do not install a browser or change defaults."""
    if is_wsl():
        powershell = shutil.which('powershell.exe')
        fallback = '/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe'
        if not powershell and Path(fallback).is_file():
            powershell = fallback
        commands = []
        if powershell:
            commands.append([powershell, '-NoProfile', '-NonInteractive', '-Command',
                             "Start-Process -FilePath '" + url.replace("'", "''") + "'"])
        if cmd := shutil.which('cmd.exe'):
            # URL is generated only from a validated host and an integer port.
            commands.append([cmd, '/d', '/c', 'start', '""', url])
        if viewer := shutil.which('wslview'):
            commands.append([viewer, url])
    else:
        if platform.system() == 'Linux' and not any(os.environ.get(k) for k in ('DISPLAY', 'WAYLAND_DISPLAY', 'BROWSER')):
            return False
        commands = [[sys.executable, '-c',
                     'import sys, webbrowser; sys.exit(0 if webbrowser.open(sys.argv[1], new=2) else 1)', url]]
    for argv in commands:
        try:
            result = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, timeout=10)
            if result.returncode == 0:
                return True
        except (OSError, subprocess.SubprocessError):
            continue
    return False


def open_app_window(url):
    """Request installed Chromium browser app mode; never install or change defaults."""
    from urllib.parse import urlsplit
    try:
        target = urlsplit(url)
        if target.scheme != 'http' or target.path or target.query or target.fragment or target.username or target.password:
            return False
        if not target.port or browser_url(target.hostname, target.port) != url:
            return False
    except (TypeError, ValueError):
        return False
    if is_wsl() or platform.system() == 'Windows':
        powershell = shutil.which('powershell.exe')
        fallback = '/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe'
        if not powershell and is_wsl() and Path(fallback).is_file():
            powershell = fallback
        if not powershell:
            return False
        # Paths are derived by Windows, including per-user and 32/64-bit installs.
        script = ("$ErrorActionPreference='Stop'; "
                  "$roots=@($env:ProgramFiles,${env:ProgramFiles(x86)},$env:LOCALAPPDATA) | Where-Object { $_ }; "
                  "$names=@('Microsoft\\Edge\\Application\\msedge.exe','Google\\Chrome\\Application\\chrome.exe'); "
                  "foreach($name in $names){foreach($root in $roots){$exe=Join-Path $root $name; "
                  "if(Test-Path -LiteralPath $exe -PathType Leaf){try { "
                  "Start-Process -FilePath $exe -ArgumentList @('--app=" + url + "','--window-size=1440,1000') -ErrorAction Stop; exit 0 "
                  "} catch { } } } }; exit 1")
        try:
            result = subprocess.run([powershell, '-NoProfile', '-NonInteractive', '-Command', script],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, timeout=10)
            return result.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False
    if platform.system() == 'Linux' and not any(os.environ.get(k) for k in ('DISPLAY', 'WAYLAND_DISPLAY')):
        return False
    paths = []
    if platform.system() == 'Darwin':
        for root in (Path('/Applications'), Path.home() / 'Applications'):
            for app, binary in (('Google Chrome', 'Google Chrome'), ('Microsoft Edge', 'Microsoft Edge')):
                path = root / (app + '.app') / 'Contents/MacOS' / binary
                if path.is_file():
                    paths.append(str(path))
    else:
        paths = [path for name in ('google-chrome', 'google-chrome-stable', 'microsoft-edge', 'microsoft-edge-stable', 'chromium', 'chromium-browser')
                 if (path := shutil.which(name))]
    for path in dict.fromkeys(paths):
        try:
            proc = subprocess.Popen([path, '--app=' + url, '--window-size=1440,1000'],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    start_new_session=True)
            try:
                if proc.wait(timeout=.5) == 0:
                    return True  # Existing browser accepted the handoff.
            except subprocess.TimeoutExpired:
                return True  # Browser owns its window; do not wait for it to close.
        except OSError:
            continue
    return False


def launch_browser(url, app_window=False):
    if app_window:
        if open_app_window(url):
            return True
        print('App-window launch unavailable. Opening the regular browser instead.', flush=True)
    return open_browser(url)


def stop_server(proc, sig=signal.SIGTERM):
    if proc.poll() is None:
        try:
            proc.send_signal(sig)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def serve(home, host=None, port=None, browser=True, app_window=True, desktop_control=None, desktop_session=None):
    host = checked_host(host or default_host())
    port = free_port(host, port)
    url = browser_url(host, port)
    store = Store(home)
    desktop = None
    if desktop_control:
        from .desktop import Session, ENV
        desktop = Session(store, desktop_control, desktop_session)
        os.environ[ENV] = desktop_session
        browser = False  # Windows owns the dedicated browser and its lifetime.
    parent = store.home / 'launcher'
    parent.mkdir(exist_ok=True)
    restarting = False
    with tempfile.TemporaryDirectory(prefix='server-', dir=parent) as temporary:
        item = restart.register(store, url)
        app = restart.make_app(temporary, item)
        env = dict(os.environ, VIRALOGIX_HOME=str(home), VIRALOGIX_LAUNCH_ID=item['id'], PYTHONUNBUFFERED='1')
        print(f'Starting Viralogix at {url}\n' + ('Windows desktop supervisor controls this session.' if desktop else 'Keep this terminal open. Press Ctrl+C to stop the app.'), flush=True)
        proc = subprocess.Popen(server_command(host, port, app), env=env, start_new_session=os.name != 'nt',
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        listening = threading.Event()
        def relay_output():
            for line in proc.stdout:
                # The pinned Streamlit release prints this only after its server binds.
                if 'You can now view your Streamlit app in your browser.' in line:
                    listening.set()
                try:
                    print(line, end='', flush=True)
                except (BrokenPipeError, OSError):
                    pass
        reader = threading.Thread(target=relay_output, daemon=True)
        reader.start()
        previous_term = signal.getsignal(signal.SIGTERM)
        def terminated(signum, frame):
            # Unwind Popen.wait before waiting again: its waitpid lock is not reentrant.
            try:
                proc.send_signal(signum)
            except ProcessLookupError:
                pass
            raise SystemExit(128 + signum)
        signal.signal(signal.SIGTERM, terminated)
        ready = False
        desktop_closed = False
        try:
            deadline = time.monotonic() + 60
            while proc.poll() is None:
                if desktop and desktop.tick(url, ready):
                    desktop_closed = True
                    stop_server(proc)
                    break
                if not ready and listening.is_set() and healthy(url):
                    if proc.poll() is not None:
                        break
                    ready = True
                    restart.mark_ready(store, item)
                    print(f'Viralogix is ready: {url}', flush=True)
                    if browser and not launch_browser(url, app_window=app_window):
                        print(f'Could not open a browser automatically. Open {url} in your browser.', flush=True)
                if ready:
                    request = restart.pending(store, item)
                    if request and restart.verify_and_mark(store, item, request):
                        print('Update verified. Restarting Viralogix on ' + url, flush=True)
                        restarting = True
                        break
                elif deadline and time.monotonic() >= deadline:
                    print(f'App startup timed out. Check the server output; its address is {url}.', flush=True)
                    deadline = None
                    if desktop:
                        desktop.stop('Server startup timed out')
                time.sleep(.3)
            if not restarting:
                code = proc.wait()
                if not ready:
                    print(f'Viralogix stopped before becoming ready (exit {code}). See the server output above.', file=sys.stderr)
                return (0 if ready else 1) if desktop_closed else code if ready else code or 1
        except KeyboardInterrupt:
            stop_server(proc, signal.SIGINT)
            return 0
        finally:
            if desktop and not restarting:
                desktop.stop('Desktop session closing')
                while desktop.jobs():
                    desktop.publish(url)
                    time.sleep(.25)
            signal.signal(signal.SIGTERM, previous_term)
            stop_server(proc)
            reader.join(timeout=1)
            if not reader.is_alive():
                proc.stdout.close()
            restart.unregister(store, item)
            if desktop and not restarting:
                desktop.finish(url)
    if restarting:
        # A fresh interpreter loads the new launcher as well as the new application.
        # Existing tabs reload through runtime.json; do not open duplicate browser tabs.
        extra = ['--desktop-control', str(desktop.root), '--desktop-session', desktop.key] if desktop else []
        os.execv(sys.executable, [sys.executable, '-m', 'viralogix.cli', 'serve', '--home', str(home),
                                 '--host', host, '--port', str(port), '--no-browser', *extra])
