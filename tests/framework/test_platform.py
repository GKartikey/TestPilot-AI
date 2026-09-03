"""Unit tests for the TestPilot platform itself.

The test framework is production code and gets tested like production
code: a broken registry or a wrong pass-rate calculation silently
corrupts every report built on top of it.
"""
from __future__ import annotations

import json

import pytest

from testpilot import analytics, registry, store
from testpilot.ai import generator
from testpilot.ai.provider import HeuristicProvider, get_provider, is_heuristic
from testpilot.reporting import exporters

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------- registry ---

def test_the_test_case_library_loads_and_validates():
    """Every committed case must satisfy the registry's schema."""
    cases = registry.load_cases()

    assert len(cases) >= 40, f"only {len(cases)} test cases are documented"
    assert all(case.expected for case in cases)
    assert all(case.steps for case in cases)


def test_test_case_ids_are_unique():
    ids = [case.id for case in registry.load_cases()]

    duplicates = {i for i in ids if ids.count(i) > 1}
    assert not duplicates, f"duplicate test case ids: {sorted(duplicates)}"


def test_the_smoke_and_regression_suites_are_defined():
    suites = registry.load_suites()

    assert "smoke" in suites
    assert "regression" in suites
    assert suites["smoke"].markers, "the smoke suite must select something"


def test_a_suite_definition_translates_into_pytest_arguments():
    args = registry.get_suite("smoke").pytest_args()

    assert "-m" in args
    assert "smoke" in " ".join(args)


def test_every_automated_case_points_at_a_test_file_that_exists():
    """A dangling automation reference means the coverage figure lies."""
    from pathlib import Path

    root = Path(registry.TESTCASES_DIR).parent
    missing = []
    for case in registry.load_cases():
        if not case.automation:
            continue
        path = root / case.automation.split("::")[0]
        if not path.exists():
            missing.append(f"{case.id} -> {case.automation}")

    assert not missing, "test cases reference automation that does not exist: " + ", ".join(missing)


def test_coverage_summary_adds_up():
    summary = registry.coverage_summary()

    assert summary["automated"] + summary["manual_only"] == summary["total_cases"]
    assert 0 <= summary["automation_rate"] <= 100
    assert sum(summary["by_layer"].values()) == summary["total_cases"]


def test_a_nodeid_resolves_back_to_its_manual_case():
    """The link from automation to design is what makes traceability work."""
    case = registry.case_by_automation("tests/api/test_auth.py::test_login_with_seeded_customer_returns_a_usable_token")

    assert case is not None, "a known automated test did not resolve to a manual case"
    assert case.layer == "api"


def test_an_invalid_case_is_rejected_by_the_registry(tmp_path):
    """The registry is a gate, not a loader."""
    (tmp_path / "bad.yaml").write_text(
        json.dumps(
            {"cases": [{"id": "TC-BAD-001", "title": "no expected result", "module": "x",
                        "layer": "api", "type": "functional", "priority": "P1",
                        "steps": ["do a thing"], "expected": ""}]}
        ),
        encoding="utf-8",
    )

    with pytest.raises(registry.RegistryError, match="expected result"):
        registry.load_cases(tmp_path)


# ------------------------------------------------------------- store ---

@pytest.fixture
def results_db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "RESULTS_DB", tmp_path / "results.db")
    return tmp_path / "results.db"


def test_a_run_tallies_its_results_when_it_finishes(results_db):
    run_id = store.start_run(suite="unit", environment="test")
    for outcome in ["passed", "passed", "failed", "skipped"]:
        store.record_result(run_id, {"nodeid": f"t::{outcome}{id(outcome)}", "outcome": outcome, "duration_ms": 10})

    summary = store.finish_run(run_id)

    assert summary["total"] == 4
    assert summary["passed"] == 2
    assert summary["failed"] == 1
    assert summary["skipped"] == 1


