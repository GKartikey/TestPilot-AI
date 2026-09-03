"""Pass/fail analytics over the execution history.

Everything here is a SQL query against the results store. That is the
point: once results are in a relational table, "which test is flakiest",
"is the pass rate trending down" and "what is our slowest suite" stop
being guesses.
"""
from __future__ import annotations

from typing import Any

from . import store


def run_summary(run_id: str) -> dict[str, Any]:
    with store.session() as conn:
        run = conn.execute("SELECT * FROM test_runs WHERE id = ?", (run_id,)).fetchone()
        if run is None:
            raise KeyError(f"Unknown run {run_id!r}")
        by_layer = conn.execute(
            """
            SELECT layer,
                   COUNT(*) AS total,
                   SUM(CASE WHEN outcome IN ('passed','xfailed') THEN 1 ELSE 0 END) AS passed,
                   SUM(CASE WHEN outcome IN ('failed','error')   THEN 1 ELSE 0 END) AS failed
            FROM test_results WHERE run_id = ?
            GROUP BY layer ORDER BY layer
            """,
            (run_id,),
        ).fetchall()
        slowest = conn.execute(
            """
            SELECT test_name, nodeid, duration_ms FROM test_results
            WHERE run_id = ? ORDER BY duration_ms DESC LIMIT 5
            """,
            (run_id,),
        ).fetchall()
        failures = conn.execute(
            """
            SELECT id, case_id, nodeid, test_name, layer, failure_type, failure_message,
                   screenshot_path, trace_path
            FROM test_results WHERE run_id = ? AND outcome IN ('failed','error') ORDER BY id
            """,
            (run_id,),
        ).fetchall()

    run_dict = dict(run)
    total = run_dict["total"] or 0
    executed = total - (run_dict["skipped"] or 0)
    run_dict["pass_rate"] = round((run_dict["passed"] or 0) / executed * 100, 1) if executed else 0.0
    return {
        "run": run_dict,
        "by_layer": [dict(r) for r in by_layer],
        "slowest": [dict(r) for r in slowest],
        "failures": [dict(r) for r in failures],
    }


def history(suite: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """Most recent runs, oldest first, with a pass rate per run."""
    runs = store.list_runs(limit=limit, suite=suite)
    out = []
    for run in reversed(runs):
        executed = (run["total"] or 0) - (run["skipped"] or 0)
        out.append(
            {
                **run,
                "pass_rate": round((run["passed"] or 0) / executed * 100, 1) if executed else 0.0,
            }
        )
    return out


def flaky_tests(min_runs: int = 3, limit: int = 15) -> list[dict[str, Any]]:
    """Tests that have both passed and failed across recorded history.

    A test that is always red is broken, not flaky, so anything with a
    100% failure rate is excluded.
    """
    with store.session() as conn:
        rows = conn.execute(
            """
            SELECT nodeid,
                   test_name,
                   layer,
                   COUNT(*) AS runs,
                   SUM(CASE WHEN outcome IN ('passed','xfailed') THEN 1 ELSE 0 END) AS passes,
                   SUM(CASE WHEN outcome IN ('failed','error')   THEN 1 ELSE 0 END) AS failures
            FROM test_results
            WHERE outcome IN ('passed','failed','error','xfailed')
            GROUP BY nodeid
            HAVING runs >= ? AND passes > 0 AND failures > 0
            ORDER BY (CAST(failures AS REAL) / runs) DESC, runs DESC
            LIMIT ?
            """,
            (min_runs, limit),
        ).fetchall()
    return [
        {**dict(r), "flake_rate": round(r["failures"] / r["runs"] * 100, 1)}
        for r in rows
    ]


def failure_hotspots(limit: int = 10) -> list[dict[str, Any]]:
    """Which modules and failure types dominate. Drives where to invest."""
    with store.session() as conn:
        rows = conn.execute(
            """
            SELECT module, layer, failure_type, COUNT(*) AS occurrences
            FROM test_results
            WHERE outcome IN ('failed','error')
            GROUP BY module, layer, failure_type
            ORDER BY occurrences DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def case_execution_status() -> list[dict[str, Any]]:
    """Latest known outcome per manual test case id."""
    with store.session() as conn:
        rows = conn.execute(
            """
            SELECT r.case_id,
                   r.nodeid,
                   r.outcome,
                   r.recorded_at,
                   r.run_id
            FROM test_results r
            JOIN (
                SELECT case_id, MAX(id) AS latest
                FROM test_results
                WHERE case_id IS NOT NULL
                GROUP BY case_id
            ) newest ON newest.latest = r.id
            ORDER BY r.case_id
            """
        ).fetchall()
    return [dict(r) for r in rows]


def overall_stats() -> dict[str, Any]:
    with store.session() as conn:
        runs = conn.execute("SELECT COUNT(*) AS n FROM test_runs").fetchone()["n"]
        results = conn.execute("SELECT COUNT(*) AS n FROM test_results").fetchone()["n"]
        tally = conn.execute(
            """
            SELECT
                SUM(CASE WHEN outcome IN ('passed','xfailed') THEN 1 ELSE 0 END) AS passed,
                SUM(CASE WHEN outcome IN ('failed','error')   THEN 1 ELSE 0 END) AS failed,
                SUM(CASE WHEN outcome = 'skipped' THEN 1 ELSE 0 END)             AS skipped,
                COALESCE(AVG(duration_ms), 0)                                    AS avg_duration_ms
            FROM test_results
            """
        ).fetchone()
        defects = conn.execute(
            "SELECT status, COUNT(*) AS n FROM defects GROUP BY status ORDER BY status"
        ).fetchall()

    executed = (tally["passed"] or 0) + (tally["failed"] or 0)
    return {
        "total_runs": runs,
        "total_results": results,
        "passed": tally["passed"] or 0,
        "failed": tally["failed"] or 0,
        "skipped": tally["skipped"] or 0,
        "pass_rate": round((tally["passed"] or 0) / executed * 100, 1) if executed else 0.0,
        "avg_duration_ms": int(tally["avg_duration_ms"] or 0),
        "defects_by_status": {r["status"]: r["n"] for r in defects},
    }


def compare_runs(baseline_id: str, candidate_id: str) -> dict[str, Any]:
    """New failures, fixed tests and still-failing tests between two runs.

    This is the query a reviewer actually wants on a pull request: not
    "42 failed" but "these 2 are new since main".
    """
    def outcomes(run_id: str) -> dict[str, str]:
        return {r["nodeid"]: r["outcome"] for r in store.results_for_run(run_id)}

    base = outcomes(baseline_id)
    cand = outcomes(candidate_id)
    bad = {"failed", "error"}

    return {
        "baseline": baseline_id,
        "candidate": candidate_id,
        "new_failures": sorted(n for n, o in cand.items() if o in bad and base.get(n) not in bad and n in base),
        "newly_added_failing": sorted(n for n, o in cand.items() if o in bad and n not in base),
        "fixed": sorted(n for n, o in cand.items() if o not in bad and base.get(n) in bad),
        "still_failing": sorted(n for n, o in cand.items() if o in bad and base.get(n) in bad),
        "removed": sorted(n for n in base if n not in cand),
    }
