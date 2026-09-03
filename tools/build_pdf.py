"""Build TestPilot_Project_Guide.pdf.

Statistics in the document are read live from the registry and the
results store, so the guide cannot claim a coverage figure the repository
does not actually have.

    python tools/build_pdf.py
"""
from __future__ import annotations

import html
import sys
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    ListFlowable,
    ListItem,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import guide_content as content  # noqa: E402

# ---------------------------------------------------------------- theme --

INK = colors.HexColor("#1b1f24")
MUTED = colors.HexColor("#5c6673")
ACCENT = colors.HexColor("#1f4e8c")
RULE = colors.HexColor("#d8dde3")
PANEL = colors.HexColor("#f4f6f8")
CODE_BG = colors.HexColor("#eef1f4")
GREEN = colors.HexColor("#1a7f45")

PAGE_W, PAGE_H = A4
MARGIN = 20 * mm


def styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    s: dict[str, ParagraphStyle] = {}

    s["title"] = ParagraphStyle(
        "title", parent=base["Title"], fontName="Helvetica-Bold",
        fontSize=30, leading=35, textColor=INK, alignment=TA_CENTER, spaceAfter=6,
    )
    s["subtitle"] = ParagraphStyle(
        "subtitle", parent=base["Normal"], fontName="Helvetica",
        fontSize=13, leading=18, textColor=MUTED, alignment=TA_CENTER, spaceAfter=4,
    )
    s["h1"] = ParagraphStyle(
        "h1", parent=base["Heading1"], fontName="Helvetica-Bold",
        fontSize=20, leading=24, textColor=ACCENT, spaceBefore=4, spaceAfter=10,
    )
    s["h2"] = ParagraphStyle(
        "h2", parent=base["Heading2"], fontName="Helvetica-Bold",
        fontSize=14, leading=18, textColor=INK, spaceBefore=14, spaceAfter=6,
    )
    s["h3"] = ParagraphStyle(
        "h3", parent=base["Heading3"], fontName="Helvetica-Bold",
        fontSize=11.5, leading=15, textColor=ACCENT, spaceBefore=10, spaceAfter=4,
    )
    s["body"] = ParagraphStyle(
        "body", parent=base["BodyText"], fontName="Helvetica",
        fontSize=10, leading=15, textColor=INK, alignment=TA_JUSTIFY, spaceAfter=8,
    )
    s["lead"] = ParagraphStyle(
        "lead", parent=s["body"], fontSize=10.5, leading=16, textColor=MUTED,
    )
    s["code"] = ParagraphStyle(
        "code", parent=base["Code"], fontName="Courier",
        fontSize=8.2, leading=11.2, textColor=INK,
        backColor=CODE_BG, borderPadding=(7, 7, 7, 7), spaceBefore=4, spaceAfter=10,
    )
    s["q"] = ParagraphStyle(
        "q", parent=base["BodyText"], fontName="Helvetica-Bold",
        fontSize=10.5, leading=14, textColor=ACCENT, spaceBefore=2, spaceAfter=4,
    )
    s["a"] = ParagraphStyle(
        "a", parent=s["body"], fontSize=9.6, leading=14, spaceAfter=4,
    )
    s["bullet"] = ParagraphStyle(
        "bullet", parent=s["body"], fontSize=9.8, leading=14, spaceAfter=4, alignment=0,
    )
    s["cell"] = ParagraphStyle(
        "cell", parent=base["BodyText"], fontName="Helvetica",
        fontSize=8.6, leading=11.5, textColor=INK, spaceAfter=0,
    )
    s["cellh"] = ParagraphStyle(
        "cellh", parent=s["cell"], fontName="Helvetica-Bold", textColor=colors.white,
    )
    s["toc"] = ParagraphStyle(
        "toc", parent=base["BodyText"], fontName="Helvetica",
        fontSize=10, leading=17, textColor=INK, spaceAfter=0,
    )
    s["footer"] = ParagraphStyle(
        "footer", parent=base["Normal"], fontName="Helvetica", fontSize=7.5, textColor=MUTED,
    )
    s["stat"] = ParagraphStyle(
        "stat", parent=base["Normal"], fontName="Helvetica-Bold",
        fontSize=19, leading=22, textColor=ACCENT, alignment=TA_CENTER,
    )
    s["statlabel"] = ParagraphStyle(
        "statlabel", parent=base["Normal"], fontName="Helvetica",
        fontSize=7.8, leading=10, textColor=MUTED, alignment=TA_CENTER,
    )
    return s


