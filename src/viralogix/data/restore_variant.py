"""Restore a verified isolated checkpoint. This program runs no analysis tools."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile


def sha(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def identity(path):
    if path.is_symlink():
        raise ValueError('Linked cache files are not supported')
    if path.is_file():
        return {'kind': 'file', 'size': path.stat().st_size, 'sha256': sha(path)}
    if not path.is_dir():
        raise ValueError('Missing checkpoint: ' + str(path))
    files = {}
    for item in sorted(path.rglob('*')):
        if item.is_symlink():
            raise ValueError('Linked cache contents are not supported')
        if item.is_file():
            files[item.relative_to(path).as_posix()] = {'size': item.stat().st_size, 'sha256': sha(item)}
        elif not item.is_dir():
            raise ValueError('Invalid cache contents')
    return {'kind': 'directory', 'files': files}


def restore(manifest, index):
    manifest = Path(manifest).absolute()
    root = manifest.parent
    record = json.loads(manifest.read_text())
    if record.get('schema') != 1:
        raise ValueError('Unsupported checkpoint schema')
    entry = record['checkpoints'][int(index)]
    for row in entry['outputs']:
        source, target = Path(row['cache']), Path(row['path'])
        if not source.is_relative_to(root / 'variant-cache') or not target.is_relative_to(root / 'outputs'):
            raise ValueError('Checkpoint path is outside this run')
        for path in (source, target):
            if any(p.is_symlink() for p in (path, *path.parents)):
                raise ValueError('Linked checkpoint paths are not allowed')
        if identity(source) != row['identity']:
            raise ValueError('Checkpoint bytes changed: ' + str(source))
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix='.viralogix-restore-', dir=target.parent))
        try:
            staged = staging / 'output'
            if row['identity']['kind'] == 'directory':
                shutil.copytree(source, staged)
            else:
                shutil.copy2(source, staged)
            if identity(staged) != row['identity']:
                raise ValueError('Checkpoint copy failed verification')
            if target.is_dir():
                shutil.rmtree(target)
            os.replace(staged, target)
        finally:
            shutil.rmtree(staging)
    print('Inherited checkpoint:', entry['rule'], 'from', record['parent'])


if __name__ == '__main__':
    restore(sys.argv[1], int(sys.argv[2]))
