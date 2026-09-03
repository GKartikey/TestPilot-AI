"""Tests for the evidence gate and the AI features it protects.

These are the tests that keep the platform's central promise honest: no
AI feature may assert a defect without a recorded failing execution. If
any test in this file goes red, the AI layer must be treated as unsafe
to use until it is fixed.

They run against a throwaway results database, so they need neither the
application nor a network.
"""
from __future__ import annotations

import pytest

from testpilot import defects, store
from testpilot.ai import bug_report, edge_cases, evidence, failure_analysis
from testpilot.ai.provider import HeuristicProvider

pytestmark = [pytest.mark.unit]


@pytest.fixture
def results_db(tmp_path, monkeypatch):
    """Point the whole store at a temporary database for this test."""
    db_path = tmp_path / "results.db"
    monkeypatch.setattr(store, "RESULTS_DB", db_path)
    monkeypatch.setattr(evidence.store, "RESULTS_DB", db_path)
    monkeypatch.setattr(defects.store, "RESULTS_DB", db_path)
    return db_path


def _record(outcome: str = "failed", **overrides):
    """Create a run with a single result and return its id."""
    run_id = store.start_run(suite="unit", environment="test", trigger="manual")
    payload = {
        "nodeid": "tests/api/test_cart.py::test_totals",
        "test_name": "test_totals",
        "module": "test_cart",
        "layer": "api",
        "markers": ["api", "regression"],
        "outcome": outcome,
        "duration_ms": 42,
        "case_id": "TC-CART-030",
        "failure_type": "AssertionError" if outcome in {"failed", "error"} else None,
        "failure_message": "assert 1799 == 1800" if outcome in {"failed", "error"} else None,
        "traceback": "E  assert 1799 == 1800" if outcome in {"failed", "error"} else None,
    }
    payload.update(overrides)
    result_id = store.record_result(run_id, payload)
    store.finish_run(run_id)
    return result_id


provider = HeuristicProvider()


# ------------------------------------------------- the gate itself ----

def test_a_recorded_failure_produces_admissible_evidence(results_db):
    """The positive control: a real failure is usable."""
    bundle = evidence.collect(_record("failed"))

    assert bundle.admissible is True
    assert bundle.reasons == []
    assert bundle.outcome == "failed"
    assert bundle.case_id == "TC-CART-030"


def test_evidence_is_refused_when_the_result_does_not_exist(results_db):
    """A claim about a result id that was never recorded is inadmissible."""
    bundle = evidence.collect(999_999)

    assert bundle.admissible is False
    assert any("no stored test result" in reason.lower() for reason in bundle.reasons)


@pytest.mark.parametrize("outcome", ["passed", "skipped", "xfailed"])
def test_evidence_is_refused_for_a_test_that_did_not_fail(results_db, outcome):
    """The core guarantee: a passing test can never support a defect claim."""
    bundle = evidence.collect(_record(outcome))

    assert bundle.admissible is False
    assert any("not a failure" in reason.lower() for reason in bundle.reasons)


def test_evidence_is_refused_when_no_failure_detail_was_captured(results_db):
    """A failure with no message gives nothing concrete to reproduce."""
    bundle = evidence.collect(_record("failed", failure_message=None, traceback=None))

    assert bundle.admissible is False
    assert any("no failure message" in reason.lower() for reason in bundle.reasons)


def test_require_admissible_raises_for_insufficient_evidence(results_db):
    bundle = evidence.collect(_record("passed"))

    with pytest.raises(evidence.EvidenceError, match="Refusing to assert a defect"):
        evidence.require_admissible(bundle)


def test_repeated_failures_are_marked_reproducible(results_db):
    """Reproduction count comes from the store, not from a guess."""
    _record("failed")
    bundle = evidence.collect(_record("failed"))

    assert bundle.occurrences == 2
    assert bundle.reproducible is True
    assert bundle.strength in {"moderate", "strong"}


# ------------------------------------------------ summarise/classify ---

def test_a_summary_of_a_passing_test_is_refused(results_db):
    """The summariser inherits the gate."""
    result = failure_analysis.summarize_failure(evidence.collect(_record("passed")), provider)

    assert result["evidence_admissible"] is False
    assert "will not characterise" in result["statement"]


def test_a_summary_quotes_the_recorded_values_only(results_db):
    result = failure_analysis.summarize_failure(evidence.collect(_record("failed")), provider)

    assert result["evidence_admissible"] is True
    assert result["expected"] == "1800"
    assert result["actual"] == "1799"
    assert result["probable_area"] == "cart and pricing"


def test_an_assertion_failure_is_classified_as_a_product_defect(results_db):
    result = failure_analysis.classify_failure(evidence.collect(_record("failed")), provider)

    assert result["category"] == "product_defect"
    assert result["may_file_defect"] is True