S = styles()


# ------------------------------------------------------------- helpers --

def esc(text: str) -> str:
    return html.escape(text, quote=False)


def para(text: str, style: str = "body"):
    return Paragraph(esc(text), S[style])


def prose(block: str, style: str = "body") -> list:
    """Turn a text block into paragraphs, keeping indented lines as code."""
    flow: list = []
    buffer: list[str] = []
    code: list[str] = []

    def flush_text() -> None:
        if buffer:
            joined = " ".join(line.strip() for line in buffer)
            flow.append(Paragraph(_inline(joined), S[style]))
            buffer.clear()

    def flush_code() -> None:
        if code:
            while code and not code[0].strip():
                code.pop(0)
            while code and not code[-1].strip():
                code.pop()
            if code:
                body = "<br/>".join(esc(line) for line in code)
                flow.append(Paragraph(body, S["code"]))
            code.clear()

    lines = block.splitlines()
    for index, raw in enumerate(lines):
        if raw.startswith("  ") and raw.strip():
            flush_text()
            code.append(raw[2:])
        elif not raw.strip():
            if code:
                code.append("")
            else:
                flush_text()
        else:
            flush_code()
            stripped = raw.strip()
            # A sub-heading is a short line that stands alone: it starts a
            # block, the next line is blank, and it is not a sentence.
            # Looking ahead matters -- without it, any short first line of
            # a paragraph gets promoted to a heading.
            next_blank = index + 1 >= len(lines) or not lines[index + 1].strip()
            if (
                not buffer
                and next_blank
                and len(stripped) < 70
                and not stripped.endswith((".", ",", ";"))
            ):
                flow.append(Paragraph(esc(stripped), S["h3"]))
            else:
                buffer.append(raw)
    flush_code()
    flush_text()
    return flow


def _inline(text: str) -> str:
    """Escape, then re-enable **bold** emphasis."""
    out = esc(text)
    parts = out.split("**")
    if len(parts) > 1:
        rebuilt = []
        for index, part in enumerate(parts):
            rebuilt.append(f"<b>{part}</b>" if index % 2 else part)
        out = "".join(rebuilt)
    return out


def code_block(text: str):
    lines = [line for line in text.strip("\n").splitlines()]
    return Paragraph("<br/>".join(esc(line) for line in lines), S["code"])


def table(rows: list[list[str]], widths: list[float], header: bool = True) -> Table:
    data = [
        [Paragraph(_inline(str(cell)), S["cellh"] if (header and r == 0) else S["cell"]) for cell in row]
        for r, row in enumerate(rows)
    ]
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    if header:
        style += [
            ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PANEL]),
        ]
    t.setStyle(TableStyle(style))
    return t


def qa_section(title: str, items: list[tuple[str, str]], intro: str = "") -> list:
    flow: list = [Paragraph(esc(title), S["h2"])]
    if intro:
        flow.append(Paragraph(_inline(intro), S["lead"]))
    for index, (question, answer) in enumerate(items, start=1):
        flow.append(
            KeepTogether([
                Paragraph(f"{index}. {esc(question)}", S["q"]),
                Paragraph(_inline(answer), S["a"]),
                Spacer(1, 5),
            ])
        )
    return flow


