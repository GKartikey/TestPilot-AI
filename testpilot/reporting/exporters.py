"""Exportable test reports.

Five formats, each with a different consumer:

  html     the human-readable run report, with screenshots inlined
  json     machine consumption and archival
  junit    what CI systems and PR annotations understand
  csv      what a test lead pastes into a tracker or spreadsheet
  markdown what gets posted as a pull request comment
"""
from __future__ import annotations

import base64
import csv
import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from .. import analytics, defects, registry, store
from ..config import REPORTS_DIR, ensure_dirs


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _target(run_id: str, extension: str, destination: Path | None = None) -> Path:
    ensure_dirs()
    if destination:
        destination.parent.mkdir(parents=True, exist_ok=True)
        return destination
    return REPORTS_DIR / f"{run_id}.{extension}"


# -------------------------------------------------------------- json ----

def export_json(run_id: str, destination: Path | None = None) -> Path:
    summary = analytics.run_summary(run_id)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run": summary["run"],
        "by_layer": summary["by_layer"],
        "slowest": summary["slowest"],
        "results": store.results_for_run(run_id),
        "case_coverage": registry.coverage_summary(),
        "defects": defects.list_defects(),
    }
    path = _target(run_id, "json", destination)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


# ------------------------------------------------------------- junit ----

def export_junit(run_id: str, destination: Path | None = None) -> Path:
    """JUnit XML, the lingua franca of CI test reporting."""
    summary = analytics.run_summary(run_id)
    run = summary["run"]
    results = store.results_for_run(run_id)

    suites = ET.Element("testsuites", name="TestPilot", tests=str(run["total"] or 0))
    suite = ET.SubElement(
        suites,
        "testsuite",
        name=run["suite"],
        tests=str(run["total"] or 0),
        failures=str(run["failed"] or 0),
        errors=str(run["errors"] or 0),
        skipped=str(run["skipped"] or 0),
        time=f"{(run['duration_ms'] or 0) / 1000:.3f}",
        timestamp=run["started_at"],
    )
    properties = ET.SubElement(suite, "properties")
    for key in ("environment", "trigger", "git_branch", "git_commit"):
        ET.SubElement(properties, "property", name=key, value=str(run.get(key) or ""))

    for result in results:
        case = ET.SubElement(
            suite,
            "testcase",
            classname=f"{result['layer']}.{result['module']}",
            name=result["test_name"],
            time=f"{result['duration_ms'] / 1000:.3f}",
        )
        if result["case_id"]:
            case.set("id", result["case_id"])
        outcome = result["outcome"]
        if outcome == "failed":
            node = ET.SubElement(
                case, "failure", message=(result["failure_message"] or "assertion failed")[:400],
                type=result["failure_type"] or "AssertionError",
            )
            node.text = result["traceback"] or ""
        elif outcome == "error":
            node = ET.SubElement(case, "error", message=(result["failure_message"] or "error")[:400])
            node.text = result["traceback"] or ""
        elif outcome == "skipped":
            ET.SubElement(case, "skipped")

    path = _target(run_id, "xml", destination)
    ET.ElementTree(suites).write(path, encoding="utf-8", xml_declaration=True)
    return path


# --------------------------------------------------------------- csv ----

