"""Suggest edge cases for an endpoint, a field or a business rule.

These are *suggestions for a human test designer*, not findings. Nothing
in this module inspects a running system, so nothing in it may imply that
a defect exists -- only that a scenario is worth covering.
"""
from __future__ import annotations

import json
from typing import Any

from .provider import GUARDRAIL, Provider, get_provider, is_heuristic

SYSTEM = GUARDRAIL + """

Your present task is EDGE CASE IDEATION. Propose scenarios that are worth
testing. You are not analysing a failure and you have no execution
evidence, so you must not state or imply that any of these scenarios
currently fails."""

_SCHEMA_HINT = """Return JSON: {"suggestions": [{"scenario": str,
"category": one of ["boundary","negative","security","concurrency","data-integrity","usability","performance"],
"why_it_matters": str, "risk": one of ["high","medium","low"]}]}"""


# Rule-based catalogue keyed by the shape of the thing under test. These
# are the checks an experienced tester reaches for by reflex.
_BY_TYPE: dict[str, list[tuple[str, str, str, str]]] = {
    "integer": [
        ("Value exactly at the minimum", "boundary", "Off-by-one errors cluster on the inclusive lower bound.", "high"),
        ("Value one below the minimum", "boundary", "Confirms the bound is rejected rather than clamped.", "high"),
        ("Value exactly at the maximum", "boundary", "The inclusive upper bound must be accepted.", "high"),
        ("Value one above the maximum", "boundary", "The most common validation gap.", "high"),
        ("Zero", "boundary", "Zero often means 'remove' or 'unlimited' by accident.", "medium"),
        ("Negative value", "negative", "Negative quantities can invert totals or credit an account.", "high"),
        ("Non-numeric string in a numeric field", "negative", "Type coercion can turn '5x' into 5.", "medium"),
        ("Very large integer beyond 32-bit range", "boundary", "Overflow and column-width failures.", "medium"),
    ],
    "string": [
        ("Empty string", "boundary", "Distinct from null and often mishandled.", "high"),
        ("Whitespace only", "negative", "Passes a naive truthiness check but is not a real value.", "medium"),
        ("Maximum declared length", "boundary", "Confirms the field stores its advertised size.", "high"),
        ("One character over the maximum", "boundary", "Must be rejected, not silently truncated.", "high"),
        ("Unicode, emoji and combining characters", "data-integrity", "Encoding loss corrupts stored data.", "medium"),
        ("Leading and trailing whitespace", "data-integrity", "Determines whether lookups match later.", "medium"),
        ("HTML and script markup", "security", "Confirms output is escaped and not executed.", "high"),
        ("SQL metacharacters such as a quote or -- comment", "security", "Confirms parameterised queries are used.", "high"),
    ],
    "email": [
        ("Address with no @ sign", "negative", "The base validation case.", "high"),
        ("Address with no top-level domain", "negative", "A common regex gap.", "medium"),
        ("Plus-addressing such as user+tag@example.com", "boundary", "Valid but often wrongly rejected.", "medium"),
        ("Mixed case address", "data-integrity", "Login must be case-insensitive on the domain part.", "high"),
        ("254-character address", "boundary", "The RFC maximum.", "low"),
        ("Address already registered", "negative", "Must return a conflict, not a second account.", "high"),
    ],
    "money": [
        ("Amount of zero", "boundary", "Free items must not break the payment path.", "high"),
        ("Fractional cent rounding", "data-integrity", "Rounding drift is a revenue defect.", "high"),
        ("Discount larger than the subtotal", "boundary", "Must clamp at zero, never go negative.", "high"),
        ("Amount at the free-shipping threshold exactly", "boundary", "The rule is inclusive; the code often is not.", "high"),
        ("Amount one cent below the threshold", "boundary", "The other half of the same bound.", "high"),
    ],
    "auth": [
        ("No Authorization header at all", "security", "The endpoint must not be anonymous.", "high"),
        ("Malformed header without the Bearer scheme", "security", "Parser must fail closed.", "high"),
        ("Expired token", "security", "Expiry must actually be verified.", "high"),
        ("Token signed with the wrong secret", "security", "Signature verification must not be skipped.", "high"),
        ("Valid token belonging to a different user", "security", "The classic broken-object-level-authorisation case.", "high"),
        ("Token for a deactivated account", "security", "Deactivation must take effect immediately.", "medium"),
    ],
    "collection": [
        ("Empty collection", "boundary", "Empty states are the most-skipped screen.", "high"),
        ("Single element", "boundary", "Reveals pluralisation and index assumptions.", "medium"),
        ("Page size of one", "boundary", "Exercises pagination arithmetic.", "medium"),
        ("Page beyond the last page", "boundary", "Must return an empty page, not an error.", "medium"),
        ("Concurrent modification during pagination", "concurrency", "Causes skipped or duplicated rows.", "medium"),
    ],
    "stock": [
        ("Requesting exactly the remaining stock", "boundary", "The inclusive bound of availability.", "high"),
        ("Requesting one more than remaining stock", "boundary", "The oversell case; must be rejected.", "high"),
        ("Two customers checking out the last unit at once", "concurrency", "Requires a real transactional guard.", "high"),
        ("Item goes out of stock between cart and checkout", "data-integrity", "Stock must be revalidated at checkout.", "high"),
    ],
}