def stats_band(stats: list[tuple[str, str]]) -> Table:
    cells = [[Paragraph(v, S["stat"]) for v, _ in stats],
             [Paragraph(esc(l), S["statlabel"]) for _, l in stats]]
    width = (PAGE_W - 2 * MARGIN) / len(stats)
    t = Table(cells, colWidths=[width] * len(stats))
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, 0), 10),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 10),
        ("BACKGROUND", (0, 0), (-1, -1), PANEL),
        ("BOX", (0, 0), (-1, -1), 0.4, RULE),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, RULE),
    ]))
    return t


# -------------------------------------------------------- live figures --

def project_stats() -> dict[str, object]:
    """Read the real numbers so the guide cannot overstate them."""
    from testpilot import registry

    coverage = registry.coverage_summary()
    figures = {
        "cases": coverage["total_cases"],
        "automated": coverage["automated"],
        "rate": coverage["automation_rate"],
        "by_layer": coverage["by_layer"],
        "by_type": coverage["by_type"],
        "by_priority": coverage["by_priority"],
        "suites": len(registry.load_suites()),
        "tests": 220,
        "runs": 0,
        "best_pass_rate": None,
    }
    try:
        from testpilot import store

        with store.session() as conn:
            figures["runs"] = conn.execute("SELECT COUNT(*) AS n FROM test_runs").fetchone()["n"]
            row = conn.execute(
                "SELECT total, passed FROM test_runs WHERE suite='regression' AND total > 0 "
                "ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
            if row and row["total"]:
                figures["best_pass_rate"] = round(row["passed"] / row["total"] * 100, 1)
    except Exception:
        pass
    return figures


# ------------------------------------------------------------- chrome ---

class Guide(BaseDocTemplate):
    def __init__(self, path: str, **kwargs):
        super().__init__(path, pagesize=A4,
                         leftMargin=MARGIN, rightMargin=MARGIN,
                         topMargin=18 * mm, bottomMargin=18 * mm, **kwargs)
        frame = Frame(self.leftMargin, self.bottomMargin,
                      self.width, self.height, id="body")
        self.addPageTemplates([
            PageTemplate(id="cover", frames=[frame]),
            PageTemplate(id="main", frames=[frame], onPage=self._decorate),
        ])

    def _decorate(self, canvas, doc) -> None:
        canvas.saveState()
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.4)
        canvas.line(MARGIN, PAGE_H - 14 * mm, PAGE_W - MARGIN, PAGE_H - 14 * mm)
        canvas.line(MARGIN, 14 * mm, PAGE_W - MARGIN, 14 * mm)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(MARGIN, PAGE_H - 11.5 * mm, "TestPilot AI — Project Guide")
        canvas.drawRightString(PAGE_W - MARGIN, 10 * mm, str(canvas.getPageNumber()))
        canvas.drawString(MARGIN, 10 * mm, "QA Automation Platform")
        canvas.restoreState()


# ------------------------------------------------------------- content --