def export_csv(run_id: str, destination: Path | None = None) -> Path:
    results = store.results_for_run(run_id)
    path = _target(run_id, "csv", destination)
    columns = [
        "case_id", "nodeid", "test_name", "module", "layer", "outcome",
        "duration_ms", "failure_type", "failure_message", "screenshot_path", "trace_path",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for result in results:
            writer.writerow({k: result.get(k) for k in columns})
    return path


# ---------------------------------------------------------- markdown ----

def export_markdown(run_id: str, destination: Path | None = None) -> Path:
    summary = analytics.run_summary(run_id)
    run = summary["run"]
    lines = [
        f"## TestPilot report - `{run['suite']}`",
        "",
        f"**{run['passed']} passed / {run['failed']} failed / {run['skipped']} skipped** "
        f"({summary['run']['pass_rate']}% pass rate) in {(run['duration_ms'] or 0) / 1000:.1f}s",
        "",
        f"| Field | Value |",
        f"| --- | --- |",
        f"| Run | `{run['id']}` |",
        f"| Environment | {run['environment']} |",
        f"| Trigger | {run['trigger']} |",
        f"| Branch | {run.get('git_branch') or 'n/a'} |",
        f"| Commit | {run.get('git_commit') or 'n/a'} |",
        "",
        "### Results by layer",
        "",
        "| Layer | Total | Passed | Failed |",
        "| --- | ---: | ---: | ---: |",
    ]
    for row in summary["by_layer"]:
        lines.append(f"| {row['layer']} | {row['total']} | {row['passed']} | {row['failed']} |")

    if summary["failures"]:
        lines += ["", "### Failures", ""]
        for failure in summary["failures"]:
            lines.append(f"<details><summary><code>{failure['nodeid']}</code></summary>")
            lines.append("")
            if failure["case_id"]:
                lines.append(f"Manual case: **{failure['case_id']}**  ")
            lines.append(f"Type: `{failure['failure_type']}`")
            lines.append("")
            lines.append("```")
            lines.append((failure["failure_message"] or "no message captured")[:800])
            lines.append("```")
            for artefact in (failure["screenshot_path"], failure["trace_path"]):
                if artefact:
                    lines.append(f"- Artefact: `{artefact}`")
            lines.append("")
            lines.append("</details>")
            lines.append("")
    else:
        lines += ["", "### Failures", "", "None. Every executed test passed.", ""]

    path = _target(run_id, "md", destination)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# -------------------------------------------------------------- html ----

_CSS = """
:root{--bg:#f5f6f8;--surface:#fff;--ink:#1b1f24;--muted:#5c6673;--line:#e1e5ea;
--pass:#1a7f45;--fail:#c0342c;--skip:#a86b00;--brand:#1f6feb}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.55 -apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:28px}
h1{font-size:23px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 10px}
.sub{color:var(--muted);margin:0 0 22px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-bottom:8px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px}
.card .n{font-size:26px;font-weight:700;line-height:1.1}
.card .l{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.5px}
.pass{color:var(--pass)}.fail{color:var(--fail)}.skip{color:var(--skip)}
.bar{height:10px;border-radius:5px;background:var(--line);overflow:hidden;display:flex;margin:14px 0 4px}
.bar i{display:block;height:100%}
.bar .p{background:var(--pass)}.bar .f{background:var(--fail)}.bar .s{background:var(--skip)}
table{width:100%;border-collapse:collapse;background:var(--surface);
border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);background:#fafbfc}
tr:last-child td{border-bottom:none}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
code{font-family:ui-monospace,Consolas,monospace;font-size:12.5px}
.badge{display:inline-block;padding:2px 8px;border-radius:20px;font-size:11px;font-weight:700;
text-transform:uppercase;letter-spacing:.4px}
.badge.passed{background:#e6f5ec;color:var(--pass)}
.badge.failed,.badge.error{background:#fdecea;color:var(--fail)}
.badge.skipped,.badge.xfailed{background:#fdf3e0;color:var(--skip)}
details{background:var(--surface);border:1px solid var(--line);border-radius:10px;
padding:12px 14px;margin-bottom:10px}
summary{cursor:pointer;font-weight:600}
pre{background:#1b1f24;color:#e6edf3;padding:12px;border-radius:8px;overflow-x:auto;font-size:12px}
img.shot{max-width:100%;border:1px solid var(--line);border-radius:8px;margin-top:10px}
.meta{color:var(--muted);font-size:12.5px}
footer{color:var(--muted);font-size:12px;margin-top:32px;padding-top:14px;border-top:1px solid var(--line)}
"""


def _embed_screenshot(path_value: str | None) -> str:
    """Inline the PNG so the report is a single portable file."""
    if not path_value:
        return ""
    path = Path(path_value)
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.exists() or path.stat().st_size > 4_000_000:
        return f'<p class="meta">Screenshot on disk: <code>{html.escape(str(path_value))}</code></p>'
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return (
        f'<p class="meta">Failure screenshot (<code>{html.escape(path.name)}</code>):</p>'
        f'<img class="shot" alt="Failure screenshot" src="data:image/png;base64,{encoded}">'
    )


def export_html(run_id: str, destination: Path | None = None) -> Path:
    summary = analytics.run_summary(run_id)
    run = summary["run"]
    results = store.results_for_run(run_id)
    total = max(run["total"] or 0, 1)

    rows = "\n".join(
        f"<tr><td><code>{html.escape(r['test_name'])}</code>"
        f"<div class=meta>{html.escape(r['nodeid'])}</div></td>"
        f"<td>{html.escape(r['case_id'] or '-')}</td>"
        f"<td>{html.escape(r['layer'])}</td>"
        f"<td><span class='badge {r['outcome']}'>{r['outcome']}</span></td>"
        f"<td class=num>{r['duration_ms']}</td></tr>"
        for r in results
    )

    failure_blocks = []
    for failure in summary["failures"]:
        full = next((r for r in results if r["id"] == failure["id"]), failure)
        trace_line = (
            f'<p class="meta">Playwright trace: <code>{html.escape(full.get("trace_path") or "")}</code> '
            f'&mdash; open with <code>playwright show-trace &lt;file&gt;</code></p>'
            if full.get("trace_path")
            else ""
        )
        request_line = (
            f'<p class="meta">HTTP conversation captured:</p><pre>{html.escape((full.get("request_log") or "")[:3000])}</pre>'
            if full.get("request_log")
            else ""
        )
        failure_blocks.append(
            f"<details open><summary>{html.escape(failure['test_name'])} "
            f"<span class='badge failed'>{html.escape(failure['failure_type'] or 'error')}</span></summary>"
            f"<p class=meta>{html.escape(failure['nodeid'])}"
            + (f" &middot; case {html.escape(failure['case_id'])}" if failure["case_id"] else "")
            + "</p>"
            f"<pre>{html.escape((full.get('traceback') or failure['failure_message'] or '')[:6000])}</pre>"
            f"{_embed_screenshot(full.get('screenshot_path'))}{trace_line}{request_line}</details>"
        )

    layer_rows = "\n".join(
        f"<tr><td>{html.escape(row['layer'])}</td><td class=num>{row['total']}</td>"
        f"<td class='num pass'>{row['passed']}</td><td class='num fail'>{row['failed']}</td></tr>"
        for row in summary["by_layer"]
    )
    slowest_rows = "\n".join(
        f"<tr><td><code>{html.escape(row['test_name'])}</code></td><td class=num>{row['duration_ms']} ms</td></tr>"
        for row in summary["slowest"]
    )

    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TestPilot report - {html.escape(run['suite'])}</title>
<style>{_CSS}</style></head><body><div class="wrap">
<h1>TestPilot execution report</h1>
<p class="sub">Suite <strong>{html.escape(run['suite'])}</strong> on environment
<strong>{html.escape(run['environment'])}</strong> &middot; run <code>{html.escape(run['id'])}</code>
&middot; {html.escape(run['started_at'])}</p>

<div class="cards">
  <div class="card"><div class="n">{run['total']}</div><div class="l">Total</div></div>
  <div class="card"><div class="n pass">{run['passed']}</div><div class="l">Passed</div></div>
  <div class="card"><div class="n fail">{run['failed']}</div><div class="l">Failed</div></div>
  <div class="card"><div class="n skip">{run['skipped']}</div><div class="l">Skipped</div></div>
  <div class="card"><div class="n">{run['pass_rate']}%</div><div class="l">Pass rate</div></div>
  <div class="card"><div class="n">{(run['duration_ms'] or 0) / 1000:.1f}s</div><div class="l">Duration</div></div>
</div>

<div class="bar">
  <i class="p" style="width:{(run['passed'] or 0) / total * 100:.1f}%"></i>
  <i class="f" style="width:{(run['failed'] or 0) / total * 100:.1f}%"></i>
  <i class="s" style="width:{(run['skipped'] or 0) / total * 100:.1f}%"></i>
</div>
<p class="meta">Trigger: {html.escape(run['trigger'])} &middot;
Branch: {html.escape(run.get('git_branch') or 'n/a')} &middot;
Commit: {html.escape(run.get('git_commit') or 'n/a')}</p>

<h2>Failures ({len(summary['failures'])})</h2>
{''.join(failure_blocks) or '<div class="card">No failures. Every executed test passed.</div>'}

<h2>Results by layer</h2>
<table><thead><tr><th>Layer</th><th class=num>Total</th><th class=num>Passed</th>
<th class=num>Failed</th></tr></thead><tbody>{layer_rows}</tbody></table>

<h2>Slowest tests</h2>
<table><thead><tr><th>Test</th><th class=num>Duration</th></tr></thead>
<tbody>{slowest_rows}</tbody></table>

<h2>All results</h2>
<table><thead><tr><th>Test</th><th>Case</th><th>Layer</th><th>Outcome</th>
<th class=num>ms</th></tr></thead><tbody>{rows}</tbody></table>

<footer>Generated by TestPilot at {datetime.now(timezone.utc).isoformat(timespec='seconds')}.
Failure analysis in this platform is evidence-gated: no defect is asserted without a recorded failing execution.</footer>
</div></body></html>"""

    path = _target(run_id, "html", destination)
    path.write_text(document, encoding="utf-8")
    return path


# ------------------------------------------------------------ bundle ----

FORMATS = {
    "html": export_html,
    "json": export_json,
    "junit": export_junit,
    "csv": export_csv,
    "markdown": export_markdown,
}


def export_all(run_id: str, formats: list[str] | None = None) -> dict[str, str]:
    chosen = formats or list(FORMATS)
    written: dict[str, str] = {}
    for name in chosen:
        if name not in FORMATS:
            raise KeyError(f"Unknown format {name!r}. Known formats: {', '.join(FORMATS)}")
        written[name] = str(FORMATS[name](run_id))
    return written


def export_defect(defect_id: str, destination: Path | None = None) -> Path:
    """Write one defect's markdown body, ready to paste into a tracker."""
    defect = defects.get(defect_id)
    if defect is None:
        raise KeyError(f"Unknown defect {defect_id!r}")
    ensure_dirs()
    path = destination or REPORTS_DIR / f"{defect_id}.md"
    path.write_text(defect["body_markdown"], encoding="utf-8")
    return path
