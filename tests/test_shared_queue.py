"""Queue controls are atomic, persistent, and never mutate saved job payloads."""
import copy
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time

import pytest

from viralogix import queue
from viralogix.store import Store, now
from viralogix.ui_backend import dispatch, snapshot
from viralogix import updates


def change(store, action, jid=None):
    return queue.change(store, action, store.queue_snapshot()['revision'], jid)


def test_legacy_jobs_keep_fifo_without_rewriting_payloads(tmp_path):
    home = tmp_path / 'legacy'
    home.mkdir()
    with sqlite3.connect(home / 'workspace.sqlite3') as db:
        db.execute('CREATE TABLE jobs (id TEXT PRIMARY KEY,kind TEXT,payload TEXT,status TEXT,created TEXT,started TEXT,finished TEXT,error TEXT,cancel INTEGER DEFAULT 0)')
        for key in ['job-first', 'job-second']:
            db.execute("INSERT INTO jobs(id,kind,payload,status,created) VALUES (?,'smoke',?,'queued',?)",
                       (key, json.dumps({'custom': key}), now()))
    store = Store(home)
    assert [j['id'] for j in store.queue_snapshot()['waiting']] == ['job-first', 'job-second']
    third = store.submit('smoke', {'custom': 'new'})
    assert [store.claim()['id'] for _ in range(3)] == ['job-first', 'job-second', third]
    assert store.job('job-first')['payload'] == {'custom': 'job-first'}
    assert store.claim() is None


def test_pause_survives_reopen_and_covers_future_jobs(tmp_path):
    store = Store(tmp_path)
    first = store.submit('smoke', {})
    assert store.claim()['id'] == first
    change(store, 'pause')
    second = store.submit('smoke', {'retain': [1, 2]})
    store = Store(tmp_path)
    assert store.queue_snapshot()['paused']
    assert store.claim() is None
    assert store.job(first)['status'] == 'running' and not store.job(first)['cancel']
    store.update_job(first, status='succeeded', finished=now())
    change(store, 'resume')
    assert store.claim()['id'] == second
    assert store.job(first)['status'] == 'succeeded'


def test_holds_and_order_persist_and_do_not_change_payloads(tmp_path):
    store = Store(tmp_path)
    ids = [store.submit('smoke', {'order': i}) for i in range(3)]
    original = {j['id']: j['payload'] for j in store.jobs()}
    change(store, 'hold', ids[0])
    change(store, 'up', ids[2])
    change(store, 'up', ids[2])
    state = Store(tmp_path).queue_snapshot()
    assert [j['id'] for j in state['waiting']] == [ids[2], ids[0], ids[1]]
    assert state['held_count'] == 1
    assert store.claim()['id'] == ids[2]
    assert store.claim()['id'] == ids[1]
    assert store.claim() is None
    change(store, 'pause')
    change(store, 'release', ids[0])
    assert store.claim() is None  # Releasing a hold never resumes the global queue.
    change(store, 'resume')
    assert store.claim()['id'] == ids[0]
    assert {j['id']: j['payload'] for j in store.jobs()} == original


def test_new_jobs_append_after_custom_order(tmp_path):
    store = Store(tmp_path)
    first, second = [store.submit('smoke', {}) for _ in range(2)]
    change(store, 'up', second)
    third = store.submit('smoke', {})
    assert [store.claim()['id'] for _ in range(3)] == [second, first, third]


@pytest.mark.parametrize('mutation', ['claim', 'submit', 'cancel', 'hold', 'pause', 'aba'])
def test_stale_controls_cannot_overwrite_new_queue_state(tmp_path, mutation):
    store = Store(tmp_path)
    first, second = [store.submit('smoke', {}) for _ in range(2)]
    revision = store.queue_snapshot()['revision']
    if mutation == 'claim': store.claim()
    elif mutation == 'submit': store.submit('smoke', {})
    elif mutation == 'cancel': store.cancel(first)
    elif mutation == 'hold': change(store, 'hold', first)
    else:
        change(store, 'pause')
        if mutation == 'aba': change(store, 'resume')
    before = store.queue_snapshot()
    with pytest.raises(ValueError, match='queue changed'):
        queue.change(store, 'up', revision, second)
    assert store.queue_snapshot() == before


