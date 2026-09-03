"""Defect records and their lifecycle.

The lifecycle is enforced as a state machine rather than a free-text
status field, so a defect cannot jump from NEW to CLOSED without somebody
verifying the fix. Every transition is appended to `defect_events`, which
gives an audit trail of who moved what and why.

    NEW -> TRIAGED -> IN_PROGRESS -> FIXED -> VERIFIED -> CLOSED
                 \\-> REJECTED / DEFERRED
    VERIFIED/CLOSED -> REOPENED -> IN_PROGRESS
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from . import store
from .ai import bug_report as bug_report_module
from .ai.evidence import Evidence, EvidenceError, collect, require_admissible

TRANSITIONS: dict[str, set[str]] = {
    "NEW": {"TRIAGED", "REJECTED", "DEFERRED"},
    "TRIAGED": {"IN_PROGRESS", "REJECTED", "DEFERRED"},
    "IN_PROGRESS": {"FIXED", "DEFERRED"},
    "FIXED": {"VERIFIED", "REOPENED"},
    "VERIFIED": {"CLOSED", "REOPENED"},
    "CLOSED": {"REOPENED"},
    "REJECTED": {"REOPENED"},
    "DEFERRED": {"TRIAGED", "REJECTED"},
    "REOPENED": {"IN_PROGRESS", "REJECTED"},
}

TERMINAL = {"CLOSED", "REJECTED"}


class LifecycleError(ValueError):
    """Raised on an illegal defect status transition."""


def _new_id() -> str:
    return f"DEF-{uuid.uuid4().hex[:8].upper()}"


def file_defect(
    result_id: int,
    provider: Any = None,
    allow_non_product: bool = False,
    reporter: str = "testpilot",
) -> dict[str, Any]:
    """File a defect for a failing result, or refuse.

    This is the only path that writes a `defects` row, and it goes
    through the evidence gate first. A caller cannot bypass it by
    supplying their own text.
    """
    evidence = collect(result_id)
    try:
        require_admissible(evidence)
    except EvidenceError as exc:
        return {"filed": False, "reason": str(exc), "reasons": evidence.reasons}

    draft = bug_report_module.draft(evidence, provider=provider, allow_non_product=allow_non_product)
    if not draft.get("drafted"):
        return {"filed": False, "reason": draft.get("refusal"), "reasons": draft.get("reasons", []), "draft": draft}

    report = draft["report"]
    defect_id = _new_id()
    now = store.utcnow()

    with store.session() as conn:
        conn.execute(
            """
            INSERT INTO defects (id, result_id, run_id, title, severity, priority, status,
                                 component, classification, body_markdown, evidence, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'NEW', ?, ?, ?, ?, ?, ?)
            """,
            (
                defect_id,
                evidence.result_id,
                evidence.run_id,
                report["title"],
                report.get("severity", "S3"),
                report.get("priority", "P2"),
                report.get("component", "unknown"),
                draft["classification"].get("category", "undetermined"),
                draft["markdown"],
                json.dumps(evidence.to_dict(), default=str),
                now,
                now,
            ),
        )
        conn.execute(
            "INSERT INTO defect_events (defect_id, from_status, to_status, actor, note, created_at) "
            "VALUES (?, NULL, 'NEW', ?, ?, ?)",
            (defect_id, reporter, f"Filed from run {evidence.run_id}, result {evidence.result_id}", now),
        )

    return {
        "filed": True,
        "defect_id": defect_id,
        "title": report["title"],
        "severity": report.get("severity"),
        "priority": report.get("priority"),
        "classification": draft["classification"].get("category"),
        "verification_required": True,
        "markdown": draft["markdown"],
    }


def transition(defect_id: str, to_status: str, actor: str = "qa", note: str | None = None) -> dict[str, Any]:
    to_status = to_status.upper()
    with store.session() as conn:
        row = conn.execute("SELECT * FROM defects WHERE id = ?", (defect_id,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown defect {defect_id!r}")
        current = row["status"]
        allowed = TRANSITIONS.get(current, set())
        if to_status not in allowed:
            raise LifecycleError(
                f"{defect_id} cannot move from {current} to {to_status}. "
                f"Allowed from {current}: {', '.join(sorted(allowed)) or 'nothing'}."
            )
        if to_status == "VERIFIED" and not note:
            raise LifecycleError("Verifying a fix requires a note recording how it was verified.")

        now = store.utcnow()
        conn.execute("UPDATE defects SET status = ?, updated_at = ? WHERE id = ?", (to_status, now, defect_id))
        conn.execute(
            "INSERT INTO defect_events (defect_id, from_status, to_status, actor, note, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (defect_id, current, to_status, actor, note, now),
        )
        return {"defect_id": defect_id, "from": current, "to": to_status, "at": now}


def get(defect_id: str) -> dict[str, Any] | None:
    with store.session() as conn:
        row = conn.execute("SELECT * FROM defects WHERE id = ?", (defect_id,)).fetchone()
        if row is None:
            return None
        events = conn.execute(
            "SELECT * FROM defect_events WHERE defect_id = ? ORDER BY id", (defect_id,)
        ).fetchall()
    defect = dict(row)
    defect["evidence"] = json.loads(defect.get("evidence") or "{}")
    defect["history"] = [dict(e) for e in events]
    defect["allowed_transitions"] = sorted(TRANSITIONS.get(defect["status"], set()))
    return defect


def list_defects(status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    with store.session() as conn:
        if status:
            rows = conn.execute(
                "SELECT id, title, severity, priority, status, component, classification, created_at "
                "FROM defects WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status.upper(), limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, title, severity, priority, status, component, classification, created_at "
                "FROM defects ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [dict(r) for r in rows]


def metrics() -> dict[str, Any]:
    """Defect metrics a test lead reports at the end of a cycle."""
    with store.session() as conn:
        by_status = conn.execute("SELECT status, COUNT(*) AS n FROM defects GROUP BY status").fetchall()
        by_severity = conn.execute("SELECT severity, COUNT(*) AS n FROM defects GROUP BY severity").fetchall()
        by_component = conn.execute(
            "SELECT component, COUNT(*) AS n FROM defects GROUP BY component ORDER BY n DESC LIMIT 10"
        ).fetchall()
        rejected = conn.execute("SELECT COUNT(*) AS n FROM defects WHERE status = 'REJECTED'").fetchone()["n"]
        total = conn.execute("SELECT COUNT(*) AS n FROM defects").fetchone()["n"]
        open_count = conn.execute(
            "SELECT COUNT(*) AS n FROM defects WHERE status NOT IN ('CLOSED','REJECTED')"
        ).fetchone()["n"]

    return {
        "total": total,
        "open": open_count,
        "by_status": {r["status"]: r["n"] for r in by_status},
        "by_severity": {r["severity"]: r["n"] for r in by_severity},
        "top_components": [dict(r) for r in by_component],
        # Rejected/total is the classic "how much noise does QA file" metric.
        "rejection_rate": round(rejected / total * 100, 1) if total else 0.0,
    }


def evidence_for(defect_id: str) -> Evidence | None:
    defect = get(defect_id)
    if not defect or not defect.get("result_id"):
        return None
    return collect(int(defect["result_id"]))
