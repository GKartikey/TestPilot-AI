"""The evidence gate.

This module is the reason TestPilot's AI features are safe to put in
front of a release manager. No AI feature in this codebase is allowed to
assert that a defect exists; it may only *describe* evidence that the
execution layer already produced.

A claim is admissible only when all of the following hold:

  1. A stored `test_results` row exists (the claim is anchored to a real,
     recorded execution, not to a model's recollection).
  2. Its outcome is `failed` or `error` -- never `passed`, `skipped`,
     `xfailed` or a test that was never run.
  3. A failure message or traceback was captured, so there is something
     concrete to quote.
  4. The run is attributable: suite, environment and timestamp are known.

Anything short of that produces `admissible = False`, and every consumer
downgrades its language from "defect" to "unverified observation" and
refuses to file a defect record.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import store

FAILING_OUTCOMES = {"failed", "error"}
_NON_PRODUCT_HINTS = (
    "connection refused",
    "connectionerror",
    "max retries exceeded",
    "no such file or directory",
    "executable doesn't exist",
    "browsertype.launch",
    "fixture ",
    "modulenotfounderror",
    "importerror",
    "address already in use",
)


@dataclass
class Evidence:
    """A verifiable record of one failing execution."""

    admissible: bool
    reasons: list[str] = field(default_factory=list)
    result_id: int | None = None
    run_id: str | None = None
    nodeid: str | None = None
    case_id: str | None = None
    test_name: str | None = None
    layer: str | None = None
    module: str | None = None
    outcome: str | None = None
    failure_type: str | None = None
    failure_message: str | None = None
    traceback: str | None = None
    request_log: str | None = None
    screenshot_path: str | None = None
    trace_path: str | None = None
    screenshot_exists: bool = False
    trace_exists: bool = False
    suite: str | None = None
    environment: str | None = None
    git_branch: str | None = None
    git_commit: str | None = None
    started_at: str | None = None
    duration_ms: int | None = None
    occurrences: int = 0
    total_executions: int = 0
    reproducible: bool = False
    likely_non_product: bool = False

    @property
    def strength(self) -> str:
        """How much weight a human should put on this evidence."""
        if not self.admissible:
            return "insufficient"
        score = 1
        if self.traceback:
            score += 1
        if self.screenshot_exists or self.trace_exists:
            score += 1
        if self.reproducible:
            score += 1
        return {1: "weak", 2: "moderate", 3: "strong", 4: "strong"}.get(score, "moderate")

    def artefacts(self) -> list[str]:
        found = []
        if self.screenshot_exists and self.screenshot_path:
            found.append(self.screenshot_path)
        if self.trace_exists and self.trace_path:
            found.append(self.trace_path)
        return found

    def to_dict(self) -> dict[str, Any]:
        payload = dict(self.__dict__)
        payload["strength"] = self.strength
        return payload

    def summary_line(self) -> str:
        if not self.admissible:
            return "No admissible execution evidence: " + "; ".join(self.reasons)
        return (
            f"{self.nodeid} {self.outcome} in run {self.run_id} "
            f"(suite={self.suite}, env={self.environment}) with {self.failure_type or 'an error'}"
        )


def _exists(path: str | None) -> bool:
    if not path:
        return False
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = Path(os.getcwd()) / candidate
    return candidate.exists()


def collect(result_id: int) -> Evidence:
    """Build the evidence bundle for one recorded test result."""
    result = store.get_result(result_id)
    if result is None:
        return Evidence(
            admissible=False,
            reasons=[f"No stored test result with id {result_id}; nothing was executed to support a claim."],
            result_id=result_id,
        )

    run = store.get_run(result["run_id"]) or {}
    reasons: list[str] = []

    outcome = result["outcome"]
    if outcome not in FAILING_OUTCOMES:
        reasons.append(
            f"Test outcome was {outcome!r}, not a failure. A defect cannot be claimed from a non-failing execution."
        )
    if not (result.get("failure_message") or result.get("traceback")):
        reasons.append("No failure message or traceback was captured, so there is nothing concrete to reproduce.")
    if not run:
        reasons.append("The parent run record is missing, so the failure is not attributable to a build or environment.")
    elif not (run.get("environment") and run.get("started_at")):
        reasons.append("The run is missing environment or timestamp attribution.")

    # How often has this exact test failed, and how often has it run?
    with store.session() as conn:
        counts = conn.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN outcome IN ('failed','error') THEN 1 ELSE 0 END) AS failures
            FROM test_results WHERE nodeid = ?
            """,
            (result["nodeid"],),
        ).fetchone()

    haystack = f"{result.get('failure_message') or ''} {result.get('traceback') or ''}".lower()
    likely_non_product = any(hint in haystack for hint in _NON_PRODUCT_HINTS)

    return Evidence(
        admissible=not reasons,
        reasons=reasons,
        result_id=result["id"],
        run_id=result["run_id"],
        nodeid=result["nodeid"],
        case_id=result.get("case_id"),
        test_name=result.get("test_name"),
        layer=result.get("layer"),
        module=result.get("module"),
        outcome=outcome,
        failure_type=result.get("failure_type"),
        failure_message=result.get("failure_message"),
        traceback=result.get("traceback"),
        request_log=result.get("request_log"),
        screenshot_path=result.get("screenshot_path"),
        trace_path=result.get("trace_path"),
        screenshot_exists=_exists(result.get("screenshot_path")),
        trace_exists=_exists(result.get("trace_path")),
        suite=run.get("suite"),
        environment=run.get("environment"),
        git_branch=run.get("git_branch"),
        git_commit=run.get("git_commit"),
        started_at=run.get("started_at"),
        duration_ms=result.get("duration_ms"),
        occurrences=int(counts["failures"] or 0),
        total_executions=int(counts["total"] or 0),
        reproducible=int(counts["failures"] or 0) >= 2,
        likely_non_product=likely_non_product,
    )


def collect_for_run(run_id: str) -> list[Evidence]:
    """Evidence bundles for every failing result in a run."""
    bundles = []
    for result in store.results_for_run(run_id):
        if result["outcome"] in FAILING_OUTCOMES:
            bundles.append(collect(result["id"]))
    return bundles


class EvidenceError(RuntimeError):
    """Raised when a caller tries to file a defect without admissible evidence."""


def require_admissible(evidence: Evidence) -> Evidence:
    if not evidence.admissible:
        raise EvidenceError(
            "Refusing to assert a defect. " + " ".join(evidence.reasons)
        )
    return evidence