def test_the_pass_rate_excludes_skipped_tests(results_db):
    """A skipped test is neither a pass nor a failure; counting it as
    either misrepresents the health of the build."""
    run_id = store.start_run(suite="unit", environment="test")
    store.record_result(run_id, {"nodeid": "t::a", "outcome": "passed"})
    store.record_result(run_id, {"nodeid": "t::b", "outcome": "failed"})
    store.record_result(run_id, {"nodeid": "t::c", "outcome": "skipped"})
    store.finish_run(run_id)

    assert analytics.run_summary(run_id)["run"]["pass_rate"] == 50.0


def test_run_comparison_separates_new_failures_from_pre_existing_ones(results_db):
    """This is the query a pull request actually needs."""
    baseline = store.start_run(suite="regression", environment="test")
    store.record_result(baseline, {"nodeid": "t::stable", "outcome": "passed"})
    store.record_result(baseline, {"nodeid": "t::already_broken", "outcome": "failed"})
    store.record_result(baseline, {"nodeid": "t::will_be_fixed", "outcome": "failed"})
    store.finish_run(baseline)

    candidate = store.start_run(suite="regression", environment="test")
    store.record_result(candidate, {"nodeid": "t::stable", "outcome": "failed"})
    store.record_result(candidate, {"nodeid": "t::already_broken", "outcome": "failed"})
    store.record_result(candidate, {"nodeid": "t::will_be_fixed", "outcome": "passed"})
    store.record_result(candidate, {"nodeid": "t::brand_new", "outcome": "failed"})
    store.finish_run(candidate)

    diff = analytics.compare_runs(baseline, candidate)

    assert diff["new_failures"] == ["t::stable"]
    assert diff["still_failing"] == ["t::already_broken"]
    assert diff["fixed"] == ["t::will_be_fixed"]
    assert diff["newly_added_failing"] == ["t::brand_new"]


def test_a_consistently_failing_test_is_not_reported_as_flaky(results_db):
    """A test that always fails is broken, not flaky; conflating the two
    hides real regressions behind a 'known flake' label."""
    for _ in range(4):
        run_id = store.start_run(suite="unit", environment="test")
        store.record_result(run_id, {"nodeid": "t::always_red", "outcome": "failed"})
        store.record_result(run_id, {"nodeid": "t::always_green", "outcome": "passed"})
        store.finish_run(run_id)

    assert analytics.flaky_tests(min_runs=2) == []


def test_a_test_that_sometimes_passes_is_reported_as_flaky(results_db):
    for outcome in ["passed", "failed", "passed", "failed"]:
        run_id = store.start_run(suite="unit", environment="test")
        store.record_result(run_id, {"nodeid": "t::wobbly", "outcome": outcome})
        store.finish_run(run_id)

    flaky = analytics.flaky_tests(min_runs=2)

    assert [f["nodeid"] for f in flaky] == ["t::wobbly"]
    assert flaky[0]["flake_rate"] == 50.0


# --------------------------------------------------------- reporting ---

@pytest.fixture
def populated_run(results_db, monkeypatch, tmp_path):
    monkeypatch.setattr(exporters, "REPORTS_DIR", tmp_path)
    run_id = store.start_run(suite="regression", environment="test", git_branch="main", git_commit="abc1234")
    store.record_result(run_id, {"nodeid": "tests/api/t.py::ok", "test_name": "ok", "module": "t",
                                 "layer": "api", "outcome": "passed", "duration_ms": 12})
    store.record_result(run_id, {"nodeid": "tests/api/t.py::bad", "test_name": "bad", "module": "t",
                                 "layer": "api", "outcome": "failed", "duration_ms": 30,
                                 "failure_type": "AssertionError", "failure_message": "assert 1 == 2",
                                 "traceback": "E  assert 1 == 2", "case_id": "TC-X-001"})
    store.finish_run(run_id)
    return run_id


def test_html_export_contains_the_failure_and_its_traceback(populated_run, tmp_path):
    path = exporters.export_html(populated_run, tmp_path / "report.html")
    body = path.read_text(encoding="utf-8")

    assert "assert 1 == 2" in body
    assert "TC-X-001" in body
    assert "<html" in body.lower()