def test_a_connection_error_is_classified_as_environment_not_product(results_db):
    """Infrastructure failures must never be blamed on the product."""
    result_id = _record(
        "error",
        failure_type="ConnectionError",
        failure_message="HTTPConnectionPool: Max retries exceeded: Connection refused",
        traceback="ConnectionError: Connection refused",
    )

    result = failure_analysis.classify_failure(evidence.collect(result_id), provider)

    assert result["category"] == "environment"
    assert result["may_file_defect"] is False


def test_a_missing_browser_is_classified_as_environment(results_db):
    result_id = _record(
        "error",
        failure_type="UnknownError",
        failure_message="BrowserType.launch: Executable doesn't exist",
        traceback="Error: BrowserType.launch: Executable doesn't exist at chrome.exe",
    )

    result = failure_analysis.classify_failure(evidence.collect(result_id), provider)
    assert result["category"] == "environment"


def test_a_missing_fixture_is_classified_as_a_test_defect(results_db):
    result_id = _record(
        "error",
        failure_message="fixture 'nonexistent_thing' not found",
        traceback="E  fixture 'nonexistent_thing' not found",
    )

    result = failure_analysis.classify_failure(evidence.collect(result_id), provider)
    assert result["category"] == "test_defect"
    assert result["may_file_defect"] is False


# ------------------------------------------------------ bug reports ----

def test_a_bug_report_is_refused_without_admissible_evidence(results_db):
    """The headline guarantee, stated as a test."""
    draft = bug_report.draft(evidence.collect(_record("passed")), provider)

    assert draft["drafted"] is False
    assert "no admissible execution evidence" in draft["refusal"].lower()
    assert "report" not in draft


def test_a_bug_report_is_refused_for_a_non_product_failure(results_db):
    """Triage is the second gate: an infra failure is not a product bug."""
    result_id = _record(
        "error",
        failure_type="ConnectionError",
        failure_message="Connection refused",
        traceback="ConnectionError: Connection refused",
    )

    draft = bug_report.draft(evidence.collect(result_id), provider)

    assert draft["drafted"] is False
    assert "environment" in draft["refusal"]
    assert "override_hint" in draft


def test_a_bug_report_is_drafted_for_a_genuine_product_failure(results_db):
    draft = bug_report.draft(evidence.collect(_record("failed")), provider)

    assert draft["drafted"] is True
    assert draft["verification_required"] is True
    assert draft["report"]["title"].startswith("[DRAFT]")
    assert draft["report"]["severity"] in {"S1", "S2", "S3", "S4"}


def test_the_drafted_markdown_carries_the_evidence_and_a_caveat(results_db):
    draft = bug_report.draft(evidence.collect(_record("failed")), provider)
    body = draft["markdown"]

    assert "awaiting human verification" in body
    assert "assert 1799 == 1800" in body, "the report must quote the real assertion"
    assert "TC-CART-030" in body, "the report must link back to the manual case"
    assert "Open questions for the reviewer" in body


def test_a_human_can_override_the_triage_gate_and_the_override_is_recorded(results_db):
    """The override exists, but it is never silent."""
    result_id = _record(
        "error", failure_type="ConnectionError", failure_message="Connection refused",
        traceback="ConnectionError: Connection refused",
    )

    draft = bug_report.draft(evidence.collect(result_id), provider, allow_non_product=True)

    assert draft["drafted"] is True
    assert draft["override_used"] is True


# ------------------------------------------------ defect lifecycle -----

def test_filing_a_defect_from_a_passing_result_is_refused(results_db):
    outcome = defects.file_defect(_record("passed"), provider=provider)

    assert outcome["filed"] is False
    assert "Refusing to assert a defect" in outcome["reason"]


def test_filing_a_defect_from_a_real_failure_succeeds_and_starts_at_new(results_db):
    outcome = defects.file_defect(_record("failed"), provider=provider)

    assert outcome["filed"] is True
    stored = defects.get(outcome["defect_id"])
    assert stored["status"] == "NEW"
    assert stored["history"][0]["to_status"] == "NEW"


def test_the_defect_lifecycle_rejects_an_illegal_transition(results_db):
    defect_id = defects.file_defect(_record("failed"), provider=provider)["defect_id"]

    with pytest.raises(defects.LifecycleError, match="cannot move from NEW to CLOSED"):
        defects.transition(defect_id, "CLOSED")


def test_verifying_a_fix_requires_a_note(results_db):
    """A fix cannot be signed off without recording how it was checked."""
    defect_id = defects.file_defect(_record("failed"), provider=provider)["defect_id"]
    defects.transition(defect_id, "TRIAGED")
    defects.transition(defect_id, "IN_PROGRESS")
    defects.transition(defect_id, "FIXED")

    with pytest.raises(defects.LifecycleError, match="requires a note"):
        defects.transition(defect_id, "VERIFIED")


