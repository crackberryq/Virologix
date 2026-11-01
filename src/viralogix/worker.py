"""One OS lock serializes setup, native workflows and shared environment writes."""
import argparse
import fcntl
import time
import traceback
from .store import Store, now
from .engine import Cancelled, Context, execute
from .runtime import environment_lock
from .updates import assert_current


def work(store, desktop_owner=None):
    from .desktop import session_stopped
    with (store.home / "worker.lock").open("a+") as lock:
        # Waiting launchers also close the idle-shutdown race: a job submitted as
        # the previous worker exits always has a worker waiting to acquire the lock.
        while True:
            if session_stopped(store, desktop_owner):
                return
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                time.sleep(.25)
        # Native children inherit the lock. Recovery cannot overlap a surviving child.
        from .queue import recover_interrupted
        recover_interrupted(store)
        idle = 0
        processed = False
        while idle < 20:
            if session_stopped(store, desktop_owner):
                return
            job = store.claim()
            if not job:
                if not processed:
                    return
                idle += 1
                time.sleep(0.25)
                continue
            idle = 0
            processed = True
            ctx = Context(store, job, lock.fileno())
            try:
                ctx.check_cancel()
                ctx.write("Virologix started " + now())
                with environment_lock(exclusive=job["kind"] == "app_update") as environment_fd:
                    ctx.lock_fds = (lock.fileno(), environment_fd)
                    assert_current(store)
                    execute(ctx)
                ctx.check_cancel()
                store.update_job(job["id"], status="succeeded", finished=now())
            except Cancelled as exc:
                ctx.write(str(exc))
                store.update_job(job["id"], status="cancelled", finished=now(), error=str(exc))
            except Exception as exc:
                ctx.write(traceback.format_exc())
                store.update_job(job["id"], status="failed", finished=now(), error=str(exc))
            finally:
                ctx.observe("finish", store.job(job["id"])["status"])
                ctx.log.close()
            if job["kind"] == "app_update":
                # Never claim more work with modules loaded before pip replaced them.
                return


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", required=True)
    parser.add_argument('--desktop-owner')
    args = parser.parse_args()
    work(Store(args.home), args.desktop_owner)
