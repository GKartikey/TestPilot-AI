"""Summarise and classify failures.

Both features take an `Evidence` bundle, never a free-form description.
If the bundle is not admissible the functions return an explicit
"insufficient evidence" result rather than speculating: a summary of a
failure that did not happen is worse than no summary.

Classification answers the triage question a lead asks first -- "is this
the product, the test, the environment or the data?" -- because that
determines who picks the failure up, and because only `product_defect`
may ever become a filed defect.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from .evidence import Evidence
from .provider import GUARDRAIL, Provider, get_provider, is_heuristic

SUMMARY_SYSTEM = GUARDRAIL + """

Your present task is FAILURE SUMMARISATION. Summarise only what the
supplied evidence shows. Quote the actual assertion and the actual
values. If the evidence does not reveal a root cause, say that the root
cause is not determinable from this evidence."""

CLASSIFY_SYSTEM = GUARDRAIL + """

Your present task is FAILURE TRIAGE. Assign one category and give the
signals that justify it. Choosing 'product_defect' is a statement about
where to look, not a confirmation that a defect is real; a human still
verifies it."""

CATEGORIES = {
    "product_defect": "The system under test behaved differently from its documented contract.",
    "test_defect": "The test itself is wrong: bad selector, stale expectation, faulty assertion.",
    "environment": "Infrastructure: the service, browser or database was unavailable or misconfigured.",
    "test_data": "The fixture or seed data was missing, stale or conflicting.",
    "flaky_timing": "A race or timeout; the same test has passed on the same build.",
    "undetermined": "The evidence does not distinguish between the categories above.",
}

_SUMMARY_SCHEMA = """Return JSON: {"headline": str, "what_the_evidence_shows": str,
"expected": str, "actual": str, "probable_area": str, "next_step_for_a_human": str,
"root_cause_determinable": bool}"""

_CLASSIFY_SCHEMA = """Return JSON: {"category": one of ["product_defect","test_defect",
"environment","test_data","flaky_timing","undetermined"], "confidence": one of
["high","medium","low"], "signals": [str], "recommended_owner": str}"""


# Ordered most-specific first: the first pattern that matches wins.
_SIGNATURES: list[tuple[str, str, str, str]] = [
    (r"connection refused|max retries|connectionerror|failed to establish", "environment",
     "high", "The client could not reach the service at all."),
    (r"address already in use|port .* in use", "environment", "high", "A port conflict prevented startup."),
    (r"executable doesn'?t exist|browsertype\.launch|playwright install", "environment", "high",
     "The browser binary is missing from this machine."),
    (r"modulenotfounderror|importerror|no module named", "environment", "high",
     "A dependency is not installed in this interpreter."),
    (r"fixture '.*' not found|error in .* setup", "test_defect", "high",
     "A pytest fixture could not be resolved, which is a harness problem."),
    (r"no such table|no such column|operationalerror", "environment", "medium",
     "The database schema is missing or out of date."),
    (r"integrityerror|unique constraint|foreign key constraint", "test_data", "medium",
     "Seed data collided with existing rows."),
    (r"timeouterror|timeout .*exceeded|waiting for (locator|selector)", "flaky_timing", "medium",
     "The wait expired before the expected state appeared."),
    (r"strict mode violation|resolved to \d+ elements", "test_defect", "medium",
     "The locator matched the wrong number of elements."),
    (r"keyerror|attributeerror|typeerror: .*nonetype", "test_defect", "medium",
     "The test code touched a field that was not present."),
    (r"assert .*==|assertionerror", "product_defect", "medium",
     "An explicit assertion on the system's response did not hold."),
]

# pytest renders a failed equality as "assert <actual> == <expected>",
# evaluated left-hand side first. That ordering is a reliable contract.
_ASSERT_RE = re.compile(r"^assert\s+(.+?)\s*==\s*(.+)$", re.IGNORECASE)
# The suite's own assert_status helper emits exactly this phrasing.
_EXPECTED_GOT_RE = re.compile(
    r"expected\s+(?:HTTP\s+)?(\S+?)\s+but\s+(?:got|was|returned)\s+(\S+?)\b", re.IGNORECASE
)


def _insufficient(evidence: Evidence, kind: str) -> dict[str, Any]:
    return {
        "evidence_admissible": False,
        "reasons": evidence.reasons,
        "kind": kind,
        "statement": (
            "TestPilot will not characterise this as a failure. "
            + " ".join(evidence.reasons)
        ),
    }


# ------------------------------------------------------------ summary ---

def _extract_expected_actual(evidence: Evidence) -> tuple[str | None, str | None]:
    """Recover the expected and actual values from a captured failure.

    Only two sources are trusted, because both carry their own ordering:

      1. pytest's comparison line, "assert <actual> == <expected>".
      2. The suite's assert_status helper, "Expected HTTP 401 but got 200".

    Nothing else is inferred. An earlier version scanned the traceback for
    any three-digit status code and assumed the first one found was the
    actual value; because a traceback quotes the assertion source *above*
    the rendered message, that silently inverted expected and actual.
    Reporting them backwards is worse than reporting neither, so when
    neither pattern matches this returns nothing and the summary says the
    root cause is not determinable from this evidence.
    """
    haystack = f"{evidence.failure_message or ''}\n{evidence.traceback or ''}"

    for line in haystack.splitlines():
        stripped = line.strip()
        # Only pytest's own rendered lines, which it prefixes with "E ".
        # The source listing above them quotes the *expression* the test
        # wrote ("assert response.status == 401, ("), not the values it
        # evaluated to, and reading that back is how this went wrong.
        if not stripped.startswith("E "):
            continue
        match = _ASSERT_RE.match(stripped[2:].strip())
        if match:
            actual, expected = match.group(1).strip(), match.group(2).strip()
            if _looks_like_a_value(actual) and _looks_like_a_value(expected):
                return expected, actual

    match = _EXPECTED_GOT_RE.search(haystack)
    if match:
        return match.group(1).strip(), match.group(2).strip()

    return None, None


def _looks_like_a_value(text: str) -> bool:
    """Is this an evaluated value rather than the expression that produced it?

    Values start with a digit, a quote or a bracket; expressions start
    with an identifier. A trailing comma means the regex ran past the end
    of the comparison into the assertion's custom message.
    """
    if not text or "," in text or "(" in text:
        return False
    return text[0].isdigit() or text[0] in "-'\"[{" or text in {"True", "False", "None"}


def _heuristic_summary(evidence: Evidence) -> dict[str, Any]:
    message = evidence.failure_message or ""
    expected, actual = _extract_expected_actual(evidence)

    # The nodeid is part of the signal: a failure in test_cart.py is about
    # the cart even when the assertion text is only bare numbers.
    lowered = f"{message} {evidence.traceback or ''} {evidence.nodeid or ''} {evidence.module or ''}".lower()
    area = next(
        (name for keyword, name in (
            ("cart", "cart and pricing"),
            ("coupon", "cart and pricing"),
            ("discount", "cart and pricing"),
            ("total", "cart and pricing"),
            ("stock", "inventory"),
            ("order", "checkout and orders"),
            ("checkout", "checkout and orders"),
            ("token", "authentication"),
            ("auth", "authentication"),
            ("login", "authentication"),
            ("product", "catalogue"),
        ) if keyword in lowered),
        evidence.module or "unknown",
    )

    determinable = bool(expected and actual)
    return {
        "evidence_admissible": True,
        "kind": "summary",
        "headline": f"{evidence.test_name} failed with {evidence.failure_type or 'an error'} in {area}",
        "what_the_evidence_shows": (
            f"The recorded execution of {evidence.nodeid} on environment "
            f"{evidence.environment!r} ended as {evidence.outcome!r}. "
            f"The captured message was: {message[:400] or '(none captured)'}"
        ),
        "expected": expected or "not stated explicitly in the captured assertion",
        "actual": actual or "not stated explicitly in the captured assertion",
        "probable_area": area,
        "next_step_for_a_human": (
            "Re-run this single test against the same build and confirm the same message, then compare "
            "the observed behaviour with the documented requirement before treating it as a product defect."
        ),
        "root_cause_determinable": determinable,
        "artefacts": evidence.artefacts(),
        "evidence_strength": evidence.strength,
        "provider": "heuristic",
    }


def summarize_failure(evidence: Evidence, provider: Provider | None = None) -> dict[str, Any]:
    if not evidence.admissible:
        return _insufficient(evidence, "summary")

    provider = provider or get_provider()
    if is_heuristic(provider):
        return _heuristic_summary(evidence)

    payload = {
        "nodeid": evidence.nodeid,
        "outcome": evidence.outcome,
        "failure_type": evidence.failure_type,
        "failure_message": evidence.failure_message,
        "traceback": (evidence.traceback or "")[:6000],
        "request_log": (evidence.request_log or "")[:2000],
        "environment": evidence.environment,
        "suite": evidence.suite,
        "artefacts": evidence.artefacts(),
    }
    prompt = f"Execution evidence:\n{json.dumps(payload, indent=2)}\n\n{_SUMMARY_SCHEMA}"
    try:
        parsed = provider.complete(SUMMARY_SYSTEM, prompt).json()
        if not isinstance(parsed, dict) or "headline" not in parsed:
            raise ValueError("model response did not match the schema")
        return {
            "evidence_admissible": True,
            "kind": "summary",
            **parsed,
            "artefacts": evidence.artefacts(),
            "evidence_strength": evidence.strength,
            "provider": getattr(provider, "name", "unknown"),
        }
    except Exception:
        return _heuristic_summary(evidence)


# ----------------------------------------------------- classification ---

def _heuristic_classify(evidence: Evidence) -> dict[str, Any]:
    haystack = f"{evidence.failure_type or ''} {evidence.failure_message or ''} {evidence.traceback or ''}".lower()

    category, confidence, signals = "undetermined", "low", []
    for pattern, cat, conf, explanation in _SIGNATURES:
        if re.search(pattern, haystack):
            category, confidence, signals = cat, conf, [explanation]
            break

    if evidence.likely_non_product and category == "product_defect":
        category, confidence = "environment", "medium"
        signals.append("Infrastructure wording in the traceback outweighs the assertion signal.")

    # A test that has passed on other executions of the same nodeid is a
    # flake candidate rather than a hard product defect.
    if category == "product_defect" and evidence.total_executions >= 3:
        pass_count = evidence.total_executions - evidence.occurrences
        if pass_count > 0 and evidence.occurrences / evidence.total_executions < 0.5:
            category, confidence = "flaky_timing", "low"
            signals.append(
                f"This test has passed {pass_count} of {evidence.total_executions} recorded executions."
            )

    if evidence.reproducible:
        signals.append(f"Reproduced in {evidence.occurrences} of {evidence.total_executions} recorded executions.")
    else:
        signals.append("Observed once so far; reproduction has not been confirmed.")

    owner = {
        "product_defect": "Development team owning " + (evidence.module or "the affected module"),
        "test_defect": "The automation engineer who owns this test",
        "environment": "Build or infrastructure engineer",
        "test_data": "The automation engineer who owns the fixtures",
        "flaky_timing": "The automation engineer who owns this test",
        "undetermined": "QA lead for manual triage",
    }[category]

    return {
        "evidence_admissible": True,
        "kind": "classification",
        "category": category,
        "category_meaning": CATEGORIES[category],
        "confidence": confidence,
        "signals": signals,
        "recommended_owner": owner,
        "may_file_defect": category == "product_defect",
        "evidence_strength": evidence.strength,
        "provider": "heuristic",
    }


def classify_failure(evidence: Evidence, provider: Provider | None = None) -> dict[str, Any]:
    if not evidence.admissible:
        return _insufficient(evidence, "classification")

    provider = provider or get_provider()
    if is_heuristic(provider):
        return _heuristic_classify(evidence)

    payload = {
        "nodeid": evidence.nodeid,
        "layer": evidence.layer,
        "failure_type": evidence.failure_type,
        "failure_message": evidence.failure_message,
        "traceback": (evidence.traceback or "")[:6000],
        "executions_recorded": evidence.total_executions,
        "failures_recorded": evidence.occurrences,
        "artefacts_present": bool(evidence.artefacts()),
    }
    prompt = (
        f"Execution evidence:\n{json.dumps(payload, indent=2)}\n\n"
        f"Categories:\n{json.dumps(CATEGORIES, indent=2)}\n\n{_CLASSIFY_SCHEMA}"
    )
    try:
        parsed = provider.complete(CLASSIFY_SYSTEM, prompt).json()
        category = parsed.get("category")
        if category not in CATEGORIES:
            raise ValueError(f"model returned unknown category {category!r}")
        return {
            "evidence_admissible": True,
            "kind": "classification",
            "category": category,
            "category_meaning": CATEGORIES[category],
            "confidence": parsed.get("confidence", "low"),
            "signals": parsed.get("signals", []),
            "recommended_owner": parsed.get("recommended_owner", "QA lead"),
            "may_file_defect": category == "product_defect",
            "evidence_strength": evidence.strength,
            "provider": getattr(provider, "name", "unknown"),
        }
    except Exception:
        return _heuristic_classify(evidence)


# ------------------------------------------------------- run rollup ----

def summarize_run(bundles: list[Evidence], provider: Provider | None = None) -> dict[str, Any]:
    """A triage-ready rollup of every failure in one run."""
    provider = provider or get_provider()
    analyses = []
    for evidence in bundles:
        analyses.append(
            {
                "result_id": evidence.result_id,
                "nodeid": evidence.nodeid,
                "case_id": evidence.case_id,
                "summary": summarize_failure(evidence, provider),
                "classification": classify_failure(evidence, provider),
            }
        )

    counts = Counter(
        a["classification"].get("category", "undetermined")
        for a in analyses
        if a["classification"].get("evidence_admissible")
    )
    filable = [a for a in analyses if a["classification"].get("may_file_defect")]

    return {
        "failures_analysed": len(analyses),
        "by_category": dict(counts),
        "eligible_for_defect_filing": len(filable),
        "analyses": analyses,
        "provider": getattr(provider, "name", "unknown"),
        "note": (
            "Categories indicate where to look first. Only failures categorised as product_defect "
            "may be filed, and every filed defect still requires human verification."
        ),
    }