def test_junit_export_is_wellformed_and_counts_failures(populated_run, tmp_path):
    from xml.etree import ElementTree as ET

    path = exporters.export_junit(populated_run, tmp_path / "junit.xml")
    root = ET.parse(path).getroot()
    suite = root.find("testsuite")

    assert suite.get("tests") == "2"
    assert suite.get("failures") == "1"
    assert len(suite.findall("testcase")) == 2


def test_csv_export_has_a_header_and_one_row_per_test(populated_run, tmp_path):
    path = exporters.export_csv(populated_run, tmp_path / "results.csv")
    lines = path.read_text(encoding="utf-8").strip().splitlines()

    assert lines[0].startswith("case_id,nodeid")
    assert len(lines) == 3


def test_markdown_export_is_suitable_for_a_pull_request_comment(populated_run, tmp_path):
    body = exporters.export_markdown(populated_run, tmp_path / "report.md").read_text(encoding="utf-8")

    assert body.startswith("## TestPilot report")
    assert "1 passed / 1 failed" in body
    assert "<details>" in body


def test_json_export_round_trips(populated_run, tmp_path):
    payload = json.loads(exporters.export_json(populated_run, tmp_path / "report.json").read_text(encoding="utf-8"))

    assert payload["run"]["id"] == populated_run
    assert len(payload["results"]) == 2


# ---------------------------------------------------------- AI plumbing ---

def test_the_offline_provider_is_selected_when_ai_is_switched_off(monkeypatch):
    """CI must never fail because a model key is absent."""
    monkeypatch.setenv("TESTPILOT_AI", "off")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-not-really-used")

    assert is_heuristic(get_provider())


def test_the_offline_provider_is_selected_when_no_key_is_present(monkeypatch):
    monkeypatch.delenv("TESTPILOT_AI", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    assert is_heuristic(get_provider())


def test_generated_cases_cover_the_four_design_axes():
    """The generator must not produce only happy-path cases."""
    spec = {
        "info": {"title": "Sample", "version": "1"},
        "paths": {
            "/api/cart/items": {
                "post": {
                    "operationId": "add_item",
                    "tags": ["cart"],
                    "summary": "Add an item to the cart",
                    "security": [{"bearer": []}],
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"properties": {"product_id": {"type": "integer"},
                                                          "quantity": {"type": "integer"}}}
                            }
                        }
                    },
                    "responses": {"201": {}, "422": {}},
                }
            }
        },
    }

    result = generator.generate_from_spec(spec, provider=HeuristicProvider())
    types = {case["type"] for case in result["cases"]}

    assert "functional" in types
    assert "negative" in types
    assert "security" in types
    assert all(case["status"] == "draft" for case in result["cases"])
    assert all(case["id"].startswith("TC-GEN-") for case in result["cases"])


def test_generated_cases_are_marked_as_drafts_needing_review():
    spec = {"info": {"title": "S", "version": "1"},
            "paths": {"/api/products": {"get": {"operationId": "list", "tags": ["products"], "responses": {"200": {}}}}}}

    result = generator.generate_from_spec(spec, provider=HeuristicProvider())

    assert "review" in result["note"].lower()
    assert result["operations_analysed"] == 1


def test_the_generator_reads_boundaries_from_the_specification():
    """Bounds in the generated cases must come from the spec, not be invented."""
    spec = {
        "info": {"title": "S", "version": "1"},
        "paths": {
            "/api/products": {
                "get": {
                    "operationId": "list",
                    "tags": ["products"],
                    "parameters": [{"name": "page_size", "in": "query",
                                    "schema": {"type": "integer", "minimum": 1, "maximum": 100}}],
                    "responses": {"200": {}},
                }
            }
        },
    }

    result = generator.generate_from_spec(spec, provider=HeuristicProvider())
    boundary = [c for c in result["cases"] if c["type"] == "boundary"]

    assert boundary, "a parameter with a declared range produced no boundary case"
    assert boundary[0]["test_data"] == {"minimum": 1, "maximum": 100}