@pytest.mark.parametrize('state', ['running', 'succeeded', 'failed', 'cancelled', 'interrupted'])
def test_only_waiting_jobs_can_be_held_or_reordered(tmp_path, state):
    store = Store(tmp_path)
    jid = store.submit('smoke', {})
    store.update_job(jid, status=state)
    for action in ['hold', 'release', 'up', 'down']:
        with pytest.raises(ValueError, match='Only waiting'):
            change(store, action, jid)
    assert store.job(jid)['status'] == state


def test_invalid_controls_and_order_edges_are_rejected(tmp_path):
    store = Store(tmp_path)
    jid = store.submit('smoke', {})
    for action in ('up', 'down'):
        with pytest.raises(ValueError, match='end of'):
            change(store, action, jid)
    for action, revision, key in [([], 'x', jid), ('other', 'x', jid), ('hold', None, jid), ('hold', store.queue_snapshot()['revision'], [])]:
        with pytest.raises(ValueError): queue.change(store, action, revision, key)


def test_held_work_preserves_update_duplicate_and_archive_guards(tmp_path):
    store = Store(tmp_path)
    run = 'run-fixture'
    job = store.submit('workflow', {'run_id': run, 'action': 'run'})
    change(store, 'hold', job)
    with pytest.raises(ValueError, match='already has'):
        store.submit('workflow', {'run_id': run, 'action': 'run'})
    with pytest.raises(ValueError, match='Finish'):
        store.submit('app_update', {})
    from viralogix.runs import archive_runs
    store.put('runs', run, {'id': run})
    with pytest.raises(ValueError):
        archive_runs(store, [run], True)
    store.cancel(job)
    assert store.job(job)['status'] == 'cancelled'
    change(store, 'pause')
    assert not updates.status(store)['can_install']
    with pytest.raises(ValueError, match='Resume the queue'):
        store.submit('app_update', {})
    change(store, 'resume')
    update = store.submit('app_update', {})
    for action in ('pause', 'hold', 'up'):
        with pytest.raises(ValueError, match='application update'):
            change(store, action, update)
    assert store.claim()['id'] == update
    with pytest.raises(ValueError, match='cannot be cancelled'):
        store.cancel(update)


def test_claim_and_hold_race_has_one_consistent_outcome(tmp_path):
    store = Store(tmp_path)
    jid = store.submit('smoke', {})
    revision = store.queue_snapshot()['revision']
    barrier = threading.Barrier(2)
    outcome = {}
    def hold():
        barrier.wait()
        try:
            queue.change(store, 'hold', revision, jid)
            outcome['held'] = True
        except ValueError:
            outcome['held'] = False
    thread = threading.Thread(target=hold)
    thread.start()
    barrier.wait()
    claimed = store.claim()
    thread.join()
    if outcome['held']:
        assert claimed is None and store.job(jid)['held']
    else:
        assert claimed['id'] == jid and store.job(jid)['status'] == 'running' and not store.job(jid)['held']


def test_dispatch_releases_and_resume_launch_worker_without_replaying_actions(tmp_path, monkeypatch):
    from viralogix.ui_backend import handle_request
    store = Store(tmp_path)
    jid = store.submit('smoke', {})
    launches = []
    monkeypatch.setattr('viralogix.ui_backend.launch_worker', lambda s: launches.append(s.home))
    change(store, 'pause')
    change(store, 'hold', jid)
    dispatch(store, 'queue_control', {'action': 'release', 'id': jid, 'revision': store.queue_snapshot()['revision']})
    assert not launches and store.queue_snapshot()['paused']
    request = {'id': 'unique', 'kind': 'queue_control', 'payload': {'action': 'resume', 'revision': store.queue_snapshot()['revision']}}
    session = {}
    assert handle_request(store, request, session)['ok']
    assert handle_request(store, request, session)['ok']
    assert launches == [store.home]
    assert snapshot(store)['queue'] == store.queue_snapshot()
    change(store, 'hold', jid)
    def fail(_): raise OSError('worker fixture')
    monkeypatch.setattr('viralogix.ui_backend.launch_worker', fail)
    result = dispatch(store, 'queue_control', {'action': 'release', 'id': jid, 'revision': store.queue_snapshot()['revision']})
    assert 'change saved' in result['message'] and not store.job(jid)['held']


