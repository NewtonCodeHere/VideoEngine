"""
SQLite database initialization and job tracking.
Uses a simple thread-safe connection pool via threading.local.
"""
from __future__ import annotations

import sqlite3
import threading
import json
import time
from pathlib import Path
from typing import Optional

_local = threading.local()


def _get_conn(db_path: Path) -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id              TEXT PRIMARY KEY,
    idempotency_key TEXT UNIQUE,
    status          TEXT NOT NULL DEFAULT 'queued',
    progress        INTEGER NOT NULL DEFAULT 0,
    input_mode      TEXT NOT NULL DEFAULT 'pdf',
    settings        TEXT NOT NULL DEFAULT '{}',
    result          TEXT,
    error           TEXT,
    warnings        TEXT NOT NULL DEFAULT '[]',
    created_at      REAL NOT NULL,
    started_at      REAL,
    finished_at     REAL
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_idempotency ON jobs(idempotency_key);
"""


def init_db(db_path: Path) -> None:
    conn = _get_conn(db_path)
    conn.executescript(SCHEMA)
    conn.commit()


def create_job(
    db_path: Path,
    job_id: str,
    idempotency_key: Optional[str],
    input_mode: str,
    settings: dict,
) -> dict:
    conn = _get_conn(db_path)
    now = time.time()
    conn.execute(
        """INSERT INTO jobs
           (id, idempotency_key, status, progress, input_mode, settings, created_at)
           VALUES (?, ?, 'queued', 0, ?, ?, ?)""",
        (job_id, idempotency_key, input_mode, json.dumps(settings), now),
    )
    conn.commit()
    return get_job(db_path, job_id)


def get_job(db_path: Path, job_id: str) -> Optional[dict]:
    conn = _get_conn(db_path)
    row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        return None
    return _row_to_dict(row)


def get_job_by_idempotency_key(db_path: Path, key: str) -> Optional[dict]:
    conn = _get_conn(db_path)
    row = conn.execute(
        "SELECT * FROM jobs WHERE idempotency_key=?", (key,)
    ).fetchone()
    if row is None:
        return None
    return _row_to_dict(row)


def update_job(
    db_path: Path,
    job_id: str,
    *,
    status: Optional[str] = None,
    progress: Optional[int] = None,
    result: Optional[dict] = None,
    error: Optional[str] = None,
    warnings: Optional[list] = None,
    started_at: Optional[float] = None,
    finished_at: Optional[float] = None,
) -> None:
    fields, values = [], []
    if status is not None:
        fields.append("status=?"); values.append(status)
    if progress is not None:
        fields.append("progress=?"); values.append(progress)
    if result is not None:
        fields.append("result=?"); values.append(json.dumps(result))
    if error is not None:
        fields.append("error=?"); values.append(error)
    if warnings is not None:
        fields.append("warnings=?"); values.append(json.dumps(warnings))
    if started_at is not None:
        fields.append("started_at=?"); values.append(started_at)
    if finished_at is not None:
        fields.append("finished_at=?"); values.append(finished_at)
    if not fields:
        return
    values.append(job_id)
    conn = _get_conn(db_path)
    conn.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id=?", values)
    conn.commit()


def count_running_jobs(db_path: Path) -> int:
    conn = _get_conn(db_path)
    row = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE status IN ('queued', 'running')"
    ).fetchone()
    return row[0]


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    for key in ("settings", "result", "warnings"):
        if d.get(key):
            try:
                d[key] = json.loads(d[key])
            except (json.JSONDecodeError, TypeError):
                pass
    return d
