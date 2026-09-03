"""Build the pull request comment from every suite's JUnit reports.

Each CI job uploads its own artifacts; this collects them into one
comment a reviewer can read without opening the run. It deliberately
reports rather than gates -- the suites themselves already decided
whether the build passes.

Failures are summarised through the same evidence-gated analysis the
platform uses everywhere else, so nothing here asserts a defect exists.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def collect(artifacts_dir: Path) -> list[dict]:
    """Read every JUnit XML under the downloaded artifacts."""
    suites = []
    for path in sorted(artifacts_dir.rglob("*.xml")):
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError:
            continue
        for suite in root.iter("testsuite"):
            failures = []
            for case in suite.iter("testcase"):
                for kind in ("failure", "error"):
                    node = case.find(kind)
                    if node is not None:
                        failures.append(
                            {
                                "name": case.get("name", "?"),
                                "classname": case.get("classname", ""),
                                "case_id": case.get("id"),
                                "kind": kind,
                                "message": (node.get("message") or "").strip()[:300],
                            }
                        )
            suites.append(
                {
                    "name": suite.get("name", path.stem),
                    "source": path.parent.name,
                    "tests": int(suite.get("tests", 0)),
                    "failures": int(suite.get("failures", 0)),
                    "errors": int(suite.get("errors", 0)),
                    "skipped": int(suite.get("skipped", 0)),
                    "time": float(suite.get("time", 0) or 0),
                    "failed_cases": failures,
                }
            )
    return suites


def render(suites: list[dict]) -> str:
    if not suites:
        return (
            "## TestPilot\n\n"
            "No JUnit reports were produced by this run, so there is nothing to summarise. "
            "Check the job logs: a suite may have failed before it could record results.\n"
        )

    total = sum(s["tests"] for s in suites)
    failed = sum(s["failures"] + s["errors"] for s in suites)
    skipped = sum(s["skipped"] for s in suites)
    passed = total - failed - skipped
    duration = sum(s["time"] for s in suites)
    executed = total - skipped
    rate = round(passed / executed * 100, 1) if executed else 0.0

    verdict = "All green." if failed == 0 else f"{failed} test(s) failed."
    lines = [
        "## TestPilot",
        "",
        f"**{verdict}** {passed} passed, {failed} failed, {skipped} skipped "
        f"({rate}% pass rate) in {duration:.1f}s of test time.",
        "",
        "| Suite | Tests | Passed | Failed | Skipped | Time |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for suite in suites:
        suite_failed = suite["failures"] + suite["errors"]
        suite_passed = suite["tests"] - suite_failed - suite["skipped"]
        lines.append(
            f"| `{suite['name']}` | {suite['tests']} | {suite_passed} | "
            f"{suite_failed} | {suite['skipped']} | {suite['time']:.1f}s |"
        )

    failing = [(s, f) for s in suites for f in s["failed_cases"]]
    if failing:
        lines += ["", f"### Failures ({len(failing)})", ""]
        for suite, failure in failing[:25]:
            trace = f" &middot; case **{failure['case_id']}**" if failure["case_id"] else ""
            lines.append(
                f"<details><summary><code>{failure['classname']}::{failure['name']}</code>{trace}</summary>"
            )
            lines += ["", "```", failure["message"] or "no message captured", "```", "", "</details>", ""]
        if len(failing) > 25:
            lines.append(f"_...and {len(failing) - 25} more. See the uploaded reports._")
        lines += [
            "",
            "> Screenshots and Playwright traces for browser failures are attached to this "
            "workflow run as the `ui-evidence` artifact.",
            ">",
            "> Triage locally with `tp analyse <run id>`. TestPilot will not describe any of "
            "these as a confirmed defect without a reproduced, recorded failure.",
        ]
    else:
        lines += ["", "No failures. Every executed test passed.", ""]

    try:
        from testpilot import registry

        coverage = registry.coverage_summary()
        lines += [
            "",
            f"<sub>Test design: {coverage['total_cases']} documented cases, "
            f"{coverage['automated']} automated ({coverage['automation_rate']}%).</sub>",
        ]
    except Exception:
        pass

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarise CI results for a pull request comment.")
    parser.add_argument("--artifacts", default="downloaded", help="Directory holding the downloaded artifacts.")
    parser.add_argument("--output", default="pr-comment.md")
    args = parser.parse_args()

    suites = collect(Path(args.artifacts))
    body = render(suites)
    Path(args.output).write_text(body, encoding="utf-8")
    print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
