"""Verified update handoff between the worker, launcher and open browser tabs."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

from . import __version__


def current_launcher(store):
    key = os.environ.get('VIRALOGIX_LAUNCH_ID')
    item = store.get('launchers', key) if key else None
    if not item or item.get('environment') != sys.prefix or item.get('status') not in {'ready', 'restarting'}:
        return None
    try:
        os.kill(item['pid'], 0)
    except (OSError, KeyError, TypeError):
        return None
    return item


def register(store, url):
    item = {'id': uuid.uuid4().hex, 'pid': os.getpid(), 'version': __version__, 'environment': sys.prefix,
            'url': url, 'started_at': time.time(), 'status': 'starting'}
    store.put('launchers', item['id'], item)
    return item


def mark_ready(store, item):
    item['status'] = 'ready'
    store.put('launchers', item['id'], item)
    state = store.get('settings', 'app-update', {})
    if state.get('status') == 'installed' and state.get('version') == __version__ and state.get('restart_status') == 'restarting' and state.get('restart_pid') == item['pid'] and state.get('environment') == sys.prefix:
        store.put('settings', 'app-update', {**state, 'restart_status': 'ready', 'restarted_at': time.time()})


def pending(store, item):
    state = store.get('settings', 'app-update', {})
    if (state.get('status') != 'installed' or state.get('launcher_id') != item['id']
            or state.get('environment') != sys.prefix or state.get('pip_started_at', 0) <= item['started_at']
            or state.get('restart_status') in {'failed', 'ready'}):
        return None
    job = store.job(state.get('job'))
    if not job or job['kind'] != 'app_update' or job['status'] != 'succeeded':
        return None
    if any(j['status'] in {'queued', 'running'} for j in store.jobs()):
        return None
    return state


def verify_and_mark(store, item, state):
    code = ('import importlib.metadata as m; import viralogix, streamlit; '
            f'assert m.version("viralogix") == {state["version"]!r}; '
            f'assert viralogix.__version__ == {state["version"]!r}')
    try:
        subprocess.run([sys.executable, '-c', code], check=True, timeout=30, capture_output=True, text=True)
    except (OSError, subprocess.SubprocessError) as exc:
        store.put('settings', 'app-update', {**state, 'restart_status': 'failed', 'restart_error': str(exc)})
        return False
    store.put('settings', 'app-update', {**state, 'restart_status': 'restarting', 'restart_pid': item['pid']})
    item['status'] = 'restarting'
    store.put('launchers', item['id'], item)
    return True


def unregister(store, item):
    with store.connect() as db:
        db.execute("DELETE FROM items WHERE kind='launchers' AND id=?", (item['id'],))


def make_app(folder, item):
    """Give each server its own static identity, even while pip replaces package files."""
    root = Path(folder)
    (root / 'static').mkdir()
    (root / 'static/runtime.json').write_text(json.dumps({'id': item['id'], 'version': item['version']}))
    app = root / 'app.py'
    app.write_text("import runpy\nrunpy.run_module('viralogix.app', run_name='__main__')\n")
    return app