WORKER_FIXTURE = '''
import sys
from pathlib import Path
from viralogix import worker
from viralogix.store import Store

def execute(ctx):
    p=ctx.job['payload']
    ctx.command([sys.executable, '-c', 'import time,sys; from pathlib import Path; time.sleep(float(sys.argv[1])); Path(sys.argv[2]).write_text("finished")', str(p.get('delay',0)), p['marker']])
worker.execute=execute
worker.work(Store(sys.argv[1]))
'''


def start_worker(store):
    return subprocess.Popen([sys.executable, '-c', WORKER_FIXTURE, str(store.home)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def wait_for(condition, timeout=10):
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline: pytest.fail('Timed out waiting for software fixture')
        time.sleep(.05)


def test_real_worker_finishes_current_then_stops_and_keeps_holds(tmp_path):
    store = Store(tmp_path / 'workspace')
    ids = [store.submit('smoke', {'delay': 1 if i == 0 else 0, 'marker': str(tmp_path / str(i))}) for i in range(3)]
    change(store, 'hold', ids[2])
    proc = start_worker(store)
    try:
        wait_for(lambda: store.job(ids[0])['status'] == 'running')
        change(store, 'pause')
        out, err = proc.communicate(timeout=15)
        assert proc.returncode == 0, out + err
        assert (tmp_path / '0').read_text() == 'finished'
        assert store.job(ids[0])['status'] == 'succeeded' and not store.job(ids[0])['cancel']
        assert all(store.job(j)['status'] == 'queued' for j in ids[1:])
        assert not (tmp_path / '1').exists() and not (tmp_path / '2').exists()
        before = store.job(ids[0])
        change(store, 'resume')
        proc = start_worker(store)
        out, err = proc.communicate(timeout=15)
        assert proc.returncode == 0, out + err
        assert store.job(ids[1])['status'] == 'succeeded'
        assert store.job(ids[2])['status'] == 'queued' and not (tmp_path / '2').exists()
        assert store.job(ids[0]) == before
    finally:
        if proc.poll() is None: proc.kill(); proc.wait()


def test_recovered_interruption_pauses_and_preserves_waiting_order(tmp_path):
    store = Store(tmp_path)
    old = store.submit('smoke', {})
    store.claim()
    queued = [store.submit('smoke', {'marker': str(tmp_path / 'never')}) for _ in range(2)]
    change(store, 'up', queued[1])
    change(store, 'hold', queued[0])
    proc = start_worker(store)
    out, err = proc.communicate(timeout=10)
    assert proc.returncode == 0, out + err
    state = store.queue_snapshot()
    assert state['paused'] and state['pause_reason'] == 'interruption' and state['recovered'] == [old]
    assert [j['id'] for j in state['waiting']] == queued[::-1]
    assert store.job(old)['status'] == 'interrupted'
    assert not (tmp_path / 'never').exists()
    assert store.claim() is None
    assert queue.recover_interrupted(store) == []
    assert store.queue_snapshot() == state


@pytest.mark.parametrize('result', ['failed', 'cancelled'])
def test_stop_after_current_is_kept_when_current_does_not_succeed(tmp_path, monkeypatch, result):
    from types import SimpleNamespace
    from viralogix import worker
    from viralogix.engine import Cancelled
    store = Store(tmp_path)
    first, second = [store.submit('smoke', {}) for _ in range(2)]
    def execute(ctx):
        assert ctx.job['id'] == first
        change(store, 'pause')
        if result == 'cancelled': raise Cancelled('test cancellation')
        raise RuntimeError('test failure')
    monkeypatch.setattr(worker, 'execute', execute)
    monkeypatch.setattr(worker, 'time', SimpleNamespace(sleep=lambda seconds: None))
    worker.work(store)
    assert store.job(first)['status'] == result
    assert store.job(second)['status'] == 'queued'
    assert store.queue_snapshot()['paused']
