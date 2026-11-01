"""Software-only progress, process observation and per-attempt download contracts."""
import base64
from contextlib import nullcontext
import csv
import importlib.util
import io
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import zipfile

import pytest

from viralogix import telemetry as t
from viralogix.engine import Cancelled, Context
from viralogix.store import Store, now
from viralogix.ui_backend import dispatch, snapshot


def record_job(store, action='run', run_id='run-fixture'):
    jid = store.submit('workflow', {'action': action, 'run_id': run_id})
    store.update_job(jid, status='running')
    store.log_path(jid).touch()
    recorder = t.Recorder(store, store.job(jid))
    return jid, recorder


def point(start=0, end=2, cpu=1, rss=50, observed=1, unavailable=0):
    return dict(start_s=start, end_s=end, cpu_s=cpu, rss_peak_mb=rss,
                processes_peak=2 if observed else None, observed=observed, unavailable=unavailable)


def test_log_progress_handles_parallel_steps_and_checkpoint_replanning():
    p = t.Progress()
    for line in ['localrule alpha:', '    input: retained', '    jobid: 3', '',
                 '\x1b[32mcheckpoint discover:\x1b[0m', '    jobid: 1',
                 'DAG of jobs will be updated after completion.', '1 of 4 steps (25%) done']:
        p.feed(line)
    assert p.value()['active_rules'] == ['alpha', 'discover']
    assert p.value()['percent'] == 25 and p.value()['dynamic_plan']
    p.feed('Finished job 3.')  # Snakemake 9.6
    p.feed('Finished jobid: 1 (Rule: discover)')  # Newer runner
    p.feed('2 of 7 steps (28.57%) done')
    assert p.value()['active_count'] == 0
    assert p.value()['total'] == 7 and p.value()['percent'] == 28.6
    p.feed('3 of 3 steps (100%) done')
    assert p.value()['completed'] == 3 and p.value()['total'] == 3
    for invalid in ['99 of 3 steps (100%) done', '0 of 0 steps (0%) done', '$ 1 of 2 steps (50%) done']:
        p.feed(invalid)
    assert p.value()['completed'] == 3
    off = t.Progress(False)
    off.feed('3 of 3 steps (100%) done')
    assert off.value()['total'] is None and off.value()['source'] == 'not applicable'


def test_log_reader_bounds_truncation_and_never_interprets_clipped_lines(tmp_path, monkeypatch):
    store = Store(tmp_path)
    jid, r = record_job(store)
    path = store.log_path(jid)
    path.write_bytes(b'x' * 9000)
    r.read_log()
    with path.open('ab') as f:
        f.write(b'1 of 2 steps (50%) done\n')
    r.read_log()
    assert r.progress.total is None
    with path.open('ab') as f:
        f.write(b'localrule finish:\n    jobid: 2\n2 of 2 steps (100%) done\n')
    r.read_log()
    assert r.progress.total == 2 and r.progress.active == {'2': 'finish'}
    path.write_text('1 of 3 steps (33%) done\n')
    r.read_log()
    assert r.progress.total == 3 and r.progress.gap and not r.progress.active
    monkeypatch.setattr(t, 'LOG_LIMIT', 128)
    path.write_text('x' * 300 + '\n2 of 3 steps (66.67%) done\n')
    r.read_log()
    assert r.progress.done == 2 and r.progress.gap


