#!/usr/bin/env python3
"""Beginner Linux/WSL installer. Does not install pipelines or touch analysis data."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
from urllib.request import Request, urlopen

STATUS_FILE = None


def progress(step, title, detail=''):
    print(f'[{step}/5] {title}: {detail}', flush=True)
    if STATUS_FILE:
        path = Path(STATUS_FILE)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'step': step, 'title': title, 'detail': detail}))
        os.replace(temporary, path)


def get_json(url):
    with urlopen(Request(url, headers={'User-Agent': 'Viralogix-installer', 'Accept': 'application/vnd.github+json'}), timeout=45) as r:
        return json.load(r)


def download(asset, target):
    digest = asset.get('digest', '')
    if not digest.startswith('sha256:') or len(digest) != 71:
        raise ValueError('Download has no verified SHA-256 metadata: ' + asset['name'])
    url = asset['browser_download_url']
    if not url.startswith('https://github.com/'):
        raise ValueError('Unexpected download origin')
    h = hashlib.sha256()
    with urlopen(Request(url, headers={'User-Agent': 'Viralogix-installer'}), timeout=90) as r, target.open('wb') as out:
        while chunk := r.read(1024 * 1024):
            h.update(chunk)
            out.write(chunk)
    if h.hexdigest() != digest.split(':', 1)[1] or target.stat().st_size != asset['size']:
        raise ValueError('Download verification failed; nothing was installed')


def run(argv, log, capture=False):
    print('Running:', ' '.join(map(str, argv)), flush=True)
    result = subprocess.run(list(map(str, argv)), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    with log.open('a') as f:
        f.write('\n' + ' '.join(map(str, argv)) + '\n' + result.stdout + result.stderr)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()[-3000:]
        raise RuntimeError('Command failed: ' + ' '.join(map(str, argv)) + '\n' + detail + '\nFull setup log: ' + str(log))
    return result.stdout if capture else None


def find_conda():
    candidates = [os.environ.get('CONDA_EXE'), shutil.which('conda')]
    candidates += [str(Path.home() / p / 'bin/conda') for p in ('miniforge3', 'miniconda3', 'anaconda3', '.local/share/viralogix/conda', '.local/share/bactomics/conda')]
    return next((p for p in candidates if p and Path(p).is_file() and os.access(p, os.X_OK)), None)


def select_release(rows, channel):
    eligible = [r for r in rows if not r.get('draft') and (channel == 'prerelease' or not r.get('prerelease'))
                and any(a['name'].startswith('viralogix-') and a['name'].endswith('-py3-none-any.whl') for a in r.get('assets', []))]
    if not eligible:
        raise ValueError('No installable release in this channel. Alpha releases require --channel prerelease.')
    return max(eligible, key=lambda r: r.get('published_at') or '')


def main():
    global STATUS_FILE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--channel', choices=['stable', 'prerelease'], default='prerelease', help='Default: prerelease while Viralogix is alpha')
    parser.add_argument('--install-conda', action='store_true', help='Allow installation of checksum-verified Miniforge if Conda is missing')
    parser.add_argument('--check', action='store_true', help='Read-only prerequisite check; no downloads or installs')
    parser.add_argument('--no-launch', action='store_true')
    parser.add_argument('--status-file', help='Write atomic progress for the Windows installer')
    parser.add_argument('--result-file', help='Write the installed launcher paths as JSON')
    parser.add_argument('--upgrade-app', action='store_true', help='Update an existing application; preserve its workspace and pipeline installations')
    args = parser.parse_args()
    STATUS_FILE = args.status_file
    progress(1, 'Checking Ubuntu', 'Operating system, disk space and existing Conda installation')
    if platform.system() != 'Linux':
        parser.error('Run inside Ubuntu/WSL2 or supported Linux, not Windows Python or PowerShell.')
    arch = platform.machine()
    if arch not in ('x86_64', 'aarch64'):
        parser.error('Unsupported installer architecture: ' + arch)
    if os.geteuid() == 0:
        parser.error('Run as your regular Ubuntu user, without sudo.')
    conda = find_conda()
    root = Path.home() / '.local/share/viralogix'
    free = shutil.disk_usage(Path.home()).free
    print('System:', platform.platform(), '\nArchitecture:', arch, '\nConda:', conda or 'missing', '\nHome free space: %.1f GiB' % (free / 2**30))
    print('This release installs the virology workspace interface; sequencing workflows are not yet included.')
    if args.check:
        if free < 3 * 2**30:
            print('Blocked: application setup requires at least 3 GiB free home space.')
        return 0 if conda and free >= 3 * 2**30 else 1
    if free < 3 * 2**30:
        parser.error('At least 3 GiB free home space is required for application setup; pipeline storage is additional.')
    if not conda and not args.install_conda:
        parser.error('Conda is missing. Rerun with --install-conda to install Miniforge, or install Conda yourself.')
    root.mkdir(parents=True, exist_ok=True)
    lock = root / 'install.lock'
    try:
        lock.mkdir()
    except FileExistsError:
        parser.error('Setup lock exists. Check for another installer before removing ' + str(lock))
    log = root / 'setup.log'
    try:
        with tempfile.TemporaryDirectory(prefix='viralogix-install-') as temporary:
            temp = Path(temporary)
            if not conda:
                progress(2, 'Installing Conda', 'Downloading and verifying Miniforge')
                release = get_json('https://api.github.com/repos/conda-forge/miniforge/releases/latest')
                name = 'Miniforge3-Linux-' + arch + '.sh'
                asset = next(a for a in release['assets'] if a['name'] == name)
                installer = temp / name
                download(asset, installer)
                prefix = root / 'conda'
                if prefix.exists():
                    raise ValueError('Incomplete Conda location already exists; inspect it before retrying: ' + str(prefix))
                run(['bash', installer, '-b', '-p', prefix], log)
                conda = str(prefix / 'bin/conda')
            progress(3, 'Preparing application environment', 'Using a dedicated environment; existing workflow environments are untouched')
            prefix = root / 'app-env'
            python = prefix / 'bin/python'
            if not python.is_file():
                if prefix.exists():
                    raise ValueError('Application environment is incomplete; inspect before retrying: ' + str(prefix))
                run([conda, 'create', '--prefix', prefix, '--no-default-packages', '--override-channels', '-c', 'conda-forge', 'python=3.12', 'pip', '-y'], log)
            run([python, '-c', 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ required"'], log)
            installed = run([python, '-c', 'import importlib.util; print(bool(importlib.util.find_spec("viralogix")))'], log, capture=True).strip()
            if installed == 'True' and not args.upgrade_app:
                print('Existing Viralogix preserved. Rerun Setup or use --upgrade-app to change versions.')
                command = Path(prefix) / 'bin/viralogix'
            else:
                progress(4, 'Installing Virologix', 'Discovering a published release and checking its download checksum')
                rows = get_json('https://api.github.com/repos/crackberryq/Virologix/releases?per_page=100')
                release = select_release(rows, args.channel)
                asset = next(a for a in release['assets'] if a['name'].startswith('viralogix-') and a['name'].endswith('-py3-none-any.whl'))
                wheel = temp / asset['name']
                download(asset, wheel)
                run([python, '-m', 'pip', 'install', '--upgrade', wheel], log)
                run([python, '-m', 'pip', 'check'], log)
                command = Path(prefix) / 'bin/viralogix'
                print('Installed:', release['tag_name'], '\nLaunch:', command, '\nSetup log:', log)
            progress(5, 'Application ready', 'Your environments, databases and run folders are preserved')
            if args.result_file:
                path = Path(args.result_file)
                temporary = path.with_suffix('.tmp')
                temporary.write_text(json.dumps({'python': str(python), 'command': str(command), 'log': str(log)}))
                os.replace(temporary, path)
    finally:
        lock.rmdir()
    if not args.no_launch:
        return subprocess.call([str(command), 'serve'])
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, KeyError, StopIteration) as exc:
        print('Setup stopped:', exc, file=sys.stderr)
        raise SystemExit(1)