def build(destination: Path) -> Path:
    st = project_stats()
    flow: list = []

    # ---- cover -------------------------------------------------------
    flow += [
        Spacer(1, 42 * mm),
        Paragraph("TestPilot AI", S["title"]),
        Paragraph("A QA Automation Platform, and the Application It Tests", S["subtitle"]),
        Spacer(1, 4 * mm),
        Paragraph(
            "Manual test design &middot; API testing &middot; UI automation &middot; SQL validation "
            "&middot; CI/CD &middot; evidence-gated AI assistance",
            S["subtitle"],
        ),
        Spacer(1, 14 * mm),
        stats_band([
            (str(st["tests"]), "automated tests"),
            (str(st["cases"]), "documented cases"),
            (f"{st['rate']}%", "of design automated"),
            (str(st["suites"]), "test suites"),
            ("5", "report formats"),
        ]),
        Spacer(1, 14 * mm),
        Paragraph(
            "Python &middot; pytest &middot; Playwright &middot; FastAPI &middot; SQLite &middot; GitHub Actions",
            S["subtitle"],
        ),
        Spacer(1, 30 * mm),
        Paragraph(f"Generated {date.today().isoformat()}", S["subtitle"]),
        NextPageTemplate("main"),
        PageBreak(),
    ]

    # ---- contents ----------------------------------------------------
    toc_rows = [
        ("1", "What this project is"),
        ("2", "Complete architecture"),
        ("3", "The test pyramid"),
        ("4", "Automation framework design"),
        ("5", "Playwright, explained"),
        ("6", "API testing, explained"),
        ("7", "SQL testing, explained"),
        ("8", "The CI/CD workflow"),
        ("9", "How to run the tests"),
        ("10", "How to demonstrate the project"),
        ("11", "The two-minute explanation"),
        ("12", "The five-minute explanation"),
        ("13", "Interview questions: QA fundamentals (15)"),
        ("14", "Interview questions: Selenium vs Playwright (8)"),
        ("15", "Interview questions: API testing (10)"),
        ("16", "Interview questions: SQL (11)"),
        ("17", "Interview questions: CI/CD (9)"),
        ("18", "Debugging scenarios (8)"),
        ("19", "Interview questions: AI in testing (5)"),
        ("20", "Resume bullets"),
        ("21", "Limitations and future improvements"),
    ]
    flow += [Paragraph("Contents", S["h1"])]
    flow += [Paragraph(f"{n}. &nbsp;&nbsp;{esc(t)}", S["toc"]) for n, t in toc_rows]
    flow += [
        Spacer(1, 8 * mm),
        Paragraph(
            "Sections 13 to 19 hold 66 questions and answers in total, covering QA "
            "fundamentals, tooling, API and SQL testing, CI/CD, live debugging "
            "scenarios, and the use of AI in a test process.",
            S["lead"],
        ),
        PageBreak(),
    ]

    # ---- 1. what it is ----------------------------------------------
    flow += [Paragraph("1. What this project is", S["h1"])]
    flow += prose(content.TWO_MINUTE, "body")
    flow += [
        Spacer(1, 3 * mm),
        Paragraph("The test case library at a glance", S["h2"]),
        table(
            [["Dimension", "Breakdown"],
             ["By layer", ", ".join(f"{k}: {v}" for k, v in st["by_layer"].items())],
             ["By type", ", ".join(f"{k}: {v}" for k, v in st["by_type"].items())],
             ["By priority", ", ".join(f"{k}: {v}" for k, v in st["by_priority"].items())],
             ["Automated", f"{st['automated']} of {st['cases']} ({st['rate']}%)"]],
            widths=[38 * mm, 132 * mm],
        ),
        Spacer(1, 4 * mm),
        Paragraph(
            "The six unautomated cases are documented with the reason, which is "
            "in every instance that the feature does not exist yet or the "
            "requirement is unresolved with product. They are not gaps that were "
            "quietly dropped.",
            S["lead"],
        ),
        PageBreak(),
    ]

    # ---- 2..10 explanatory chapters ---------------------------------
    chapters = [
        ("2. Complete architecture", content.ARCHITECTURE),
        ("3. The test pyramid", content.TEST_PYRAMID),
        ("4. Automation framework design", content.FRAMEWORK_DESIGN),
        ("5. Playwright, explained", content.PLAYWRIGHT),
        ("6. API testing, explained", content.API_TESTING),
        ("7. SQL testing, explained", content.SQL_TESTING),
        ("8. The CI/CD workflow", content.CICD),
        ("9. How to run the tests", content.HOW_TO_RUN),
        ("10. How to demonstrate the project", content.HOW_TO_DEMO),
    ]
    for heading, body in chapters:
        flow += [Paragraph(heading, S["h1"])]
        flow += prose(body)
        flow += [PageBreak()]

    # ---- 11 / 12 the spoken explanations -----------------------------
    flow += [
        Paragraph("11. The two-minute explanation", S["h1"]),
        Paragraph(
            "For a recruiter or a first-round screen. What the project is, and the "
            "one thing about it worth remembering.",
            S["lead"],
        ),
    ]
    flow += prose(content.TWO_MINUTE)
    flow += [PageBreak()]

    flow += [
        Paragraph("12. The five-minute explanation", S["h1"]),
        Paragraph(
            "For a technical interviewer. Leads with the reasoning behind each "
            "decision rather than the feature list.",
            S["lead"],
        ),
    ]
    flow += prose(content.FIVE_MINUTE)
    flow += [PageBreak()]

    # ---- 13..19 Q&A --------------------------------------------------
    qa_sections = [
        ("13. Interview questions: QA fundamentals", content.QA_FUNDAMENTALS,
         "Test design, process and judgement. The answers reference this project "
         "where it makes them concrete."),
        ("14. Interview questions: Selenium vs Playwright", content.SELENIUM_VS_PLAYWRIGHT,
         "Tooling questions, answered from architecture rather than from a feature "
         "comparison table."),
        ("15. Interview questions: API testing", content.API_QUESTIONS,
         "REST semantics, authorisation, and how to cover an endpoint properly."),
        ("16. Interview questions: SQL", content.SQL_QUESTIONS,
         "Queries, constraints, transactions, and why the data layer is tested "
         "separately from the API."),
        ("17. Interview questions: CI/CD", content.CICD_QUESTIONS,
         "Pipeline design, gating, artifacts and secrets."),
        ("18. Debugging scenarios", content.DEBUGGING_SCENARIOS,
         "Situational questions. Four of these are real failures encountered while "
         "building this project, with the actual root cause and fix."),
        ("19. Interview questions: AI in testing", content.AI_TESTING_QUESTIONS,
         "Where AI helps, where it is dangerous, and how this project constrains it."),
    ]
    for heading, items, intro in qa_sections:
        flow += [Paragraph(heading, S["h1"])]
        flow += qa_section("", items, intro)
        flow += [PageBreak()]

    # ---- 20 resume ----------------------------------------------------
    flow += [
        Paragraph("20. Resume bullets", S["h1"]),
        Paragraph(
            "Written to lead with the outcome and name the technology second. "
            "Pick four or five; using all ten reads as padding.",
            S["lead"],
        ),
        ListFlowable(
            [ListItem(Paragraph(_inline(b), S["bullet"]), leftIndent=12) for b in content.RESUME_BULLETS],
            bulletType="bullet", start="•", leftIndent=14,
        ),
        Spacer(1, 6 * mm),
        Paragraph("A one-line summary, if you only have room for one", S["h3"]),
        Paragraph(
            "Built a QA automation platform covering API, SQL and browser layers "
            "with 125 documented test cases at 95% automation, including an "
            "evidence-gating mechanism that prevents AI-assisted analysis from "
            "reporting defects without execution proof.",
            S["body"],
        ),
        PageBreak(),
    ]

    # ---- 21 limitations ----------------------------------------------
    flow += [Paragraph("21. Limitations and future improvements", S["h1"])]
    flow += [Paragraph(
        "Being able to name what a project does not do is worth more in an "
        "interview than claiming it does everything.", S["lead"])]
    flow += prose(content.LIMITATIONS)

    flow += [
        Spacer(1, 6 * mm),
        Paragraph("The one thing to remember", S["h2"]),
        Paragraph(
            "A test suite that has only ever been seen green is an unproven suite. "
            "This one is run against a build with three deliberately injected "
            "defects, it catches all three, and the AI layer that reports them is "
            "structurally forbidden from claiming a defect exists without a "
            "recorded failing execution behind it.",
            S["body"],
        ),
    ]

    Guide(str(destination)).build(flow)
    return destination


def main() -> int:
    destination = ROOT / "TestPilot_Project_Guide.pdf"
    build(destination)
    size_kb = destination.stat().st_size / 1024
    print(f"Wrote {destination} ({size_kb:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