def test_sampler_tracks_process_identity_and_excludes_reaped_child_counters(monkeypatch):
    class Process:
        def __init__(self, pid, born, counter, rss):
            self.pid, self.born, self.counter, self.rss = pid, born, counter, rss
            self.error = False
        def is_running(self): return True
        def children(self, recursive): return [child]
        def oneshot(self): return nullcontext()
        def create_time(self): return self.born
        def cpu_times(self):
            if self.error: raise t.psutil.AccessDenied(self.pid)
            return SimpleNamespace(user=self.counter, system=.25, children_user=999, children_system=999)
        def memory_info(self): return SimpleNamespace(rss=self.rss * 1024 ** 2)
    root, child = Process(10, 1, 1, 20), Process(11, 2, 2, 30)
    monkeypatch.setattr(t.psutil, 'Process', lambda pid: root)
    sampler = t.Sampler(10)
    assert sampler.sample() == {'cpu_s': 3.5, 'rss_mb': 50, 'processes': 2}
    root.counter += 1
    child.counter += 2
    assert sampler.sample()['cpu_s'] == 3
    child.born, child.counter = 3, .5  # Same PID, different process.
    assert sampler.sample()['cpu_s'] == .75
    child.error = True
    assert sampler.sample()['rss_mb'] == 20 and sampler.partial
    root.error = True
    assert sampler.sample() is None
    monkeypatch.setattr(t, 'psutil', None)
    assert t.Sampler(10).sample() is None


def test_compaction_preserves_integrals_peaks_and_missing_intervals():
    points = [point(i, i+1, i/10, None if i % 3 == 0 else i,
                    observed=int(i % 3 != 0), unavailable=int(i % 3 == 0)) for i in range(11)]
    result = points
    for _ in range(4): result = t.compact(result)
    assert len(result) == 1
    assert result[0]['start_s'] == 0 and result[0]['end_s'] == 11
    assert result[0]['cpu_s'] == pytest.approx(sum(p['cpu_s'] for p in points))
    assert result[0]['rss_peak_mb'] == 10
    assert result[0]['observed'] == 7 and result[0]['unavailable'] == 4


def test_recorder_is_bounded_and_each_attempt_remains_separate(tmp_path, monkeypatch):
    store = Store(tmp_path)
    store.put('runs', 'run-fixture', {'id': 'run-fixture', 'tool': 'hybas', 'commit': 'a'*40,
              'cores': 3, 'memory_mb': 1024, 'config_sha256': 'c'*64, 'workflow_sha256': 'd'*64})
    jid, recorder = record_job(store)
    clock = [100.0]
    monkeypatch.setattr(t.time, 'monotonic', lambda: clock[0])
    recorder.started = recorder.last = recorder.last_save = clock[0]
    monkeypatch.setattr(t, 'HISTORY_LIMIT', 4)
    recorder.proc = SimpleNamespace(pid=1)
    recorder.sampler = SimpleNamespace(sample=lambda: {'cpu_s': 1, 'rss_mb': 20, 'processes': 2}, partial=False)
    for _ in range(7):
        clock[0] += 2
        recorder.tick()
    recorder.end_command()
    recorder.finish('failed')
    store.update_job(jid, status='failed')
    first = t.inspect(store, jid)
    assert first['summary']['history_compacted'] and len(first['points']) <= 4
    assert first['summary']['observed_cpu_s'] == sum(p['cpu_s'] for p in first['points'])
    assert first['summary']['budget'] == {'cores': 3, 'memory_mb': 1024}
    assert first['summary']['latest'] is None and first['summary']['state'] == 'failed'
    second, retry = record_job(store)
    retry.finish('succeeded')
    assert second != jid and t.inspect(store, jid) == first
    assert store.get('job_telemetry', second)['run_id'] == 'run-fixture'


def test_unavailable_stale_and_interrupted_are_not_zero_or_live(tmp_path):
    store = Store(tmp_path)
    jid, r = record_job(store)
    r.finish('failed')
    record = store.get('job_telemetry', jid)
    assert record['peak_rss_mb'] is None and record['samples'] == 0
    record.update(state='recording', updated_at=now(), latest={'cpu_percent': 99})
    assert t.view(record, store.job(jid))['live']
    record['updated_at'] = '2000-01-01T00:00:00+00:00'
    v = t.view(record, store.job(jid))
    assert v['stale'] and v['latest'] is None
    record['updated_at'] = '2099-01-01T00:00:00+00:00'
    assert not t.view(record, store.job(jid))['live']
    store.update_job(jid, status='interrupted')
    v = t.view(record, store.job(jid))
    assert v['incomplete'] and not v['live']
    assert t.view({'schema': 2, 'id': jid}, store.job(jid)) is None
    old = store.submit('smoke', {})
    with pytest.raises(ValueError, match='No resource record'):
        t.inspect(store, old)


