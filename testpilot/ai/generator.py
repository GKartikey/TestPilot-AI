"""Generate draft test cases from an OpenAPI specification.

The generator walks the spec and proposes cases across four axes that a
human test designer would cover anyway -- happy path, negative, boundary
and authorisation -- then hands them back as registry-shaped dicts ready
to be reviewed and committed to `testcases/`.

Output is always marked `status: draft`. Generated cases are a starting
point for a test designer, not a substitute for one, and nothing is
written to the repository unless a human passes `--write`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from .provider import GUARDRAIL, Provider, get_provider, is_heuristic

SYSTEM = GUARDRAIL + """

Your present task is TEST DESIGN, not defect analysis. Given an OpenAPI
operation, propose test cases. Ground every case in the operation's real
parameters, request schema and declared responses. Do not invent
endpoints, fields or status codes that are absent from the spec."""

_SCHEMA_HINT = """Return JSON: {"cases": [{"title": str, "type": one of
["functional","negative","boundary","security"], "priority": one of
["P1","P2","P3","P4"], "objective": str, "preconditions": [str],
"steps": [str], "expected": str, "test_data": object}]}"""


def load_spec(source: str | Path | dict[str, Any]) -> dict[str, Any]:
    """Accept a dict, a local .json/.yaml file, or a live /openapi.json URL."""
    if isinstance(source, dict):
        return source
    text = str(source)
    if text.startswith("http://") or text.startswith("https://"):
        import httpx

        response = httpx.get(text, timeout=30)
        response.raise_for_status()
        return response.json()
    path = Path(text)
    body = path.read_text(encoding="utf-8")
    return json.loads(body) if path.suffix == ".json" else yaml.safe_load(body)


def iter_operations(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten the spec into one record per (path, method)."""
    operations = []
    for path, item in (spec.get("paths") or {}).items():
        shared = item.get("parameters", [])
        for method, operation in item.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            operations.append(
                {
                    "path": path,
                    "method": method.upper(),
                    "operation_id": operation.get("operationId", f"{method}_{path}"),
                    "summary": operation.get("summary", ""),
                    "tags": operation.get("tags", []),
                    "parameters": [*shared, *operation.get("parameters", [])],
                    "request_body": operation.get("requestBody"),
                    "responses": sorted((operation.get("responses") or {}).keys()),
                    "secured": bool(operation.get("security")) or _looks_secured(path),
                }
            )
    return operations


def _looks_secured(path: str) -> bool:
    return any(segment in path for segment in ("/cart", "/orders", "/auth/me"))


def _slug(text: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "-", text.upper()).strip("-")


def _resolve_ref(spec: dict[str, Any], ref: str) -> dict[str, Any]:
    node: Any = spec
    for part in ref.lstrip("#/").split("/"):
        node = node.get(part, {}) if isinstance(node, dict) else {}
    return node if isinstance(node, dict) else {}


def request_fields(spec: dict[str, Any], operation: dict[str, Any]) -> dict[str, Any]:
    body = operation.get("request_body") or {}
    content = (body.get("content") or {}).get("application/json") or {}
    schema = content.get("schema") or {}
    if "$ref" in schema:
        schema = _resolve_ref(spec, schema["$ref"])
    return schema.get("properties", {}) or {}


# ----------------------------------------------------- heuristic path ---

def _heuristic_cases(spec: dict[str, Any], operation: dict[str, Any]) -> list[dict[str, Any]]:
    method, path = operation["method"], operation["path"]
    fields = request_fields(spec, operation)
    params = operation["parameters"]
    cases: list[dict[str, Any]] = []

    ok_status = next((s for s in operation["responses"] if s.startswith("2")), "200")
    cases.append(
        {
            "title": f"{method} {path} returns {ok_status} for a valid request",
            "type": "functional",
            "priority": "P1",
            "objective": operation["summary"] or f"Confirm the happy path of {method} {path}.",
            "preconditions": (["An authenticated session exists"] if operation["secured"] else ["The service is reachable"]),
            "steps": [
                f"Issue {method} {path} with a valid, complete payload",
                "Inspect the response status and body",
            ],
            "expected": f"The response status is {ok_status} and the body matches the documented schema.",
            "test_data": {"payload": "valid"},
        }
    )

    if fields:
        first = next(iter(fields))
        cases.append(
            {
                "title": f"{method} {path} rejects a request with {first} missing",
                "type": "negative",
                "priority": "P2",
                "objective": f"Confirm required-field validation on {first}.",
                "preconditions": ["The service is reachable"],
                "steps": [f"Issue {method} {path} omitting the {first} field", "Inspect the response"],
                "expected": "The response status is 422 and the body names the offending field.",
                "test_data": {"omit": first},
            }
        )
        cases.append(
            {
                "title": f"{method} {path} rejects a malformed {first} value",
                "type": "negative",
                "priority": "P3",
                "objective": f"Confirm type validation on {first}.",
                "preconditions": ["The service is reachable"],
                "steps": [f"Issue {method} {path} with {first} set to a value of the wrong type", "Inspect the response"],
                "expected": "The response status is 422 and no record is created.",
                "test_data": {first: "<wrong type>"},
            }
        )

    for param in params:
        schema = param.get("schema") or {}
        low, high = schema.get("minimum"), schema.get("maximum")
        if low is None and high is None:
            continue
        name = param.get("name")
        cases.append(
            {
                "title": f"{method} {path} enforces the declared range on {name}",
                "type": "boundary",
                "priority": "P2",
                "objective": f"Exercise the documented bounds of {name} ({low}..{high}).",
                "preconditions": ["The service is reachable"],
                "steps": [
                    f"Call {method} {path} with {name} at the lower bound"
                    + (f" ({low})" if low is not None else ""),
                    f"Call again with {name} at the upper bound" + (f" ({high})" if high is not None else ""),
                    f"Call again with {name} one step outside each bound",
                ],
                "expected": "In-range values are accepted; out-of-range values return 422 without side effects.",
                "test_data": {"minimum": low, "maximum": high},
            }
        )

    if operation["secured"]:
        cases.append(
            {
                "title": f"{method} {path} requires authentication",
                "type": "security",
                "priority": "P1",
                "objective": "Confirm the endpoint is not reachable anonymously.",
                "preconditions": ["No Authorization header is sent"],
                "steps": [f"Issue {method} {path} with no credentials", "Repeat with a malformed bearer token"],
                "expected": "Both calls return 401 and no protected data appears in the body.",
                "test_data": {"authorization": None},
            }
        )

    if "{" in path:
        cases.append(
            {
                "title": f"{method} {path} returns 404 for an unknown identifier",
                "type": "negative",
                "priority": "P2",
                "objective": "Confirm unknown resources are reported, not fabricated.",
                "preconditions": ["The service is reachable"],
                "steps": [f"Issue {method} {path} substituting an id that does not exist"],
                "expected": "The response status is 404 with a descriptive detail message.",
                "test_data": {"id": 999_999},
            }
        )
    return cases


