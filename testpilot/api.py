"""TestPilot's own REST API.

The CLI is how a person drives the platform; this is how another system
does -- a CI job posting results, a dashboard reading trends, a chat bot
asking "what broke on main last night".

Every AI endpoint here goes through the same evidence gate as the CLI. A
caller cannot obtain a bug report from this API that they could not
obtain from the command line, and no endpoint accepts a free-text
"describe this failure" prompt: analysis is always anchored to a stored
result id.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, status
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from . import analytics, defects, registry, runner, store
from .ai import bug_report as bug_report_module
from .ai import edge_cases as edge_cases_module
from .ai import evidence as evidence_module
from .ai import failure_analysis, generator
from .ai.provider import describe_provider, get_provider
from .config import ensure_dirs, get_environment
from .reporting import exporters

app = FastAPI(
    title="TestPilot API",
    version="1.0.0",
    description=__doc__,
)


# ------------------------------------------------------------ models ---

class RunRequest(BaseModel):
    suite: str = Field(..., examples=["smoke"])
    environment: Optional[str] = None
    trigger: str = "api"
    parallel: Optional[int] = Field(default=None, ge=1, le=16)


class TransitionRequest(BaseModel):
    status: str
    actor: str = "qa"
    note: Optional[str] = None


class FileDefectRequest(BaseModel):
    result_id: int
    allow_non_product: bool = False
    reporter: str = "testpilot-api"


class EdgeCaseRequest(BaseModel):
    subject: str
    declared_type: Optional[str] = None
    context: str = ""
    limit: int = Field(default=12, ge=1, le=40)


class GenerateRequest(BaseModel):
    spec: Optional[str] = Field(default=None, description="URL or path; defaults to the SUT's /openapi.json")
    include_paths: Optional[list[str]] = None


# ------------------------------------------------------------- meta ----

@app.get("/health", tags=["ops"])
def health() -> dict[str, Any]:
    ensure_dirs()
    with store.session() as conn:
        runs = conn.execute("SELECT COUNT(*) AS n FROM test_runs").fetchone()["n"]
    return {
        "status": "ok",
        "service": "TestPilot",
        "version": app.version,
        "runs_recorded": runs,
        "ai": describe_provider(get_provider()),
    }


@app.get("/api/environments/{name}", tags=["ops"])
def environment(name: str = "local") -> dict[str, Any]:
    try:
        return get_environment(name).redacted()
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# ------------------------------------------------------- test design ---

@app.get("/api/cases", tags=["design"])
def list_cases(
    layer: Optional[str] = None,
    type: Optional[str] = None,
    priority: Optional[str] = None,
    module: Optional[str] = None,
    suite: Optional[str] = None,
) -> dict[str, Any]:
    cases = registry.filter_cases(layer=layer, type_=type, priority=priority, module=module)
    if suite:
        cases = [c for c in cases if suite in c.suites]
    return {"total": len(cases), "cases": registry.as_dicts(cases)}


@app.get("/api/cases/{case_id}", tags=["design"])
def get_case(case_id: str) -> dict[str, Any]:
    case = next((c for c in registry.load_cases() if c.id == case_id), None)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"No test case {case_id}")
    return case.to_dict()


@app.get("/api/coverage", tags=["design"])
def coverage() -> dict[str, Any]:
    return registry.coverage_summary()


@app.get("/api/suites", tags=["design"])
def list_suites() -> dict[str, Any]:
    return {"suites": runner.list_suites()}


# ---------------------------------------------------------- execution --

@app.post("/api/runs", status_code=status.HTTP_202_ACCEPTED, tags=["execution"])
def start_run(request: RunRequest, background: BackgroundTasks) -> dict[str, Any]:
    """Kick off a suite. Returns immediately; poll /api/runs for the result.

    Suites take minutes, so this never blocks the caller's connection.
    """
    try:
        registry.get_suite(request.suite)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    background.add_task(
        runner.run_suite,
        request.suite,
        environment=request.environment,
        trigger=request.trigger,
        parallel=request.parallel,
        echo=False,
    )
    return {
        "accepted": True,
        "suite": request.suite,
        "environment": request.environment or "local",
        "poll": "/api/runs?suite=" + request.suite,
    }


@app.get("/api/runs", tags=["execution"])
def list_runs(suite: Optional[str] = None, limit: int = Query(default=25, ge=1, le=200)) -> dict[str, Any]:
    return {"runs": analytics.history(suite=suite, limit=limit)}


@app.get("/api/runs/latest", tags=["execution"])
def latest_run(suite: Optional[str] = None) -> dict[str, Any]:
    run = store.latest_run(suite=suite)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No runs have been recorded")
    return analytics.run_summary(run["id"])


@app.get("/api/runs/{run_id}", tags=["execution"])
def get_run(run_id: str) -> dict[str, Any]:
    try:
        return analytics.run_summary(run_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@app.get("/api/runs/{run_id}/results", tags=["execution"])
def run_results(run_id: str, outcome: Optional[str] = None) -> dict[str, Any]:
    if store.get_run(run_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"No run {run_id}")
    return {"results": store.results_for_run(run_id, outcome=outcome)}


@app.get("/api/runs/{run_id}/artifacts", tags=["execution"])
def run_artifacts(run_id: str) -> dict[str, Any]:
    if store.get_run(run_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"No run {run_id}")
    return runner.artifacts_for(run_id)


@app.get("/api/compare", tags=["execution"])
def compare(baseline: str, candidate: str) -> dict[str, Any]:
    """New failures, fixes and pre-existing breakage between two runs."""
    for run_id in (baseline, candidate):
        if store.get_run(run_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"No run {run_id}")
    return analytics.compare_runs(baseline, candidate)


# ---------------------------------------------------------- analytics --

@app.get("/api/analytics/overview", tags=["analytics"])
def overview() -> dict[str, Any]:
    return {
        "totals": analytics.overall_stats(),
        "flaky": analytics.flaky_tests(),
        "hotspots": analytics.failure_hotspots(),
        "coverage": registry.coverage_summary(),
        "defects": defects.metrics(),
    }


@app.get("/api/analytics/flaky", tags=["analytics"])
def flaky(min_runs: int = Query(default=3, ge=2)) -> dict[str, Any]:
    return {"flaky": analytics.flaky_tests(min_runs=min_runs)}


@app.get("/api/analytics/cases", tags=["analytics"])
def case_status() -> dict[str, Any]:
    return {"cases": analytics.case_execution_status()}


# ----------------------------------------------------------- reports ---

@app.get("/api/runs/{run_id}/report", tags=["reports"])
def report(
    run_id: str,
    format: Literal["html", "json", "junit", "csv", "markdown"] = "html",
) -> FileResponse:
    if store.get_run(run_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"No run {run_id}")
    path = exporters.FORMATS[format](run_id)
    media = {
        "html": "text/html",
        "json": "application/json",
        "junit": "application/xml",
        "csv": "text/csv",
        "markdown": "text/markdown",
    }[format]
    return FileResponse(path, media_type=media, filename=path.name)


# --------------------------------------------------------- AI: design --

@app.post("/api/ai/generate-cases", tags=["ai"])
def generate_cases(request: GenerateRequest) -> dict[str, Any]:
    """Draft test cases from an OpenAPI specification.

    Output is always marked draft; nothing is written to the repository.
    """
    source = request.spec or f"{get_environment().api_url}/openapi.json"
    try:
        return generator.generate_from_spec(source, include_paths=request.include_paths, provider=get_provider())
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"Could not read the specification: {exc}") from exc


@app.post("/api/ai/edge-cases", tags=["ai"])
def suggest_edge_cases(request: EdgeCaseRequest) -> dict[str, Any]:
    """Suggest scenarios worth covering. Carries no claim about defects."""
    return edge_cases_module.suggest(
        request.subject,
        declared_type=request.declared_type,
        context=request.context,
        limit=request.limit,
        provider=get_provider(),
    )


# ------------------------------------------------------ AI: analysis ---

@app.get("/api/results/{result_id}/evidence", tags=["ai"])
def result_evidence(result_id: int) -> dict[str, Any]:
    """The raw admissibility verdict for one result.

    Exposed deliberately: a caller can see exactly why the platform will
    or will not let a defect be claimed from this execution.
    """
    return evidence_module.collect(result_id).to_dict()


@app.get("/api/results/{result_id}/analysis", tags=["ai"])
def result_analysis(result_id: int) -> dict[str, Any]:
    bundle = evidence_module.collect(result_id)
    provider = get_provider()
    return {
        "evidence": bundle.to_dict(),
        "summary": failure_analysis.summarize_failure(bundle, provider),
        "classification": failure_analysis.classify_failure(bundle, provider),
    }


@app.get("/api/runs/{run_id}/analysis", tags=["ai"])
def run_analysis(run_id: str) -> dict[str, Any]:
    if store.get_run(run_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"No run {run_id}")
    bundles = evidence_module.collect_for_run(run_id)
    if not bundles:
        return {"run_id": run_id, "failures_analysed": 0, "analyses": [],
                "note": "This run recorded no failures, so there is nothing to triage."}
    return {"run_id": run_id, **failure_analysis.summarize_run(bundles, get_provider())}


@app.get("/api/results/{result_id}/bug-report", tags=["ai"])
def draft_bug_report(result_id: int, allow_non_product: bool = False) -> dict[str, Any]:
    """Draft a bug report, or refuse and say why.

    A refusal is a 200 carrying `drafted: false` and its reasons rather
    than an error: "there is not enough evidence" is a real, useful
    answer to this question, not a failure of the request.
    """
    bundle = evidence_module.collect(result_id)
    return bug_report_module.draft(bundle, provider=get_provider(), allow_non_product=allow_non_product)


# --------------------------------------------------------- defects ----

@app.post("/api/defects", tags=["defects"])
def file_defect(request: FileDefectRequest) -> dict[str, Any]:
    outcome = defects.file_defect(
        request.result_id,
        provider=get_provider(),
        allow_non_product=request.allow_non_product,
        reporter=request.reporter,
    )
    if not outcome["filed"]:
        # 422: the request was well-formed, but the evidence does not
        # support the action it asked for.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=outcome["reason"])
    return outcome


@app.get("/api/defects", tags=["defects"])
def list_defects(status_filter: Optional[str] = Query(default=None, alias="status")) -> dict[str, Any]:
    return {"defects": defects.list_defects(status=status_filter), "metrics": defects.metrics()}


@app.get("/api/defects/{defect_id}", tags=["defects"])
def get_defect(defect_id: str) -> dict[str, Any]:
    defect = defects.get(defect_id)
    if defect is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"No defect {defect_id}")
    return defect


@app.get("/api/defects/{defect_id}/markdown", response_class=PlainTextResponse, tags=["defects"])
def defect_markdown(defect_id: str) -> str:
    defect = defects.get(defect_id)
    if defect is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"No defect {defect_id}")
    return defect["body_markdown"]


@app.post("/api/defects/{defect_id}/transition", tags=["defects"])
def transition_defect(defect_id: str, request: TransitionRequest) -> dict[str, Any]:
    try:
        return defects.transition(defect_id, request.status, actor=request.actor, note=request.note)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except defects.LifecycleError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@app.get("/api/defects/{defect_id}/evidence", tags=["defects"])
def defect_evidence(defect_id: str) -> dict[str, Any]:
    bundle = defects.evidence_for(defect_id)
    if bundle is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"No evidence recorded for {defect_id}")
    return bundle.to_dict()


def run(host: str = "127.0.0.1", port: int = 8090) -> None:  # pragma: no cover
    import uvicorn

    uvicorn.run("testpilot.api:app", host=host, port=port)


if __name__ == "__main__":  # pragma: no cover
    run()