@pytest.mark.parametrize('exit_code', [0, 4])
def test_real_command_preserves_redirected_stdout_and_failure_status(tmp_path, exit_code, monkeypatch):
    store = Store(tmp_path)
    jid = store.submit('smoke', {})
    ctx = Context(store, store.claim())
    monkeypatch.setattr(t, 'INTERVAL', .1)
    target = tmp_path / 'inventory.json'
    try:
        with target.open('w') as output:
            code = 'import time,sys; data=bytearray(1024*1024); print("{\\"ok\\": true}"); time.sleep(.4); sys.exit('+str(exit_code)+')'
            if exit_code:
                with pytest.raises(RuntimeError, match='code 4'):
                    ctx.command([sys.executable, '-c', code], stdout=output)
            else:
                ctx.command([sys.executable, '-c', code], stdout=output)
        assert json.loads(target.read_text()) == {'ok': True}
        assert store.get('processes', jid)['pid'] is None
        ctx.observe('finish', 'failed' if exit_code else 'succeeded')
        record = store.get('job_telemetry', jid)
        assert record['command_count'] == 1 and record['elapsed_s'] >= .4
        assert record['samples'] + record['unavailable_samples'] > 0
        assert record['state'] == ('failed' if exit_code else 'succeeded')
    finally:
        ctx.log.close()


@pytest.mark.parametrize('broken_observer', [False, True])
def test_cancel_still_stops_command_group_when_observation_fails(tmp_path, monkeypatch, broken_observer):
    store = Store(tmp_path)
    jid = store.submit('smoke', {})
    ctx = Context(store, store.claim())
    if broken_observer:
        def fail(*args, **kwargs): raise RuntimeError('observer fixture failure')
        monkeypatch.setattr(ctx.observer, 'tick', fail)
    timer = threading.Timer(.4, lambda: store.cancel(jid))
    timer.start()
    try:
        with pytest.raises(Cancelled):
            ctx.command([sys.executable, '-c', 'import time; time.sleep(60)'])
        assert store.get('processes', jid)['pid'] is None
        if broken_observer:
            assert store.log_path(jid).read_text().count('Resource observation is unavailable') == 1
        else:
            ctx.observe('finish', 'cancelled')
            assert store.get('job_telemetry', jid)['state'] == 'cancelled'
    finally:
        timer.cancel()
        timer.join()
        ctx.log.close()


@pytest.mark.parametrize('status', ['succeeded', 'failed', 'cancelled'])
def test_worker_finalizes_records_and_marks_prior_interrupted_job(tmp_path, monkeypatch, status):
    from viralogix import worker
    store = Store(tmp_path)
    old, recorder = record_job(store)
    recorder.tick(force=True)
    jid = store.submit('smoke', {})
    def execute(ctx):
        if status == 'failed': raise ValueError('software fixture')
        if status == 'cancelled': raise Cancelled('software fixture')
    monkeypatch.setattr(worker, 'execute', execute)
    monkeypatch.setattr(worker, 'assert_current', lambda store: None)
    monkeypatch.setattr(worker, 'environment_lock', lambda exclusive: nullcontext(1))
    monkeypatch.setattr(worker, 'time', SimpleNamespace(sleep=lambda seconds: None))
    worker.work(store)
    assert store.job(jid)['status'] == 'queued'
    assert store.queue_snapshot()['paused']
    from viralogix.queue import change
    change(store, 'resume', store.queue_snapshot()['revision'])
    worker.work(store)
    assert store.job(jid)['status'] == status
    assert t.inspect(store, jid)['summary']['state'] == status
    assert t.inspect(store, old)['summary']['incomplete']


def test_observer_creation_or_persistence_failure_does_not_fail_command(tmp_path, monkeypatch):
    store = Store(tmp_path)
    def fail(*args, **kwargs): raise RuntimeError('software observer failure')
    monkeypatch.setattr(t, 'Recorder', fail)
    jid = store.submit('smoke', {})
    ctx = Context(store, store.claim())
    try:
        ctx.command([sys.executable, '-c', 'print("software fixture completed")'])
        ctx.observe('finish', 'succeeded')
        assert 'software fixture completed' in store.log_path(jid).read_text()
    finally:
        ctx.log.close()


