"""Result storage for TestPilot.

Three tables carry the whole history:

  test_runs    one row per execution of a suite
  test_results one row per test within a run, with artefact paths
  defects      one row per raised defect, linked back to the result that
               produced the evidence

Keeping runs and results separate is what makes trend analytics (flake
rate, pass rate over time, slowest tests) a plain SQL query rather than a
log-scraping exercise.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import RESULTS_DB, ensure_dirs

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS test_runs (
    id            TEXT    PRIMARY KEY,
    suite         TEXT    NOT NULL,
    environment   TEXT    NOT NULL,
    trigger       TEXT    NOT NULL DEFAULT 'manual',
    git_branch    TEXT,
    git_commit    TEXT,
    started_at    TEXT    NOT NULL,
    finished_at   TEXT,
    duration_ms   INTEGER,
    total         INTEGER NOT NULL DEFAULT 0,
    passed        INTEGER NOT NULL DEFAULT 0,
    failed        INTEGER NOT NULL DEFAULT 0,
    skipped       INTEGER NOT NULL DEFAULT 0,
    errors        INTEGER NOT NULL DEFAULT 0,
    exit_status   TEXT,
    notes         TEXT
);

CREATE TABLE IF NOT EXISTS test_results (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT    NOT NULL REFERENCES test_runs(id) ON DELETE CASCADE,
    case_id       TEXT,
    nodeid        TEXT    NOT NULL,
    test_name     TEXT    NOT NULL,
    module        TEXT    NOT NULL,
    layer         TEXT    NOT NULL DEFAULT 'unknown',
    markers       TEXT    NOT NULL DEFAULT '[]',
    outcome       TEXT    NOT NULL CHECK (outcome IN ('passed','failed','skipped','error','xfailed','xpassed')),
    duration_ms   INTEGER NOT NULL DEFAULT 0,
    failure_type  TEXT,
    failure_message TEXT,
    traceback     TEXT,
    stdout        TEXT,
    screenshot_path TEXT,
    trace_path      TEXT,
    request_log     TEXT,
    recorded_at   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS defects (
    id            TEXT    PRIMARY KEY,
    result_id     INTEGER REFERENCES test_results(id) ON DELETE SET NULL,
    run_id        TEXT    REFERENCES test_runs(id) ON DELETE SET NULL,
    title         TEXT    NOT NULL,
    severity      TEXT    NOT NULL CHECK (severity IN ('S1','S2','S3','S4')),
    priority      TEXT    NOT NULL CHECK (priority IN ('P1','P2','P3','P4')),
    status        TEXT    NOT NULL DEFAULT 'NEW'
                          CHECK (status IN ('NEW','TRIAGED','IN_PROGRESS','FIXED','VERIFIED','CLOSED','REJECTED','DEFERRED','REOPENED')),
    component     TEXT,
    classification TEXT,
    body_markdown TEXT NOT NULL,
    evidence      TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS defect_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    defect_id   TEXT NOT NULL REFERENCES defects(id) ON DELETE CASCADE,
    from_status TEXT,
    to_status   TEXT NOT NULL,
    actor       TEXT NOT NULL DEFAULT 'testpilot',
    note        TEXT,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_results_run     ON test_results(run_id);
CREATE INDEX IF NOT EXISTS idx_results_nodeid  ON test_results(nodeid);
CREATE INDEX IF NOT EXISTS idx_results_outcome ON test_results(outcome);
CREATE INDEX IF NOT EXISTS idx_runs_suite      ON test_runs(suite, started_at);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    ensure_dirs()
    path = Path(db_path) if db_path else RESULTS_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=20, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    return conn


@contextmanager
def session(db_path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


# ------------------------------------------------------------- runs ----

def start_run(
    suite: str,
    environment: str,
    trigger: str = "manual",
    git_branch: str | None = None,
    git_commit: str | None = None,
    notes: str | None = None,
    db_path: Path | str | None = None,
) -> str:
    run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    with session(db_path) as conn:
        conn.execute(
            """
            INSERT INTO test_runs (id, suite, environment, trigger, git_branch, git_commit, started_at, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, suite, environment, trigger, git_branch, git_commit, utcnow(), notes),
        )
    return run_id


