"""Local desktop supervisor protocol. Never terminate a WSL distribution.

The Windows owner controls a dedicated browser profile. Jobs carry the session
identity in SQLite; shared workers use the existing cooperative cancellation.
"""
import json
import os
from pathlib import Path
import re
import time
import uuid


ENV = 'VIRALOGIX_DESKTOP_SESSION'
LEASE_SECONDS = 30


def atomic(path, value):
    path = Path(path)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value), encoding='utf-8')
    os.replace(temporary, path)


def read(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {}


def owner_cancelled(store, jid):
    owner = store.get('job_owners', jid)
    if not owner:
        return False
    return session_stopped(store, owner)


def session_stopped(store, owner):
    if not owner:
        return False
    session = store.get('desktop_sessions', owner)
    return (not session or session.get('phase') in {'stopping', 'stopped'}
            or time.time() - session.get('last_seen', 0) > LEASE_SECONDS)


def request_browser(store):
    key = os.environ.get(ENV)
    if not key:
        return False
    state = store.get('desktop_sessions', key)
    if not state or state.get('phase') != 'ready':
        raise ValueError('The desktop session is stopping or unavailable.')
    store.put('desktop_browser', key, uuid.uuid4().hex)
    return True


class Session:
    def __init__(self, store, directory, key):
        if not re.fullmatch(r'[a-f0-9]{32}', key or ''):
            raise ValueError('Invalid desktop session identity')
        self.store, self.key, self.root = store, key, Path(directory).resolve()
        if not self.root.is_dir():
            raise ValueError('Desktop control directory is missing')
        self.started = time.time()
        self.nonce = None
        self.phase = 'starting'
        self.reason = ''
        self.publish('')

    def jobs(self):
        with self.store.connect() as db:
            rows = db.execute("SELECT j.* FROM jobs j JOIN items i ON i.kind='job_owners' AND i.id=j.id "
                              "WHERE i.body=? AND j.status IN ('queued','running')", (json.dumps(self.key),)).fetchall()
        return [dict(row) for row in rows]

    def gate(self, phase):
        self.phase = phase
        self.store.put('desktop_sessions', self.key, {'phase': phase, 'last_seen': time.time()})

    def stop(self, reason='Window closed'):
        # Same SQLite write boundary used by submit: after gating, a racing UI
        # cannot sneak in another job between cancellation and server shutdown.
        self.reason = reason
        self.gate('stopping')
        for job in self.jobs():
            if job['kind'] == 'app_update' and job['status'] == 'running':
                continue  # Never interrupt pip halfway through replacement.
            self.store.cancel(job['id'])

    def publish(self, url):
        self.gate(self.phase)
        jobs = self.jobs()
        atomic(self.root / 'status.json', {'session': self.key, 'phase': self.phase, 'url': url,
            'jobs': len(jobs), 'reason': self.reason,
            'installing_update': any(j['kind'] == 'app_update' and j['status'] == 'running' for j in jobs),
            'browser_request': self.store.get('desktop_browser', self.key)})

    def tick(self, url, ready):
        heartbeat = read(self.root / 'heartbeat.json')
        alive = heartbeat.get('session') == self.key and time.time() - heartbeat.get('time', 0) < LEASE_SECONDS
        if not alive and time.time() - self.started > LEASE_SECONDS:
            self.stop('Desktop supervisor disconnected; stopping owned work')
        request = read(self.root / 'request.json')
        if request.get('session') == self.key and request.get('nonce') != self.nonce:
            self.nonce = request.get('nonce')
            action = request.get('action')
            if action == 'close' and self.phase != 'stopping':
                self.gate('confirming')
                if not self.jobs():
                    self.stop()
            elif action == 'confirm_close':
                self.stop()
            elif action == 'reopen' and self.phase == 'confirming':
                self.gate('ready' if ready else 'starting')
        if self.phase == 'starting' and ready:
            self.phase = 'ready'
        if self.phase == 'stopping':
            self.stop(self.reason)
        self.publish(url)
        return self.phase == 'stopping' and not self.jobs()

    def finish(self, url):
        self.phase = 'stopped'
        self.publish(url)