def test_downloads_are_read_only_bounded_and_exclude_logs_commands_and_samples(tmp_path, monkeypatch):
    store = Store(tmp_path)
    jid, r = record_job(store)
    store.log_path(jid).write_text('$ secret-command private-argument\nprivate input names\n')
    r.history = [point(), point(2, 4, 0, None, 0, 1)]
    r.finish('succeeded')
    store.update_job(jid, status='succeeded')
    monkeypatch.setattr('viralogix.updates.assert_current', lambda s: pytest.fail('Read-only downloads must work during update'))
    summary = dispatch(store, 'job_metrics', {'id': jid})['usage']
    json_download = dispatch(store, 'download_metrics', {'id': jid, 'format': 'json'})['download']
    assert json.loads(json_download['text']) == summary
    assert 'secret-command' not in json_download['text'] and 'private input' not in json_download['text']
    bundle = dispatch(store, 'download_metrics', {'id': jid})['download']
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(bundle['base64']))) as archive:
        assert sorted(archive.namelist()) == ['README.txt', 'resource-use.csv', 'resource-use.json']
        assert json.loads(archive.read('resource-use.json')) == summary
        rows = list(csv.DictReader(io.StringIO(archive.read('resource-use.csv').decode())))
        assert rows[0]['cpu_percent_mean'] == '50.0'
        assert rows[1]['cpu_percent_mean'] == '' and rows[1]['peak_process_rss_sum_mb'] == ''
    workspace = snapshot(store)
    assert workspace['jobs'][0]['telemetry']['id'] == jid
    assert 'points' not in workspace['jobs'][0]['telemetry']
    assert not store.all('samples') and not store.all('runs')
    for bad in [None, [], 'job-missing']:
        with pytest.raises(ValueError, match='existing job'): dispatch(store, 'job_metrics', {'id': bad})
    with pytest.raises(ValueError, match='JSON, CSV or ZIP'): t.download(store, jid, 'html')
    monkeypatch.setattr(t, 'RECORD_LIMIT', 10)
    with pytest.raises(ValueError, match='download limit'): t.download(store, jid, 'json')


@pytest.mark.parametrize('bad', [float('nan'), -1, '=HYPERLINK("bad")', True, None])
def test_malformed_history_is_not_exported(tmp_path, bad):
    store = Store(tmp_path)
    jid, r = record_job(store)
    r.history = [point(cpu=bad)]
    r.finish('failed')
    with pytest.raises(ValueError, match='invalid measurement'): t.download(store, jid, 'csv')


def test_sample_free_snakemake_checkpoint_progress(tmp_path):
    if importlib.util.find_spec('snakemake') is None:
        pytest.skip('Snakemake runner tests enabled in CI')
    store = Store(tmp_path / 'workspace')
    jid, _ = record_job(store)
    snakefile = tmp_path / 'Snakefile'
    snakefile.write_text('rule all:\n    input: "done.txt"\n'
        'checkpoint discover:\n    output: "checkpoint.txt"\n    shell: "echo ready > {output}"\n'
        'rule finish:\n    input: lambda wc: checkpoints.discover.get().output[0]\n'
        '    output: "done.txt"\n    shell: "echo done > {output}"\n')
    ctx = Context(store, store.job(jid))
    try:
        ctx.command([sys.executable, '-m', 'snakemake', '--snakefile', str(snakefile),
                     '--directory', str(tmp_path), '--cores', '1', '--scheduler', 'greedy'])
        ctx.observe('finish', 'succeeded')
        progress = store.get('job_telemetry', jid)['progress']
        assert progress['completed'] == progress['total'] == 3
        assert progress['active_count'] == 0 and progress['dynamic_plan']
    except Exception:
        print(store.log_path(jid).read_text())
        raise
    finally:
        ctx.log.close()
