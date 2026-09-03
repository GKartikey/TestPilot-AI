"""The `tp` command line: the operator interface to TestPilot.

    tp suites                       list the suites and what they select
    tp cases --layer api            browse the manual test case library
    tp coverage                     automation coverage of the design
    tp run smoke                    execute a suite and record it
    tp history --suite regression   pass rate over recent runs
    tp report <run> --format html   export a report
    tp analyse <run>                AI triage of a run's failures
    tp defect file <result-id>      draft and file an evidence-backed defect
    tp defect move <id> TRIAGED     walk the defect lifecycle
    tp generate --spec <url>        draft test cases from an OpenAPI spec
    tp edges "cart quantity"        suggest edge cases for a field or rule
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import analytics, defects, registry, runner, store
from .ai import bug_report as bug_report_module
from .ai import edge_cases, evidence, failure_analysis, generator
from .ai.provider import describe_provider, get_provider
from .config import REPORTS_DIR, TESTCASES_DIR, ensure_dirs, get_environment
from .reporting import exporters

# ------------------------------------------------------------ output ---

try:
    from rich.console import Console
    from rich.table import Table

    _console = Console()
except ImportError:  # pragma: no cover - rich is a declared dependency
    _console = None


def _print(message: str = "") -> None:
    if _console:
        _console.print(message)
    else:
        print(message)


def _table(title: str, columns: list[str], rows: list[list[str]]) -> None:
    if not rows:
        _print(f"[dim]{title}: nothing to show[/dim]" if _console else f"{title}: nothing to show")
        return
    if _console:
        table = Table(title=title, title_justify="left", header_style="bold")
        for column in columns:
            table.add_column(column)
        for row in rows:
            table.add_row(*[str(cell) for cell in row])
        _console.print(table)
    else:
        print(f"\n{title}")
        print(" | ".join(columns))
        for row in rows:
            print(" | ".join(str(cell) for cell in row))


def _emit(payload: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, default=str))


def _outcome_style(outcome: str) -> str:
    return {"passed": "green", "failed": "red", "error": "red", "skipped": "yellow"}.get(outcome, "white")


# ------------------------------------------------------- subcommands ---

def cmd_suites(args: argparse.Namespace) -> int:
    suites = runner.list_suites()
    _emit(suites, args.json)
    if not args.json:
        _table(
            "Suites",
            ["Suite", "Selects", "Documented cases", "Budget", "Description"],
            [
                [
                    s["name"],
                    " or ".join(s["markers"]) or "-",
                    s["documented_cases"],
                    f"{s['budget_seconds']}s" if s["budget_seconds"] else "-",
                    s["description"][:46] + ("..." if len(s["description"]) > 46 else ""),
                ]
                for s in suites
            ],
        )
    return 0


def cmd_cases(args: argparse.Namespace) -> int:
    cases = registry.filter_cases(
        layer=args.layer, type_=args.type, priority=args.priority, module=args.module
    )
    if args.suite:
        cases = [c for c in cases if args.suite in c.suites]
    _emit(registry.as_dicts(cases), args.json)
    if not args.json:
        _table(
            f"Test cases ({len(cases)})",
            ["ID", "Title", "Layer", "Type", "Pri", "Automated"],
            [
                [c.id, c.title[:56], c.layer, c.type, c.priority, "yes" if c.is_automated else "no"]
                for c in cases
            ],
        )
        if args.detail and cases:
            for case in cases[: args.detail]:
                _print(f"\n[bold]{case.id} - {case.title}[/bold]" if _console else f"\n{case.id} - {case.title}")
                _print(f"Objective : {case.objective}")
                for i, step in enumerate(case.steps, 1):
                    _print(f"  {i}. {step}")
                _print(f"Expected  : {case.expected}")
                _print(f"Automation: {case.automation or 'manual only'}")
    return 0


def cmd_coverage(args: argparse.Namespace) -> int:
    summary = registry.coverage_summary()
    _emit(summary, args.json)
    if not args.json:
        _print(
            f"[bold]{summary['total_cases']}[/bold] documented cases, "
            f"[green]{summary['automated']}[/green] automated "
            f"({summary['automation_rate']}%), {summary['manual_only']} manual only"
            if _console
            else f"{summary['total_cases']} cases, {summary['automated']} automated "
            f"({summary['automation_rate']}%), {summary['manual_only']} manual only"
        )
        for label, key in (("By layer", "by_layer"), ("By type", "by_type"),
                           ("By priority", "by_priority"), ("By suite", "by_suite")):
            _table(label, ["Bucket", "Cases"], [[k, v] for k, v in summary[key].items()])

        executed = {r["case_id"]: r["outcome"] for r in analytics.case_execution_status()}
        if executed:
            never_run = [c.id for c in registry.load_cases() if c.is_automated and c.id not in executed]
            _print(
                f"\nLatest execution status known for {len(executed)} case(s); "
                f"{len(never_run)} automated case(s) have never been recorded."
            )
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    outcome = runner.run_suite(
        args.suite,
        environment=args.env,
        extra_args=args.pytest_args,
        trigger=args.trigger,
        parallel=args.parallel,
        trace=args.trace,
        echo=not args.json,
    )
    if outcome.summary:
        run = outcome.summary["run"]
        _emit({"run": run, "exit_code": outcome.exit_code}, args.json)
        if not args.json:
            _print(
                f"\n[bold]{outcome.suite}[/bold] on [bold]{outcome.environment}[/bold]: "
                f"[green]{run['passed']} passed[/green], [red]{run['failed']} failed[/red], "
                f"[yellow]{run['skipped']} skipped[/yellow] - {run['pass_rate']}% pass rate"
                if _console
                else f"\n{outcome.suite} on {outcome.environment}: {run['passed']} passed, "
                f"{run['failed']} failed, {run['skipped']} skipped - {run['pass_rate']}% pass rate"
            )
            ok, note = runner.within_budget(outcome)
            _print(("Duration within budget: " if ok else "[yellow]Over budget: [/yellow]") + note)
            _print(f"Run id: {run['id']}")
            if run["failed"]:
                _print(f"Triage it with:  tp analyse {run['id']}")
            _print(f"Export it with:  tp report {run['id']} --format html")
    else:
        _print(f"No run was recorded. pytest exit code {outcome.exit_code}: {outcome.meaning}")
    return outcome.exit_code


def cmd_history(args: argparse.Namespace) -> int:
    runs = analytics.history(suite=args.suite, limit=args.limit)
    _emit(runs, args.json)
    if not args.json:
        _table(
            "Execution history (oldest first)",
            ["Run", "Suite", "Env", "Started", "Pass", "Fail", "Skip", "Rate", "Trigger"],
            [
                [r["id"][-13:], r["suite"], r["environment"], (r["started_at"] or "")[:19],
                 r["passed"], r["failed"], r["skipped"], f"{r['pass_rate']}%", r["trigger"]]
                for r in runs
            ],
        )
        stats = analytics.overall_stats()
        _print(
            f"\nAcross all history: {stats['total_runs']} run(s), {stats['total_results']} result(s), "
            f"{stats['pass_rate']}% pass rate, {stats['failed']} failure(s) recorded."
        )
        flaky = analytics.flaky_tests()
        if flaky:
            _table(
                "Flaky tests (have both passed and failed)",
                ["Test", "Runs", "Failures", "Flake rate"],
                [[f["nodeid"][-64:], f["runs"], f["failures"], f"{f['flake_rate']}%"] for f in flaky],
            )
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    run_id = args.run or (store.latest_run() or {}).get("id")
    if not run_id:
        _print("No runs have been recorded yet. Try: tp run smoke")
        return 1
    summary = analytics.run_summary(run_id)
    _emit(summary, args.json)
    if not args.json:
        run = summary["run"]
        _print(f"[bold]{run['suite']}[/bold] / {run['id']}" if _console else f"{run['suite']} / {run['id']}")
        _print(
            f"{run['passed']} passed, {run['failed']} failed, {run['skipped']} skipped "
            f"({run['pass_rate']}%) in {(run['duration_ms'] or 0) / 1000:.1f}s on {run['environment']}"
        )
        _table("By layer", ["Layer", "Total", "Passed", "Failed"],
               [[r["layer"], r["total"], r["passed"], r["failed"]] for r in summary["by_layer"]])
        if summary["failures"]:
            _table(
                "Failures",
                ["Result id", "Case", "Test", "Type", "Message"],
                [
                    [f["id"], f["case_id"] or "-", f["test_name"][:38],
                     f["failure_type"], (f["failure_message"] or "")[:52]]
                    for f in summary["failures"]
                ],
            )
            _print("\nFile a defect for one of these with:  tp defect file <result id>")
        _table("Slowest", ["Test", "ms"], [[s["test_name"][:60], s["duration_ms"]] for s in summary["slowest"]])
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    diff = analytics.compare_runs(args.baseline, args.candidate)
    _emit(diff, args.json)
    if not args.json:
        for label, key in (
            ("New failures (were passing)", "new_failures"),
            ("New tests that fail", "newly_added_failing"),
            ("Fixed", "fixed"),
            ("Still failing", "still_failing"),
            ("Removed", "removed"),
        ):
            _table(label, ["Test"], [[n] for n in diff[key]])
    return 1 if (diff["new_failures"] or diff["newly_added_failing"]) else 0


def cmd_report(args: argparse.Namespace) -> int:
    run_id = args.run or (store.latest_run() or {}).get("id")
    if not run_id:
        _print("No runs have been recorded yet.")
        return 1
    formats = args.format or ["html", "json", "junit", "csv", "markdown"]
    written = exporters.export_all(run_id, formats)
    _emit(written, args.json)
    if not args.json:
        _table("Reports written", ["Format", "Path"], [[k, v] for k, v in written.items()])
    return 0


def cmd_analyse(args: argparse.Namespace) -> int:
    run_id = args.run or (store.latest_run() or {}).get("id")
    if not run_id:
        _print("No runs have been recorded yet.")
        return 1

    provider = get_provider(force_heuristic=args.offline)
    bundles = evidence.collect_for_run(run_id)
    if not bundles:
        _print(f"Run {run_id} recorded no failures, so there is nothing to triage.")
        _emit({"run": run_id, "failures_analysed": 0}, args.json)
        return 0

    rollup = failure_analysis.summarize_run(bundles, provider)
    _emit(rollup, args.json)
    if not args.json:
        info = describe_provider(provider)
        _print(f"Analysing {len(bundles)} failure(s) with the {info['provider']} provider ({info['mode']}).\n")
        _table("Triage categories", ["Category", "Failures"],
               [[k, v] for k, v in rollup["by_category"].items()])
        for item in rollup["analyses"]:
            summary, classification = item["summary"], item["classification"]
            _print(f"\n[bold]{item['nodeid']}[/bold]" if _console else f"\n{item['nodeid']}")
            if not summary.get("evidence_admissible"):
                _print(f"  {summary['statement']}")
                continue
            _print(f"  Headline : {summary['headline']}")
            _print(f"  Expected : {summary['expected']}")
            _print(f"  Actual   : {summary['actual']}")
            _print(f"  Category : {classification['category']} ({classification['confidence']} confidence)")
            _print(f"  Owner    : {classification['recommended_owner']}")
            if classification.get("may_file_defect"):
                _print(f"  Fileable : yes -> tp defect file {item['result_id']}")
            else:
                _print("  Fileable : no, this does not look like a product defect")
        _print(f"\n{rollup['note']}")
    return 0


def cmd_defect(args: argparse.Namespace) -> int:
    provider = get_provider(force_heuristic=getattr(args, "offline", False))

    if args.defect_command == "file":
        outcome = defects.file_defect(
            args.result_id, provider=provider, allow_non_product=args.force, reporter=args.reporter
        )
        _emit(outcome, args.json)
        if not args.json:
            if outcome["filed"]:
                _print(f"[green]Filed {outcome['defect_id']}[/green]: {outcome['title']}"
                       if _console else f"Filed {outcome['defect_id']}: {outcome['title']}")
                _print(f"Severity {outcome['severity']} / {outcome['priority']}, "
                       f"classified {outcome['classification']}.")
                _print("This is a draft. A human must reproduce it before it is treated as confirmed.")
                _print(f"Export it with: tp defect export {outcome['defect_id']}")
            else:
                _print(f"[yellow]Not filed.[/yellow] {outcome['reason']}" if _console
                       else f"Not filed. {outcome['reason']}")
                for reason in outcome.get("reasons", []):
                    _print(f"  - {reason}")
        return 0 if outcome["filed"] else 2

    if args.defect_command == "draft":
        bundle = evidence.collect(args.result_id)
        draft = bug_report_module.draft(bundle, provider=provider, allow_non_product=args.force)
        _emit(draft, args.json)
        if not args.json:
            if draft.get("drafted"):
                _print(draft["markdown"])
            else:
                _print(f"Refused: {draft['refusal']}")
                for reason in draft.get("reasons", []):
                    _print(f"  - {reason}")
        return 0 if draft.get("drafted") else 2

    if args.defect_command == "list":
        rows = defects.list_defects(status=args.status)
        _emit(rows, args.json)
        if not args.json:
            _table(
                f"Defects ({len(rows)})",
                ["ID", "Sev", "Pri", "Status", "Component", "Class", "Title"],
                [[d["id"], d["severity"], d["priority"], d["status"], d["component"],
                  d["classification"], d["title"][:44]] for d in rows],
            )
            _table("Metrics", ["Metric", "Value"],
                   [[k, json.dumps(v) if isinstance(v, (dict, list)) else v]
                    for k, v in defects.metrics().items()])
        return 0

    if args.defect_command == "show":
        defect = defects.get(args.defect_id)
        if defect is None:
            _print(f"No defect {args.defect_id}")
            return 1
        _emit(defect, args.json)
        if not args.json:
            _print(defect["body_markdown"])
            _table("Lifecycle history", ["From", "To", "Actor", "When", "Note"],
                   [[e["from_status"] or "-", e["to_status"], e["actor"],
                     e["created_at"][:19], (e["note"] or "")[:44]] for e in defect["history"]])
            _print(f"Allowed next: {', '.join(defect['allowed_transitions']) or 'none'}")
        return 0

    if args.defect_command == "move":
        try:
            moved = defects.transition(args.defect_id, args.status, actor=args.actor, note=args.note)
        except (defects.LifecycleError, KeyError) as exc:
            _print(f"[red]{exc}[/red]" if _console else str(exc))
            return 2
        _emit(moved, args.json)
        if not args.json:
            _print(f"{moved['defect_id']}: {moved['from']} -> {moved['to']}")
        return 0

    if args.defect_command == "export":
        path = exporters.export_defect(args.defect_id)
        _emit({"path": str(path)}, args.json)
        if not args.json:
            _print(f"Wrote {path}")
        return 0

    return 1


def cmd_generate(args: argparse.Namespace) -> int:
    provider = get_provider(force_heuristic=args.offline)
    source = args.spec or f"{get_environment().api_url}/openapi.json"
    result = generator.generate_from_spec(source, include_paths=args.path, provider=provider)
    _emit(result, args.json)

    if not args.json:
        _print(
            f"Analysed {result['operations_analysed']} operation(s) from "
            f"{result['spec_title']} v{result['spec_version']} using the {result['provider']} provider."
        )
        _table(
            f"Draft cases ({len(result['cases'])})",
            ["ID", "Type", "Pri", "Operation", "Title"],
            [[c["id"], c["type"], c["priority"], c["source_operation"], c["title"][:52]]
             for c in result["cases"][: args.limit]],
        )
        _print(f"\n{result['note']}")

    if args.write:
        destination = Path(args.write) if args.write != "-" else TESTCASES_DIR / "generated_cases.yaml"
        generator.write_cases(result, destination)
        _print(f"Wrote {len(result['cases'])} draft case(s) to {destination}")
        _print("Review them before adding 'generated' to any suite.")
    return 0


def cmd_edges(args: argparse.Namespace) -> int:
    provider = get_provider(force_heuristic=args.offline)
    result = edge_cases.suggest(
        args.subject, declared_type=args.type, context=args.context or "", limit=args.limit, provider=provider
    )
    _emit(result, args.json)
    if not args.json:
        _table(
            f"Edge cases worth covering for '{args.subject}'",
            ["Risk", "Category", "Scenario", "Why it matters"],
            [[s["risk"], s["category"], s["scenario"][:52], s["why_it_matters"][:52]]
             for s in result["suggestions"]],
        )
        _print(f"\n{result['disclaimer']}")
    return 0


def cmd_env(args: argparse.Namespace) -> int:
    environment = get_environment(args.name)
    _emit(environment.redacted(), args.json)
    if not args.json:
        _table("Environment", ["Key", "Value"],
               [[k, v] for k, v in environment.redacted().items() if k != "extra"])
        _table("AI provider", ["Key", "Value"],
               [[k, v] for k, v in describe_provider(get_provider()).items()])
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Check that the machine can actually run the suite."""
    checks: list[tuple[str, bool, str]] = []

    try:
        cases = registry.load_cases()
        checks.append(("Test case library", True, f"{len(cases)} cases loaded and valid"))
    except Exception as exc:
        checks.append(("Test case library", False, str(exc)))

    try:
        suites = registry.load_suites()
        checks.append(("Suite definitions", True, f"{len(suites)} suites defined"))
    except Exception as exc:
        checks.append(("Suite definitions", False, str(exc)))

    try:
        environment = get_environment()
        checks.append(("Environment config", True, f"{environment.name} -> {environment.base_url}"))
    except Exception as exc:
        checks.append(("Environment config", False, str(exc)))

    try:
        with store.session() as conn:
            runs = conn.execute("SELECT COUNT(*) AS n FROM test_runs").fetchone()["n"]
        checks.append(("Results database", True, f"reachable, {runs} run(s) recorded"))
    except Exception as exc:
        checks.append(("Results database", False, str(exc)))

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            version = browser.version
            browser.close()
        checks.append(("Playwright chromium", True, f"launches, version {version}"))
    except Exception as exc:
        checks.append(("Playwright chromium", False, f"{exc}. Run: playwright install chromium"))

    info = describe_provider(get_provider())
    checks.append(("AI provider", True, f"{info['provider']} ({info['mode']})"))

    _emit([{"check": c, "ok": ok, "detail": d} for c, ok, d in checks], args.json)
    if not args.json:
        _table("Environment check", ["Check", "Status", "Detail"],
               [[c, "ok" if ok else "FAILED", d] for c, ok, d in checks])
    return 0 if all(ok for _, ok, _ in checks) else 1


