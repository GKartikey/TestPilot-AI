"""Suite execution.

The runner turns a named suite from `testcases/suites.yaml` into a pytest
invocation, runs it as a subprocess and hands back the recorded run.

Running pytest out-of-process rather than via `pytest.main()` is
deliberate: a suite that segfaults the browser, exhausts memory or calls
`sys.exit` cannot take the platform down with it, and the exit code is
the honest one that CI would see.
"""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import analytics, registry, store
from .config import ROOT, ensure_dirs

# pytest's documented exit codes.
EXIT_MEANING = {
    0: "all tests passed",
    1: "tests were collected and run but some failed",
    2: "execution was interrupted by the user",
    3: "an internal error occurred",
    4: "pytest was misused",
    5: "no tests were collected",
}


@dataclass
class RunOutcome:
    suite: str
    environment: str
    exit_code: int
    run_id: str | None
    summary: dict[str, Any] | None
    stdout: str
    command: list[str]

    @property
    def passed(self) -> bool:
        return self.exit_code == 0

    @property
    def meaning(self) -> str:
        return EXIT_MEANING.get(self.exit_code, f"pytest exited with code {self.exit_code}")


def build_command(
    suite_name: str,
    extra_args: list[str] | None = None,
    trigger: str = "manual",
    parallel: int | None = None,
    trace: str | None = None,
) -> list[str]:
    suite = registry.get_suite(suite_name)
    command = [
        sys.executable,
        "-m",
        "pytest",
        *suite.pytest_args(),
        "--tp-record",
        f"--tp-suite={suite_name}",
        f"--tp-trigger={trigger}",
    ]
    if parallel and parallel > 1:
        command += ["-n", str(parallel)]
    if trace:
        command += [f"--tp-trace={trace}"]
    command += extra_args or []
    return command


def run_suite(
    suite_name: str,
    environment: str | None = None,
    extra_args: list[str] | None = None,
    trigger: str = "manual",
    parallel: int | None = None,
    trace: str | None = None,
    echo: bool = True,
) -> RunOutcome:
    """Execute a suite and return the recorded outcome."""
    ensure_dirs()
    registry.get_suite(suite_name)  # fail fast on an unknown suite name

    env_name = environment or os.getenv("TESTPILOT_ENV", "local")
    command = build_command(suite_name, extra_args, trigger, parallel, trace)
    environ = {**os.environ, "TESTPILOT_ENV": env_name, "PYTHONPATH": str(ROOT)}

    before = store.latest_run(suite=suite_name)
    before_id = before["id"] if before else None

    process = subprocess.Popen(
        command,
        cwd=str(ROOT),
        env=environ,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    captured: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:  # streamed, so the pipe never fills
        captured.append(line)
        if echo:
            print(line, end="")
    exit_code = process.wait()

    after = store.latest_run(suite=suite_name)
    run_id = after["id"] if after and after["id"] != before_id else None
    summary = analytics.run_summary(run_id) if run_id else None

    return RunOutcome(
        suite=suite_name,
        environment=env_name,
        exit_code=exit_code,
        run_id=run_id,
        summary=summary,
        stdout="".join(captured),
        command=command,
    )


def run_suites(names: list[str], **kwargs: Any) -> list[RunOutcome]:
    """Run several suites in order, continuing past a failing one so the
    operator gets the complete picture rather than only the first stop."""
    return [run_suite(name, **kwargs) for name in names]


def list_suites() -> list[dict[str, Any]]:
    out = []
    for name, suite in sorted(registry.load_suites().items()):
        cases = registry.cases_for_suite(name)
        out.append(
            {
                "name": name,
                "description": " ".join(suite.description.split()),
                "markers": suite.markers,
                "paths": suite.paths,
                "documented_cases": len(cases),
                "budget_seconds": suite.max_duration_seconds,
                "fail_fast": suite.fail_fast,
            }
        )
    return out


def collect_only(suite_name: str) -> list[str]:
    """What would this suite run? Answers it without executing anything."""
    suite = registry.get_suite(suite_name)
    command = [sys.executable, "-m", "pytest", *suite.pytest_args(), "--collect-only", "-q", "--no-header"]
    result = subprocess.run(
        command, cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return [
        line.strip()
        for line in result.stdout.splitlines()
        if "::" in line and not line.startswith(("=", "-"))
    ]


def within_budget(outcome: RunOutcome) -> tuple[bool, str]:
    """Check a completed run against its suite's stated time budget.

    A smoke suite that quietly grows to five minutes has stopped being a
    smoke suite, so the budget is checked rather than merely documented.
    """
    suite = registry.get_suite(outcome.suite)
    if not suite.max_duration_seconds or not outcome.summary:
        return True, "no budget declared for this suite"
    actual = (outcome.summary["run"]["duration_ms"] or 0) / 1000
    budget = suite.max_duration_seconds
    if actual <= budget:
        return True, f"{actual:.1f}s of a {budget}s budget"
    return False, f"{actual:.1f}s exceeds the {budget}s budget for {outcome.suite}"


def artifacts_for(run_id: str) -> dict[str, list[str]]:
    """Every screenshot and trace captured during a run."""
    results = store.results_for_run(run_id)
    return {
        "screenshots": [r["screenshot_path"] for r in results if r["screenshot_path"]],
        "traces": [r["trace_path"] for r in results if r["trace_path"]],
    }


def resolve_artifact(path_value: str) -> Path:
    path = Path(path_value)
    return path if path.is_absolute() else ROOT / path
