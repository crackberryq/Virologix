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


    def jobs(self):
        with self.connect() as db:
            rows = db.execute("SELECT j.*,COALESCE(q.held,0) AS held,COALESCE(q.position,j.rowid) AS queue_position FROM jobs j LEFT JOIN job_queue q ON q.job_id=j.id ORDER BY j.rowid DESC").fetchall()
        return [dict(row, payload=json.loads(row["payload"])) for row in rows]

    def job(self, jid):
        with self.connect() as db:
            row = db.execute("SELECT j.*,COALESCE(q.held,0) AS held,COALESCE(q.position,j.rowid) AS queue_position FROM jobs j LEFT JOIN job_queue q ON q.job_id=j.id WHERE j.id=?", (jid,)).fetchone()
        return dict(row, payload=json.loads(row["payload"])) if row else None


    def cancel(self, jid):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT kind,status FROM jobs WHERE id=?", (jid,)).fetchone()
            if row and row[0] == "app_update" and row[1] == "running":
                raise ValueError("An application update cannot be cancelled while it is installing. Wait for its result.")
            db.execute("UPDATE jobs SET cancel=1,status=CASE WHEN status='queued' THEN 'cancelled' ELSE status END WHERE id=? AND status IN ('queued','running')", (jid,))