# ------------------------------------------------------------- entry ---

def generate_for_operation(
    spec: dict[str, Any],
    operation: dict[str, Any],
    provider: Provider | None = None,
) -> list[dict[str, Any]]:
    provider = provider or get_provider()
    if is_heuristic(provider):
        return _heuristic_cases(spec, operation)

    prompt = (
        f"OpenAPI operation:\n{json.dumps(operation, indent=2)[:6000]}\n\n"
        f"Request body properties:\n{json.dumps(request_fields(spec, operation), indent=2)[:3000]}\n\n"
        f"Propose 4 to 7 test cases covering happy path, negative, boundary and authorisation.\n{_SCHEMA_HINT}"
    )
    try:
        parsed = provider.complete(SYSTEM, prompt).json()
        cases = parsed.get("cases", []) if isinstance(parsed, dict) else []
        return [c for c in cases if _well_formed(c)] or _heuristic_cases(spec, operation)
    except Exception:
        # A model failure must never block test design; fall back.
        return _heuristic_cases(spec, operation)


def _well_formed(case: dict[str, Any]) -> bool:
    required = {"title", "type", "priority", "steps", "expected"}
    return (
        isinstance(case, dict)
        and required.issubset(case)
        and case["type"] in {"functional", "negative", "boundary", "security"}
        and case["priority"] in {"P1", "P2", "P3", "P4"}
        and isinstance(case["steps"], list)
        and bool(case["steps"])
    )


def generate_from_spec(
    source: str | Path | dict[str, Any],
    include_paths: list[str] | None = None,
    provider: Provider | None = None,
) -> dict[str, Any]:
    """Produce a full draft case library for a specification."""
    spec = load_spec(source)
    provider = provider or get_provider()
    operations = iter_operations(spec)
    if include_paths:
        operations = [o for o in operations if any(p in o["path"] for p in include_paths)]

    generated: list[dict[str, Any]] = []
    counters: dict[str, int] = {}
    for operation in operations:
        module = (operation["tags"] or ["general"])[0]
        for case in generate_for_operation(spec, operation, provider):
            counters[module] = counters.get(module, 0) + 1
            generated.append(
                {
                    "id": f"TC-GEN-{_slug(module)}-{counters[module]:03d}",
                    "title": case["title"],
                    "module": module,
                    "layer": "api",
                    "type": case["type"],
                    "priority": case["priority"],
                    "objective": case.get("objective", ""),
                    "preconditions": case.get("preconditions", []),
                    "steps": case["steps"],
                    "expected": case["expected"],
                    "test_data": case.get("test_data", {}),
                    "suites": ["generated"],
                    "automation": None,
                    "requirement": None,
                    "source_operation": f"{operation['method']} {operation['path']}",
                    "status": "draft",
                }
            )

    return {
        "spec_title": (spec.get("info") or {}).get("title", "unknown"),
        "spec_version": (spec.get("info") or {}).get("version", "unknown"),
        "provider": getattr(provider, "name", "unknown"),
        "operations_analysed": len(operations),
        "cases": generated,
        "note": "All generated cases are drafts. A test designer must review them before they enter the suite.",
    }


def write_cases(result: dict[str, Any], destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": {
            "generated_from": result["spec_title"],
            "spec_version": result["spec_version"],
            "provider": result["provider"],
            "status": "draft - pending human review",
        },
        "cases": [{k: v for k, v in case.items() if k != "status"} for case in result["cases"]],
    }
    with destination.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False, allow_unicode=True, width=100)
    return destination
