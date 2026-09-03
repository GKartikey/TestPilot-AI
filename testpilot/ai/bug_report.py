"""Draft a bug report from execution evidence.

The single most important rule in this codebase lives here: a draft bug
report is produced **only** when an admissible `Evidence` bundle exists
and the failure was triaged as a product defect. In every other case the
function returns a refusal that names what is missing.

Even when a report is produced it is a *draft*: it is titled as such, it
carries the evidence that justifies it, and it states what a human must
still confirm. TestPilot never says "this is a bug"; it says "this
execution failed, here is the proof, here is a report you can review."
"""
from __future__ import annotations

import json
from typing import Any

from .evidence import Evidence
from .failure_analysis import classify_failure, summarize_failure
from .provider import GUARDRAIL, Provider, get_provider, is_heuristic

SYSTEM = GUARDRAIL + """

Your present task is DRAFTING A BUG REPORT from evidence that has already
been verified to come from a real failing execution. Write it for a
developer: precise, reproducible, no adjectives. State the expected and
actual behaviour using only values present in the evidence. Add an
'Open questions' section for anything the evidence does not settle."""

_SCHEMA = """Return JSON: {"title": str, "severity": one of ["S1","S2","S3","S4"],
"priority": one of ["P1","P2","P3","P4"], "component": str, "summary": str,
"steps_to_reproduce": [str], "expected_result": str, "actual_result": str,
"open_questions": [str]}"""

SEVERITY_GUIDE = {
    "S1": "Critical - data loss, money incorrect, or a core journey is completely blocked.",
    "S2": "Major - a core journey is broken but has a workaround, or a security control fails.",
    "S3": "Minor - a non-core function misbehaves.",
    "S4": "Trivial - cosmetic or wording.",
}

# Modules whose failures move money or gate access get escalated.
_HIGH_IMPACT = {"orders", "cart", "pricing", "checkout", "auth", "payments"}


def _refuse(reasons: list[str], detail: str) -> dict[str, Any]:
    return {
        "drafted": False,
        "refusal": detail,
        "reasons": reasons,
        "guidance": (
            "TestPilot only drafts a bug report from a recorded failing execution that has been "
            "triaged as a product defect. Run the test, capture the failure, then retry."
        ),
    }


def _severity_for(evidence: Evidence, summary: dict[str, Any]) -> tuple[str, str]:
    module = (evidence.module or "").lower()
    area = str(summary.get("probable_area", "")).lower()
    high_impact = any(token in f"{module} {area} {evidence.nodeid or ''}".lower() for token in _HIGH_IMPACT)

    if high_impact and evidence.reproducible:
        return "S1", "P1"
    if high_impact:
        return "S2", "P1"
    if evidence.layer == "ui":
        return "S3", "P3"
    return "S3", "P2"


def _heuristic_report(evidence: Evidence, summary: dict[str, Any], classification: dict[str, Any]) -> dict[str, Any]:
    severity, priority = _severity_for(evidence, summary)
    steps = [
        f"Deploy the system under test to the `{evidence.environment}` environment"
        + (f" at commit {evidence.git_commit}" if evidence.git_commit else ""),
        f"Execute the automated test `{evidence.nodeid}`",
        "Observe the assertion result recorded below",
    ]
    if evidence.case_id:
        steps.insert(0, f"Follow manual test case {evidence.case_id}, which this test automates")

    return {
        "title": f"[DRAFT] {summary.get('headline', evidence.test_name or 'Recorded failure')}",
        "severity": severity,
        "priority": priority,
        "component": summary.get("probable_area", evidence.module or "unknown"),
        "summary": summary.get("what_the_evidence_shows", ""),
        "steps_to_reproduce": steps,
        "expected_result": summary.get("expected", "See the assertion in the captured traceback."),
        "actual_result": summary.get("actual", evidence.failure_message or "See the captured traceback."),
        "open_questions": [
            "Has this been reproduced manually, outside the automated suite?",
            "Is the expected behaviour in the test the same as the documented requirement?",
            "Which change introduced this? Compare against the last known-green run.",
        ],
        "provider": "heuristic",
    }