def record_result(run_id: str, result: dict[str, Any], db_path: Path | str | None = None) -> int:
    with session(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO test_results (
                run_id, case_id, nodeid, test_name, module, layer, markers, outcome, duration_ms,
                failure_type, failure_message, traceback, stdout, screenshot_path, trace_path,
                request_log, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                result.get("case_id"),
                result["nodeid"],
                result.get("test_name") or result["nodeid"].rsplit("::", 1)[-1],
                result.get("module", ""),
                result.get("layer", "unknown"),
                json.dumps(result.get("markers", [])),
                result["outcome"],
                int(result.get("duration_ms", 0)),
                result.get("failure_type"),
                result.get("failure_message"),
                result.get("traceback"),
                result.get("stdout"),
                result.get("screenshot_path"),
                result.get("trace_path"),
                json.dumps(result["request_log"]) if result.get("request_log") else None,
                utcnow(),
            ),
        )
        return int(cursor.lastrowid)


def finish_run(run_id: str, exit_status: str = "completed", db_path: Path | str | None = None) -> dict[str, Any]:
    with session(db_path) as conn:
        tally = conn.execute(
            """
            SELECT
                COUNT(*)                                                   AS total,
                SUM(CASE WHEN outcome IN ('passed','xfailed') THEN 1 ELSE 0 END) AS passed,
                SUM(CASE WHEN outcome = 'failed'  THEN 1 ELSE 0 END)       AS failed,
                SUM(CASE WHEN outcome = 'skipped' THEN 1 ELSE 0 END)       AS skipped,
                SUM(CASE WHEN outcome = 'error'   THEN 1 ELSE 0 END)       AS errors,
                COALESCE(SUM(duration_ms), 0)                              AS duration_ms
            FROM test_results WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
        conn.execute(
            """
            UPDATE test_runs
               SET finished_at = ?, duration_ms = ?, total = ?, passed = ?,
                   failed = ?, skipped = ?, errors = ?, exit_status = ?
             WHERE id = ?
            """,
            (
                utcnow(),
                tally["duration_ms"] or 0,
                tally["total"] or 0,
                tally["passed"] or 0,
                tally["failed"] or 0,
                tally["skipped"] or 0,
                tally["errors"] or 0,
                exit_status,
                run_id,
            ),
        )
        return dict(conn.execute("SELECT * FROM test_runs WHERE id = ?", (run_id,)).fetchone())


def get_run(run_id: str, db_path: Path | str | None = None) -> dict[str, Any] | None:
    with session(db_path) as conn:
        row = conn.execute("SELECT * FROM test_runs WHERE id = ?", (run_id,)).fetchone()
        return dict(row) if row else None


def latest_run(suite: str | None = None, db_path: Path | str | None = None) -> dict[str, Any] | None:
    with session(db_path) as conn:
        if suite:
            row = conn.execute(
                "SELECT * FROM test_runs WHERE suite = ? ORDER BY started_at DESC LIMIT 1", (suite,)
            ).fetchone()
        else:
            row = conn.execute("SELECT * FROM test_runs ORDER BY started_at DESC LIMIT 1").fetchone()
        return dict(row) if row else None


def list_runs(limit: int = 25, suite: str | None = None, db_path: Path | str | None = None) -> list[dict[str, Any]]:
    with session(db_path) as conn:
        if suite:
            rows = conn.execute(
                "SELECT * FROM test_runs WHERE suite = ? ORDER BY started_at DESC LIMIT ?", (suite, limit)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM test_runs ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]


def results_for_run(run_id: str, outcome: str | None = None, db_path: Path | str | None = None) -> list[dict[str, Any]]:
    with session(db_path) as conn:
        if outcome:
            rows = conn.execute(
                "SELECT * FROM test_results WHERE run_id = ? AND outcome = ? ORDER BY id", (run_id, outcome)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM test_results WHERE run_id = ? ORDER BY id", (run_id,)).fetchall()
        return [dict(r) for r in rows]


def get_result(result_id: int, db_path: Path | str | None = None) -> dict[str, Any] | None:
    with session(db_path) as conn:
        row = conn.execute("SELECT * FROM test_results WHERE id = ?", (result_id,)).fetchone()
        return dict(row) if row else None
