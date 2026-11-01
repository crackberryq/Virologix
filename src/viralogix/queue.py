"""Transactional waiting-order controls; held jobs remain queued for all safety guards."""
from __future__ import annotations

import hashlib
import json

from .store import now


def control(db):
    row = db.execute("SELECT body FROM items WHERE kind='queue' AND id='control'").fetchone()
    return json.loads(row[0]) if row else {'paused': False, 'generation': 0}


def save_control(db, value):
    value = {**value, 'generation': value.get('generation', 0) + 1, 'updated_at': now()}
    db.execute("INSERT INTO items VALUES ('queue','control',?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body",
               (json.dumps(value),))


def snapshot(db):
    state = control(db)
    waiting = [dict(row) for row in db.execute(
        "SELECT j.id,j.kind,COALESCE(q.position,j.rowid) AS position,COALESCE(q.held,0) AS held "
        "FROM jobs j LEFT JOIN job_queue q ON q.job_id=j.id "
        "WHERE j.status='queued' AND j.cancel=0 ORDER BY position,j.rowid")]
    running = [dict(row) for row in db.execute("SELECT id,kind,cancel FROM jobs WHERE status='running' ORDER BY rowid")]
    data = {'control': state, 'waiting': waiting, 'running': running}
    revision = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    return {'paused': bool(state['paused']), 'revision': revision, 'waiting': waiting, 'running': running,
            'pause_reason': state.get('pause_reason'), 'recovered': state.get('recovered', []),
            'recovered_at': state.get('recovered_at'),
            'held_count': sum(bool(j['held']) for j in waiting),
            'update_active': any(j['kind'] == 'app_update' for j in waiting + running)}


def change(store, action, expected, jid=None):
    if not isinstance(action, str) or action not in {'pause', 'resume', 'hold', 'release', 'up', 'down'}:
        raise ValueError('Choose a queue control action.')
    if not isinstance(expected, str):
        raise ValueError('Refresh the queue before changing it.')
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        current = snapshot(db)
        if current['revision'] != expected:
            raise ValueError('The queue changed. Review the refreshed order and try again.')
        if current['update_active']:
            raise ValueError('Queue controls are unavailable during an application update.')
        state = control(db)
        if action in {'pause', 'resume'}:
            state.update(paused=action == 'pause', pause_reason='user' if action == 'pause' else None)
        else:
            if not isinstance(jid, str):
                raise ValueError('Choose a waiting job.')
            waiting = current['waiting']
            index = next((i for i, row in enumerate(waiting) if row['id'] == jid), None)
            if index is None:
                raise ValueError('Only waiting jobs can be held, released or reordered.')
            if action in {'up', 'down'}:
                other = index + (-1 if action == 'up' else 1)
                if not 0 <= other < len(waiting):
                    raise ValueError('This job is already at the end of the waiting order.')
                waiting[index], waiting[other] = waiting[other], waiting[index]
            else:
                waiting[index]['held'] = int(action == 'hold')
            for position, row in enumerate(waiting, 1):
                db.execute('INSERT INTO job_queue VALUES (?,?,?) ON CONFLICT(job_id) DO UPDATE '
                           'SET position=excluded.position,held=excluded.held', (row['id'], position, row['held']))
        save_control(db, state)
        return snapshot(db)


def recover_interrupted(store):
    """Called only after the worker owns the OS lock, including surviving children."""
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        ids = [row[0] for row in db.execute("SELECT id FROM jobs WHERE status='running' ORDER BY rowid")]
        if ids:
            stamp = now()
            db.execute("UPDATE jobs SET status='interrupted',finished=?,error=? WHERE status='running'",
                       (stamp, 'Worker ended unexpectedly. Inspect outputs and logs before resuming.'))
            state = control(db)
            state.update(paused=True, pause_reason='interruption', recovered=ids, recovered_at=stamp)
            save_control(db, state)
        return ids
