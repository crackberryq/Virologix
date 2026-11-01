"""Small durable workspace. SQLite transactions coordinate the UI and worker."""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import uuid
from platformdirs import user_data_dir


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def workspace(path=None):
    return Path(path or os.environ.get("VIRALOGIX_HOME") or user_data_dir("viralogix")).expanduser().resolve()


def identifier(prefix):
    return prefix + "-" + uuid.uuid4().hex[:12]


class Store:
    def __init__(self, home=None):
        self.home = workspace(home)
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        for name in ("logs", "runs", "sources", "controllers", "envs", "resources"):
            (self.home / name).mkdir(exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS items (
                  kind TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL,
                  PRIMARY KEY(kind,id));
                CREATE TABLE IF NOT EXISTS jobs (
                  id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL,
                  status TEXT NOT NULL, created TEXT NOT NULL, started TEXT,
                  finished TEXT, error TEXT, cancel INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS job_queue (
                  job_id TEXT PRIMARY KEY, position INTEGER NOT NULL,
                  held INTEGER NOT NULL DEFAULT 0 CHECK(held IN (0,1)));
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.home / "workspace.sqlite3", timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def put(self, kind, key, value):
        with self.connect() as db:
            db.execute("INSERT INTO items VALUES (?,?,?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body",
                       (kind, key, json.dumps(value)))
        return value

    def get(self, kind, key, default=None):
        with self.connect() as db:
            row = db.execute("SELECT body FROM items WHERE kind=? AND id=?", (kind, key)).fetchone()
        return json.loads(row[0]) if row else default

    def all(self, kind):
        with self.connect() as db:
            rows = db.execute("SELECT body FROM items WHERE kind=? ORDER BY rowid DESC", (kind,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def register_run(self, run):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT body FROM items WHERE kind='installs' AND id=?", (run['installation'],)).fetchone()
            installed = json.loads(row[0]) if row else {}
            if not installed.get('ready') or installed.get('version', {}).get('commit') != run['commit']:
                raise ValueError('The installation changed or was removed while creating this draft. Refresh and try again.')
            db.execute("INSERT INTO items VALUES ('runs',?,?)", (run['id'], json.dumps(run)))

    def activate_installation(self, key):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT body FROM items WHERE kind='installs' AND id=?", (key,)).fetchone()
            item = json.loads(row[0]) if row else {}
            if not item.get('ready'):
                raise ValueError('This installation is no longer ready. Refresh the installation list.')
            db.execute("INSERT INTO items VALUES ('settings',?,?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body",
                       ('active-' + item['tool'], json.dumps(key)))

    def submit(self, kind, payload):
        jid = identifier("job")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            owner = os.environ.get('VIRALOGIX_DESKTOP_SESSION')
            if owner:
                import time
                session = db.execute("SELECT body FROM items WHERE kind='desktop_sessions' AND id=?", (owner,)).fetchone()
                state = json.loads(session[0]) if session else {}
                if state.get('phase') != 'ready' or time.time() - state.get('last_seen', 0) > 30:
                    raise ValueError('This desktop session is closing or disconnected. Reopen Virologix before starting work.')
            if kind in {'check', 'environments', 'database_download'} and payload.get('installation'):
                if not db.execute("SELECT 1 FROM items WHERE kind='installs' AND id=?", (payload['installation'],)).fetchone():
                    raise ValueError('This installation was removed. Refresh before starting maintenance.')
            if kind == 'workflow':
                from .variants import lock_active
                if lock_active(db, payload.get('run_id')):
                    raise ValueError('A variant is copying this run. Wait for the snapshot to finish.')
            if db.execute("SELECT 1 FROM jobs WHERE kind LIKE 'flupop_%' AND status IN ('queued','running')").fetchone():
                raise ValueError('Wait for the earlier Virologix task to finish before using the new queue.')
            pending = db.execute("SELECT kind FROM jobs WHERE status IN ('queued','running')").fetchall()
            if any(row[0] == "app_update" for row in pending):
                raise ValueError("A Virologix update is queued or running. Wait for it to finish and restart the app.")
            if kind == "app_update":
                from .queue import control
                if control(db)['paused']:
                    raise ValueError('Resume the queue before installing a Virologix update.')
            if kind == "app_update" and pending:
                raise ValueError("Finish or cancel queued/running jobs before updating Virologix.")
            if kind == 'workstation' and any(row[0] == 'workstation' for row in pending):
                raise ValueError('A workstation check is already queued or running.')
            if kind == "workflow":
                visible = db.execute("SELECT body FROM items WHERE kind='run_visibility' AND id=?", (payload["run_id"],)).fetchone()
                if visible and json.loads(visible[0]).get("archived"):
                    raise ValueError("Restore this run from Archived before starting a job.")
                active = db.execute("SELECT payload FROM jobs WHERE kind='workflow' AND status IN ('queued','running')").fetchall()
                if any(json.loads(row[0]).get("run_id") == payload["run_id"] for row in active):
                    raise ValueError("This run already has a queued or active job")
            if kind == "database_download":
                active = db.execute("SELECT payload FROM jobs WHERE kind='database_download' AND status IN ('queued','running')").fetchall()
                if any(json.loads(row[0]).get("id") == payload["id"] for row in active):
                    raise ValueError("This database download is already queued or running")
            db.execute("INSERT INTO jobs(id,kind,payload,status,created) VALUES (?,?,?,'queued',?)",
                       (jid, kind, json.dumps(payload), now()))
            if owner:
                db.execute("INSERT INTO items VALUES ('job_owners',?,?)", (jid, json.dumps(owner)))
            position = max(db.execute('SELECT COALESCE(MAX(position),0) FROM job_queue').fetchone()[0],
                           db.execute('SELECT MAX(rowid) FROM jobs').fetchone()[0]) + 1
            db.execute('INSERT INTO job_queue VALUES (?,?,0)', (jid, position))
        return jid

    def jobs(self):
        with self.connect() as db:
            rows = db.execute("SELECT j.*,COALESCE(q.held,0) AS held,COALESCE(q.position,j.rowid) AS queue_position FROM jobs j LEFT JOIN job_queue q ON q.job_id=j.id ORDER BY j.rowid DESC").fetchall()
        return [dict(row, payload=json.loads(row["payload"])) for row in rows]

    def job(self, jid):
        with self.connect() as db:
            row = db.execute("SELECT j.*,COALESCE(q.held,0) AS held,COALESCE(q.position,j.rowid) AS queue_position FROM jobs j LEFT JOIN job_queue q ON q.job_id=j.id WHERE j.id=?", (jid,)).fetchone()
        return dict(row, payload=json.loads(row["payload"])) if row else None

    def update_job(self, jid, **fields):
        if not fields or not set(fields) <= {"status", "started", "finished", "error", "cancel"}:
            raise ValueError("Invalid job update")
        with self.connect() as db:
            db.execute("UPDATE jobs SET " + ",".join(k + "=?" for k in fields) + " WHERE id=?",
                       (*fields.values(), jid))

    def claim(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            from .queue import control
            if control(db)['paused']:
                return None
            row = db.execute("SELECT j.id FROM jobs j LEFT JOIN job_queue q ON q.job_id=j.id "
                             "WHERE j.status='queued' AND j.cancel=0 AND COALESCE(q.held,0)=0 "
                             "ORDER BY COALESCE(q.position,j.rowid),j.rowid LIMIT 1").fetchone()
            if not row:
                return None
            db.execute("UPDATE jobs SET status='running',started=? WHERE id=?", (now(), row[0]))
        return self.job(row[0])

    def queue_snapshot(self):
        from .queue import snapshot
        with self.connect() as db:
            db.execute('BEGIN')
            return snapshot(db)

    def cancel(self, jid):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT kind,status FROM jobs WHERE id=?", (jid,)).fetchone()
            if row and row[0] == "app_update" and row[1] == "running":
                raise ValueError("An application update cannot be cancelled while it is installing. Wait for its result.")
            db.execute("UPDATE jobs SET cancel=1,status=CASE WHEN status='queued' THEN 'cancelled' ELSE status END WHERE id=? AND status IN ('queued','running')", (jid,))

    def log_path(self, jid):
        if not isinstance(jid,str) or not (jid.startswith("job-") and jid[4:].isalnum() or jid.startswith("flupop-") and jid[7:].isalnum()):
            raise ValueError("Invalid job ID")
        return self.home / "logs" / (jid + ".log")