# ----------------------------------------------------------- parser ----

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tp", description="TestPilot - QA automation platform")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON instead of tables.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("suites", help="List the test suites.").set_defaults(func=cmd_suites)

    cases = sub.add_parser("cases", help="Browse the manual test case library.")
    cases.add_argument("--layer", choices=sorted(registry.VALID_LAYERS))
    cases.add_argument("--type", dest="type", choices=sorted(registry.VALID_TYPES))
    cases.add_argument("--priority", choices=sorted(registry.VALID_PRIORITIES))
    cases.add_argument("--module")
    cases.add_argument("--suite")
    cases.add_argument("--detail", type=int, default=0, help="Print full detail for the first N cases.")
    cases.set_defaults(func=cmd_cases)

    sub.add_parser("coverage", help="Automation coverage of the documented cases.").set_defaults(func=cmd_coverage)

    run = sub.add_parser("run", help="Execute a suite and record the result.")
    run.add_argument("suite")
    run.add_argument("--env", help="Environment name (default: TESTPILOT_ENV or 'local').")
    run.add_argument("--trigger", default="manual")
    run.add_argument("--parallel", type=int, help="Run with N pytest-xdist workers.")
    run.add_argument("--trace", choices=["off", "on", "retain-on-failure"])
    run.add_argument("pytest_args", nargs="*", help="Extra arguments passed straight to pytest.")
    run.set_defaults(func=cmd_run)

    history = sub.add_parser("history", help="Pass rate over recent runs.")
    history.add_argument("--suite")
    history.add_argument("--limit", type=int, default=15)
    history.set_defaults(func=cmd_history)

    show = sub.add_parser("show", help="Detail of one run (default: the latest).")
    show.add_argument("run", nargs="?")
    show.set_defaults(func=cmd_show)

    compare = sub.add_parser("compare", help="Diff two runs to find new failures.")
    compare.add_argument("baseline")
    compare.add_argument("candidate")
    compare.set_defaults(func=cmd_compare)

    report = sub.add_parser("report", help="Export a run report.")
    report.add_argument("run", nargs="?")
    report.add_argument("--format", action="append", choices=sorted(exporters.FORMATS))
    report.set_defaults(func=cmd_report)

    analyse = sub.add_parser("analyse", help="AI triage of a run's failures.")
    analyse.add_argument("run", nargs="?")
    analyse.add_argument("--offline", action="store_true", help="Force the rule-based provider.")
    analyse.set_defaults(func=cmd_analyse)

    defect = sub.add_parser("defect", help="Defect reporting and lifecycle.")
    defect_sub = defect.add_subparsers(dest="defect_command", required=True)

    file_cmd = defect_sub.add_parser("file", help="Draft and file a defect from a failing result.")
    file_cmd.add_argument("result_id", type=int)
    file_cmd.add_argument("--force", action="store_true",
                          help="File even when triage says this is not a product defect.")
    file_cmd.add_argument("--reporter", default="testpilot")
    file_cmd.add_argument("--offline", action="store_true")

    draft_cmd = defect_sub.add_parser("draft", help="Draft a report without filing it.")
    draft_cmd.add_argument("result_id", type=int)
    draft_cmd.add_argument("--force", action="store_true")
    draft_cmd.add_argument("--offline", action="store_true")

    list_cmd = defect_sub.add_parser("list", help="List defects.")
    list_cmd.add_argument("--status")

    show_cmd = defect_sub.add_parser("show", help="Show one defect and its history.")
    show_cmd.add_argument("defect_id")

    move_cmd = defect_sub.add_parser("move", help="Transition a defect.")
    move_cmd.add_argument("defect_id")
    move_cmd.add_argument("status")
    move_cmd.add_argument("--actor", default="qa")
    move_cmd.add_argument("--note")

    export_cmd = defect_sub.add_parser("export", help="Write a defect's markdown body.")
    export_cmd.add_argument("defect_id")

    defect.set_defaults(func=cmd_defect)

    generate = sub.add_parser("generate", help="Draft test cases from an OpenAPI specification.")
    generate.add_argument("--spec", help="URL or file path (default: the running app's /openapi.json).")
    generate.add_argument("--path", action="append", help="Only operations whose path contains this.")
    generate.add_argument("--write", nargs="?", const="-", help="Write the drafts to a YAML file.")
    generate.add_argument("--limit", type=int, default=30)
    generate.add_argument("--offline", action="store_true")
    generate.set_defaults(func=cmd_generate)

    edges = sub.add_parser("edges", help="Suggest edge cases for a field, endpoint or rule.")
    edges.add_argument("subject")
    edges.add_argument("--type", help="Declared type: integer, string, email, money, auth, collection, stock.")
    edges.add_argument("--context", help="Extra context for the model.")
    edges.add_argument("--limit", type=int, default=12)
    edges.add_argument("--offline", action="store_true")
    edges.set_defaults(func=cmd_edges)

    env_cmd = sub.add_parser("env", help="Show the resolved environment configuration.")
    env_cmd.add_argument("name", nargs="?")
    env_cmd.set_defaults(func=cmd_env)

    sub.add_parser("doctor", help="Check this machine can run the suite.").set_defaults(func=cmd_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    ensure_dirs()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:  # pragma: no cover
        _print("\nInterrupted.")
        return 130
    except (KeyError, ValueError) as exc:
        _print(f"[red]{exc}[/red]" if _console else f"Error: {exc}")
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
