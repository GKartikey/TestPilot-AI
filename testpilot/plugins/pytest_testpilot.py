"""pytest plugin: stream every test outcome into the TestPilot store.

The plugin is what turns a plain pytest run into a first-class,
queryable execution record. It:

  * opens a run row when the session starts and closes it at the end,
  * records one result row per test with timing, markers and traceback,
  * attaches the screenshot / trace / HTTP log that the UI and API
    fixtures parked on the item, and
  * resolves each nodeid back to its manual test case id.

It stays passive: if the store is unreachable the tests still run, they
just are not recorded. A reporting layer must never fail a green build.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from testpilot import registry, store

_RUN_ID_ENV = "TESTPILOT_RUN_ID"
_LAYER_MARKERS = ("api", "ui", "db", "unit", "contract")


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("testpilot")
    group.addoption(
        "--tp-record",
        action="store_true",
        default=os.getenv("TESTPILOT_RECORD", "").lower() in {"1", "true", "yes"},
        help="Persist results into the TestPilot results database.",
    )
    group.addoption("--tp-suite", default=os.getenv("TESTPILOT_SUITE", "adhoc"), help="Suite name for this run.")
    group.addoption(
        "--tp-trigger",
        default=os.getenv("TESTPILOT_TRIGGER", "manual"),
        help="What caused this run: manual, ci, pull_request, schedule.",
    )


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], capture_output=True, text=True, timeout=5, check=False
        )
        return out.stdout.strip() or None
    except Exception:
        return None


class TestPilotRecorder:
    def __init__(self, config: pytest.Config) -> None:
        self.config = config
        self.suite = config.getoption("--tp-suite")
        self.trigger = config.getoption("--tp-trigger")
        self.environment = os.getenv("TESTPILOT_ENV", "local")
        # Pinned once, at construction. Results belong to the database this
        # run opened; a test that monkeypatches the store's module globals
        # (the platform's own unit tests do) must not divert the recorder.
        self.db_path = store.RESULTS_DB
        self.run_id: str | None = None
        self.enabled = True
        self._recorded = 0

    # -- lifecycle -----------------------------------------------------
    def start(self) -> None:
        try:
            self.run_id = store.start_run(
                suite=self.suite,
                environment=self.environment,
                trigger=self.trigger,
                git_branch=os.getenv("GITHUB_HEAD_REF") or _git("rev-parse", "--abbrev-ref", "HEAD"),
                git_commit=os.getenv("GITHUB_SHA") or _git("rev-parse", "--short", "HEAD"),
                db_path=self.db_path,
            )
            os.environ[_RUN_ID_ENV] = self.run_id
        except Exception as exc:  # pragma: no cover - defensive
            self.enabled = False
            print(f"[testpilot] recording disabled: {exc}")

    def finish(self, exit_status: str) -> dict[str, Any] | None:
        if not (self.enabled and self.run_id):
            return None
        try:
            return store.finish_run(self.run_id, exit_status=exit_status, db_path=self.db_path)
        except Exception as exc:  # pragma: no cover - defensive
            print(f"[testpilot] could not finalise run: {exc}")
            return None

    # -- per test ------------------------------------------------------
    def record(self, item: pytest.Item, report: pytest.TestReport, outcome: str) -> None:
        if not (self.enabled and self.run_id):
            return

        markers = sorted({m.name for m in item.iter_markers()})
        layer = next((m for m in markers if m in _LAYER_MARKERS), "unknown")
        case = registry.case_by_automation(report.nodeid)

        failure_type = failure_message = traceback_text = None
        if outcome in {"failed", "error"}:
            traceback_text = _trim(str(report.longrepr), 12_000)
            failure_message = _first_meaningful_line(traceback_text)
            failure_type = _exception_type(report)

        payload = {
            "case_id": case.id if case else getattr(item, "_tp_case_id", None),
            "nodeid": report.nodeid,
            "test_name": item.name,
            "module": Path(str(item.fspath)).stem,
            "layer": layer,
            "markers": markers,
            "outcome": outcome,
            "duration_ms": int(report.duration * 1000),
            "failure_type": failure_type,
            "failure_message": failure_message,
            "traceback": traceback_text,
            "stdout": _trim(report.capstdout, 4_000) or None,
            "screenshot_path": getattr(item, "_tp_screenshot", None),
            "trace_path": getattr(item, "_tp_trace", None),
            "request_log": getattr(item, "_tp_requests", None),
        }
        try:
            result_id = store.record_result(self.run_id, payload, db_path=self.db_path)
            item._tp_result_id = result_id  # type: ignore[attr-defined]
            self._recorded += 1
        except Exception as exc:  # pragma: no cover - defensive
            print(f"[testpilot] could not record {report.nodeid}: {exc}")


def _trim(text: str | None, limit: int) -> str | None:
    if not text:
        return None
    return text if len(text) <= limit else text[:limit] + f"\n... [{len(text) - limit} more characters truncated]"


def _first_meaningful_line(traceback_text: str | None) -> str | None:
    """The headline of a failure, taken from pytest's rendered output.

    pytest prints the assertion message first and then explanatory
    continuations ("+  where 1199 = ...", "-  expected", "?  ^^^"). The
    first line is the one a human reads; a continuation only makes sense
    underneath it, so continuations are skipped rather than reported as
    the message.
    """
    if not traceback_text:
        return None

    rendered = [
        line.strip()[2:].strip()
        for line in traceback_text.strip().splitlines()
        if line.strip().startswith("E ") and len(line.strip()) > 2
    ]
    for line in rendered:
        if line and line[0] not in "+-?":
            return line[:600]
    if rendered:
        return rendered[0][:600]

    for line in traceback_text.strip().splitlines():
        if line.strip():
            return line.strip()[:600]
    return None


def _exception_type(report: pytest.TestReport) -> str:
    text = str(report.longrepr)
    for candidate in (
        "AssertionError",
        "TimeoutError",
        "ConnectionError",
        "HTTPStatusError",
        "KeyError",
        "TypeError",
        "ValueError",
        "AttributeError",
        "IntegrityError",
        "OperationalError",
    ):
        if candidate in text:
            return candidate
    return "UnknownError"


# ------------------------------------------------------------ hooks ----

def pytest_configure(config: pytest.Config) -> None:
    for marker, description in (
        ("api", "REST API level test"),
        ("ui", "Browser test driven by Playwright"),
        ("db", "SQL / data integrity validation"),
        ("unit", "Pure unit test of framework or platform code"),
        ("smoke", "Fast build-acceptance check"),
        ("regression", "Full regression coverage"),
        ("negative", "Invalid or malformed input"),
        ("boundary", "Limit and edge value"),
        ("auth", "Authentication or authorisation"),
        ("slow", "Long running"),
    ):
        config.addinivalue_line("markers", f"{marker}: {description}")

    if config.getoption("--tp-record"):
        recorder = TestPilotRecorder(config)
        recorder.start()
        config.pluginmanager.register(recorder, "testpilot-recorder")
        config._tp_recorder = recorder  # type: ignore[attr-defined]


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    outcome = yield
    report = outcome.get_result()
    # Expose the report to fixtures so they can decide whether to keep
    # the screenshot and the trace.
    setattr(item, f"_tp_report_{report.when}", report)

    recorder = getattr(item.config, "_tp_recorder", None)
    if recorder is None:
        return

    if report.when == "call":
        if report.passed:
            resolved = "xpassed" if hasattr(report, "wasxfail") else "passed"
        elif report.skipped:
            resolved = "xfailed" if hasattr(report, "wasxfail") else "skipped"
        else:
            resolved = "failed"
        item._tp_pending = (report, resolved)  # type: ignore[attr-defined]
    elif report.when == "setup" and report.failed:
        item._tp_pending = (report, "error")  # type: ignore[attr-defined]
    elif report.when == "setup" and report.skipped:
        item._tp_pending = (report, "skipped")  # type: ignore[attr-defined]
    elif report.when == "teardown" and report.failed and not hasattr(item, "_tp_flushed"):
        item._tp_pending = (report, "error")  # type: ignore[attr-defined]


def pytest_runtest_teardown(item: pytest.Item, nextitem: pytest.Item | None) -> None:
    """Flush after teardown so fixture-attached artefacts are included."""
    recorder = getattr(item.config, "_tp_recorder", None)
    pending = getattr(item, "_tp_pending", None)
    if recorder is None or pending is None:
        return
    report, resolved = pending
    recorder.record(item, report, resolved)
    item._tp_flushed = True  # type: ignore[attr-defined]
    item._tp_pending = None  # type: ignore[attr-defined]


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    recorder = getattr(session.config, "_tp_recorder", None)
    if recorder is None:
        return
    status = {0: "passed", 1: "failed", 2: "interrupted", 5: "no_tests"}.get(int(exitstatus), "completed")
    summary = recorder.finish(status)
    if summary:
        print(
            f"\n[testpilot] run {summary['id']} recorded: "
            f"{summary['passed']} passed, {summary['failed']} failed, "
            f"{summary['skipped']} skipped, {summary['errors']} errors"
        )


def pytest_report_header(config: pytest.Config) -> list[str]:
    lines = [f"testpilot: env={os.getenv('TESTPILOT_ENV', 'local')}"]
    if config.getoption("--tp-record"):
        lines.append(f"testpilot: recording suite={config.getoption('--tp-suite')}")
    return lines


def attach_request_log(item: pytest.Item, entries: list[dict[str, Any]]) -> None:
    """Called by the API client fixture to keep the HTTP conversation."""
    item._tp_requests = entries  # type: ignore[attr-defined]


def dumps(payload: Any) -> str:
    return json.dumps(payload, indent=2, default=str)
