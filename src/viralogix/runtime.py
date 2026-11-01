"""Coordinate package updates with workers sharing this Python environment."""
from contextlib import contextmanager
import hashlib
from pathlib import Path
import sys


@contextmanager
def environment_lock(exclusive=False):
    import fcntl
    from platformdirs import user_cache_dir
    key = hashlib.sha256(str(Path(sys.prefix).resolve()).encode()).hexdigest()[:24]
    directory = Path(user_cache_dir("viralogix")) / "locks"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / (key + ".lock")).open("a+") as lock:
        try:
            fcntl.flock(lock, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another Virologix worker or app update is using this Python environment. Wait for it to finish, then retry.") from None
        yield lock.fileno()