def test_a_defect_can_travel_the_full_happy_lifecycle(results_db):
    defect_id = defects.file_defect(_record("failed"), provider=provider)["defect_id"]

    for status, note in [
        ("TRIAGED", "Reproduced by hand on the same build."),
        ("IN_PROGRESS", "Assigned to the pricing team."),
        ("FIXED", "Discount now applied to the subtotal once."),
        ("VERIFIED", "Re-ran TC-CART-030 against the fix; it passes."),
        ("CLOSED", "Shipped in release 1.4.1."),
    ]:
        defects.transition(defect_id, status, actor="qa", note=note)

    stored = defects.get(defect_id)
    assert stored["status"] == "CLOSED"
    assert len(stored["history"]) == 6  # NEW plus five transitions


def test_a_closed_defect_can_be_reopened(results_db):
    defect_id = defects.file_defect(_record("failed"), provider=provider)["defect_id"]
    for status in ("TRIAGED", "IN_PROGRESS", "FIXED"):
        defects.transition(defect_id, status, note="progress")
    defects.transition(defect_id, "VERIFIED", note="verified by re-running the case")
    defects.transition(defect_id, "CLOSED", note="released")

    defects.transition(defect_id, "REOPENED", note="the defect recurred in 1.4.2")

    assert defects.get(defect_id)["status"] == "REOPENED"


# ------------------------------------------------------- edge cases ----

def test_edge_case_suggestions_never_claim_a_failure():
    """Ideation has no evidence, so it must not imply a defect."""
    result = edge_cases.suggest("cart quantity", declared_type="integer", provider=provider)

    assert result["suggestions"], "the catalogue returned nothing for an integer field"
    assert "not findings" in result["disclaimer"]
    text = " ".join(s["scenario"] + s["why_it_matters"] for s in result["suggestions"]).lower()
    for forbidden in ("is broken", "is a bug", "currently fails", "defect confirmed"):
        assert forbidden not in text, f"an edge case suggestion asserted a defect: {forbidden!r}"


def test_edge_cases_for_an_auth_field_cover_the_expected_security_scenarios():
    result = edge_cases.suggest("bearer token", declared_type="auth", provider=provider)

    scenarios = " ".join(s["scenario"].lower() for s in result["suggestions"])
    assert "expired" in scenarios
    assert "wrong secret" in scenarios or "signed with the wrong" in scenarios


def test_edge_cases_for_money_cover_the_threshold_boundaries():
    result = edge_cases.suggest("order total", declared_type="money", provider=provider)

    scenarios = " ".join(s["scenario"].lower() for s in result["suggestions"])
    assert "threshold" in scenarios
    assert any(s["category"] == "boundary" for s in result["suggestions"])


# ------------------------------- expected/actual extraction ordering ----
# These pin the ordering contract. An earlier heuristic scanned the
# traceback for loose status codes and reported expected and actual the
# wrong way round, which is more misleading than saying nothing.

def test_expected_and_actual_are_not_inverted_by_the_traceback(results_db):
    """The assertion source appears *above* the message in a traceback."""
    result_id = _record(
        "failed",
        failure_message="assert 200 == 401",
        traceback=(
            "    def test_an_expired_token_is_rejected(api):\n"
            "        response = api.get('/api/auth/me')\n"
            ">       assert response.status == 401, (\n"
            "E       AssertionError: An expired token was accepted with status 200.\n"
            "E       assert 200 == 401"
        ),
    )

    summary = failure_analysis.summarize_failure(evidence.collect(result_id), provider)

    assert summary["actual"] == "200", "the observed value must be reported as actual"
    assert summary["expected"] == "401", "the required value must be reported as expected"


def test_expected_and_actual_are_read_from_the_assert_status_helper(results_db):
    result_id = _record(
        "failed",
        failure_message="Expected HTTP 409 but got 201 [add a product with zero stock]. Response body: {}",
        traceback="E  AssertionError: Expected HTTP 409 but got 201 [add a product with zero stock].",
    )

    summary = failure_analysis.summarize_failure(evidence.collect(result_id), provider)

    assert summary["expected"] == "409"
    assert summary["actual"] == "201"


def test_values_are_withheld_rather_than_guessed_when_unparseable(results_db):
    """Saying 'not determinable' beats inventing a pair of numbers."""
    result_id = _record(
        "failed",
        failure_message="something went wrong in the checkout flow",
        traceback="E  RuntimeError: something went wrong in the checkout flow",
    )

    summary = failure_analysis.summarize_failure(evidence.collect(result_id), provider)

    assert summary["root_cause_determinable"] is False
    assert "not stated" in summary["expected"]
    assert "not stated" in summary["actual"]