_KEYWORDS = {
    "email": "email",
    "password": "auth",
    "token": "auth",
    "auth": "auth",
    "login": "auth",
    "price": "money",
    "total": "money",
    "amount": "money",
    "discount": "money",
    "coupon": "money",
    "cents": "money",
    "quantity": "integer",
    "qty": "integer",
    "stock": "stock",
    "inventory": "stock",
    "page": "collection",
    "list": "collection",
    "search": "collection",
    "name": "string",
    "description": "string",
    "sku": "string",
}


def _infer_kinds(subject: str, declared_type: str | None) -> list[str]:
    lowered = subject.lower()
    kinds = [kind for keyword, kind in _KEYWORDS.items() if keyword in lowered]
    if declared_type in _BY_TYPE:
        kinds.append(declared_type)
    if not kinds:
        kinds = ["string", "integer"]
    seen: list[str] = []
    for kind in kinds:
        if kind not in seen:
            seen.append(kind)
    return seen


def _heuristic(subject: str, declared_type: str | None, limit: int) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for kind in _infer_kinds(subject, declared_type):
        for scenario, category, why, risk in _BY_TYPE.get(kind, []):
            out.append(
                {
                    "scenario": f"{subject}: {scenario}",
                    "category": category,
                    "why_it_matters": why,
                    "risk": risk,
                    "source": f"catalogue:{kind}",
                }
            )
    order = {"high": 0, "medium": 1, "low": 2}
    out.sort(key=lambda s: order.get(s["risk"], 3))
    return out[:limit]


def suggest(
    subject: str,
    declared_type: str | None = None,
    context: str = "",
    limit: int = 12,
    provider: Provider | None = None,
) -> dict[str, Any]:
    """Suggest edge cases for a field, endpoint or rule."""
    provider = provider or get_provider()

    if is_heuristic(provider):
        suggestions = _heuristic(subject, declared_type, limit)
    else:
        prompt = (
            f"Subject under test: {subject}\n"
            f"Declared type: {declared_type or 'unspecified'}\n"
            f"Context: {context or 'none supplied'}\n\n"
            f"Propose up to {limit} edge cases worth covering.\n{_SCHEMA_HINT}"
        )
        try:
            parsed = provider.complete(SYSTEM, prompt).json()
            raw = parsed.get("suggestions", []) if isinstance(parsed, dict) else []
            suggestions = [
                {**s, "source": "model"}
                for s in raw
                if isinstance(s, dict) and s.get("scenario") and s.get("category")
            ][:limit]
            if not suggestions:
                suggestions = _heuristic(subject, declared_type, limit)
        except Exception:
            suggestions = _heuristic(subject, declared_type, limit)

    return {
        "subject": subject,
        "declared_type": declared_type,
        "provider": getattr(provider, "name", "unknown"),
        "suggestions": suggestions,
        "disclaimer": (
            "These are untested scenarios proposed for coverage. They are not findings "
            "and carry no implication that the product currently fails any of them."
        ),
    }


def suggest_for_case(case: dict[str, Any], provider: Provider | None = None, limit: int = 10) -> dict[str, Any]:
    """Expand an existing manual test case into adjacent edge cases."""
    subject = case.get("title") or case.get("id", "unnamed case")
    context = json.dumps({k: case.get(k) for k in ("objective", "steps", "expected", "test_data")}, default=str)
    return suggest(subject, declared_type=None, context=context[:2000], limit=limit, provider=provider)
