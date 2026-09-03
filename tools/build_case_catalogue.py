"""Generate docs/test-cases.md from the test case registry.

The catalogue is generated rather than hand-written so it cannot drift
from the YAML that actually drives execution. Run it after changing any
file in `testcases/`.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from testpilot import registry  # noqa: E402

HEADER = """# Test Cases

Generated from `testcases/*.yaml` by `tools/build_case_catalogue.py`.
Do not edit by hand; edit the YAML and regenerate.

Each case is a reviewable design document: objective, preconditions,
numbered steps, expected result, priority and requirement trace. The
`Automation` column is the trace link to the pytest node that executes
it, which is what lets TestPilot report coverage of the *design* rather
than a raw test count.

"""


def summary_section() -> list[str]:
    coverage = registry.coverage_summary()
    lines = [
        "## Summary",
        "",
        f"**{coverage['total_cases']} documented cases** — "
        f"{coverage['automated']} automated ({coverage['automation_rate']}%), "
        f"{coverage['manual_only']} manual only.",
        "",
        "| Dimension | Breakdown |",
        "| --- | --- |",
    ]
    for label, key in (("By layer", "by_layer"), ("By type", "by_type"),
                       ("By priority", "by_priority"), ("By module", "by_module")):
        breakdown = ", ".join(f"{k}: {v}" for k, v in coverage[key].items())
        lines.append(f"| {label} | {breakdown} |")
    lines.append("")

    lines += ["### Manual cases", "",
              "Cases deliberately left unautomated, with the reason recorded in the case itself:",
              "", "| ID | Title | Why manual |", "| --- | --- | --- |"]
    for case in registry.load_cases():
        if not case.is_automated:
            reason = case.preconditions[0] if case.preconditions else "See the case."
            lines.append(f"| `{case.id}` | {case.title} | {reason} |")
    lines.append("")
    return lines


def module_sections() -> list[str]:
    lines: list[str] = []
    by_module: dict[str, list] = {}
    for case in registry.load_cases():
        by_module.setdefault(case.module, []).append(case)

    for module in sorted(by_module):
        cases = by_module[module]
        lines += [f"## Module: {module} ({len(cases)} cases)", ""]
        lines += ["| ID | Title | Layer | Type | Pri | Requirement | Automation |",
                  "| --- | --- | --- | --- | --- | --- | --- |"]
        for case in cases:
            automation = f"`{case.automation.split('::')[-1]}`" if case.automation else "_manual_"
            lines.append(
                f"| `{case.id}` | {case.title} | {case.layer} | {case.type} | "
                f"{case.priority} | {case.requirement or '-'} | {automation} |"
            )
        lines.append("")

        for case in cases:
            lines += [f"<details><summary><strong>{case.id}</strong> — {case.title}</summary>", ""]
            if case.objective:
                lines += [f"**Objective.** {case.objective}", ""]
            if case.preconditions:
                lines += ["**Preconditions**", ""]
                lines += [f"- {p}" for p in case.preconditions]
                lines.append("")
            lines += ["**Steps**", ""]
            lines += [f"{i}. {step}" for i, step in enumerate(case.steps, 1)]
            lines += ["", f"**Expected result.** {case.expected}", ""]
            if case.test_data:
                lines += [f"**Test data.** `{case.test_data}`", ""]
            lines += [
                f"**Priority** {case.priority} &middot; "
                f"**Suites** {', '.join(case.suites) or 'none'} &middot; "
                f"**Automation** {case.automation or 'manual only'}",
                "", "</details>", "",
            ]
    return lines


def main() -> int:
    body = "\n".join([HEADER, *summary_section(), *module_sections()])
    destination = ROOT / "docs" / "test-cases.md"
    destination.write_text(body, encoding="utf-8")
    coverage = registry.coverage_summary()
    print(f"Wrote {destination} with {coverage['total_cases']} cases.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