def draft(
    evidence: Evidence,
    provider: Provider | None = None,
    allow_non_product: bool = False,
) -> dict[str, Any]:
    """Draft a bug report, or refuse and explain why.

    `allow_non_product` lets a human override the triage gate when they
    have decided a non-product-defect classification is wrong. The
    override is recorded in the output so the report is never silently
    escalated.
    """
    # Gate 1: there must be admissible execution evidence.
    if not evidence.admissible:
        return _refuse(
            evidence.reasons,
            "Refusing to draft a bug report: there is no admissible execution evidence that a failure occurred.",
        )

    provider = provider or get_provider()
    summary = summarize_failure(evidence, provider)
    classification = classify_failure(evidence, provider)

    # Gate 2: triage must point at the product, unless a human overrides.
    if not classification.get("may_file_defect") and not allow_non_product:
        category = classification.get("category", "undetermined")
        return {
            **_refuse(
                [
                    f"The failure was triaged as {category!r}: {classification.get('category_meaning', '')}",
                    *classification.get("signals", []),
                ],
                f"Refusing to draft a product bug report: this failure looks like {category!r}, not a product defect.",
            ),
            "classification": classification,
            "summary": summary,
            "override_hint": "If you have confirmed this is a product defect, re-run with allow_non_product=True.",
        }

    if is_heuristic(provider):
        report = _heuristic_report(evidence, summary, classification)
    else:
        payload = {
            "nodeid": evidence.nodeid,
            "manual_case_id": evidence.case_id,
            "environment": evidence.environment,
            "suite": evidence.suite,
            "git_branch": evidence.git_branch,
            "git_commit": evidence.git_commit,
            "observed_at": evidence.started_at,
            "failure_type": evidence.failure_type,
            "failure_message": evidence.failure_message,
            "traceback": (evidence.traceback or "")[:6000],
            "http_log": (evidence.request_log or "")[:2500],
            "artefacts": evidence.artefacts(),
            "times_failed": evidence.occurrences,
            "times_executed": evidence.total_executions,
            "severity_guide": SEVERITY_GUIDE,
        }
        prompt = f"Verified execution evidence:\n{json.dumps(payload, indent=2)}\n\n{_SCHEMA}"
        try:
            parsed = provider.complete(SYSTEM, prompt).json()
            if not isinstance(parsed, dict) or not parsed.get("title"):
                raise ValueError("model response did not match the schema")
            parsed.setdefault("severity", "S3")
            parsed.setdefault("priority", "P2")
            if parsed["severity"] not in SEVERITY_GUIDE:
                parsed["severity"] = "S3"
            title = str(parsed["title"])
            parsed["title"] = title if title.startswith("[DRAFT]") else f"[DRAFT] {title}"
            report = {**parsed, "provider": getattr(provider, "name", "unknown")}
        except Exception:
            report = _heuristic_report(evidence, summary, classification)

    return {
        "drafted": True,
        "report": report,
        "summary": summary,
        "classification": classification,
        "evidence": evidence.to_dict(),
        "override_used": bool(not classification.get("may_file_defect") and allow_non_product),
        "verification_required": True,
        "markdown": to_markdown(report, evidence, classification),
    }


def to_markdown(report: dict[str, Any], evidence: Evidence, classification: dict[str, Any]) -> str:
    """Render the draft as the markdown body that goes into the tracker."""
    steps = "\n".join(f"{i}. {step}" for i, step in enumerate(report.get("steps_to_reproduce", []), start=1))
    questions = "\n".join(f"- {q}" for q in report.get("open_questions", [])) or "- None recorded."
    artefacts = "\n".join(f"- `{path}`" for path in evidence.artefacts()) or "- No screenshot or trace was captured."
    signals = "\n".join(f"- {s}" for s in classification.get("signals", [])) or "- None recorded."

    traceback_block = (evidence.traceback or evidence.failure_message or "(none captured)")[:2500]

    return f"""# {report.get('title', 'Draft defect')}

> **This is a machine-drafted report awaiting human verification.**
> It was generated only because a recorded execution failed. It asserts
> what the evidence shows, not that a defect has been confirmed.

| Field | Value |
| --- | --- |
| Severity | {report.get('severity', 'S3')} - {SEVERITY_GUIDE.get(report.get('severity', 'S3'), '')} |
| Priority | {report.get('priority', 'P2')} |
| Component | {report.get('component', 'unknown')} |
| Triage category | {classification.get('category', 'undetermined')} ({classification.get('confidence', 'low')} confidence) |
| Evidence strength | {evidence.strength} |
| Environment | {evidence.environment} |
| Build | {evidence.git_branch or 'n/a'} @ {evidence.git_commit or 'n/a'} |
| Suite / Run | {evidence.suite} / `{evidence.run_id}` |
| Manual case | {evidence.case_id or 'not linked'} |
| Reproduced | {evidence.occurrences} of {evidence.total_executions} recorded executions |

## Summary

{report.get('summary', '')}

## Steps to reproduce

{steps}

## Expected result

{report.get('expected_result', '')}

## Actual result

{report.get('actual_result', '')}

## Execution evidence

Automated test: `{evidence.nodeid}`
Outcome recorded: **{evidence.outcome}** ({evidence.failure_type or 'error'})

```
{traceback_block}
```

### Attached artefacts

{artefacts}

### Triage signals

{signals}

## Open questions for the reviewer

{questions}

---
*Drafted by TestPilot from run `{evidence.run_id}`, result `{evidence.result_id}`.
No claim in this report may be treated as confirmed until a human reproduces it.*
"""
