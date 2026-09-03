"""Model access for the AI-assisted features.

Two providers implement the same interface:

  AnthropicProvider  calls the Claude Messages API when ANTHROPIC_API_KEY
                     is present.
  HeuristicProvider  a deterministic, rule-based fallback that needs no
                     network and no key.

The fallback is not a stub. CI must be able to run every AI feature
offline and get a stable, reviewable answer, so the heuristics are real
analysis logic and the tests assert on them. When a key *is* present the
model output is used, but it is passed through the same evidence gate and
the same schema validation, so a hallucinated field cannot reach a report.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Protocol

DEFAULT_MODEL = os.getenv("TESTPILOT_MODEL", "claude-sonnet-5")
MAX_TOKENS = 4096


@dataclass
class Completion:
    text: str
    provider: str
    model: str

    def json(self) -> Any:
        """Parse a JSON body out of the response, tolerating code fences."""
        text = self.text.strip()
        fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
        if fenced:
            text = fenced.group(1).strip()
        start = min((i for i in (text.find("{"), text.find("[")) if i != -1), default=-1)
        if start > 0:
            text = text[start:]
        return json.loads(text)


class Provider(Protocol):
    name: str

    def complete(self, system: str, prompt: str, max_tokens: int = MAX_TOKENS) -> Completion: ...


class AnthropicProvider:
    """Live model access via the Claude Messages API."""

    name = "anthropic"

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL) -> None:
        self.api_key = api_key
        self.model = model

    def complete(self, system: str, prompt: str, max_tokens: int = MAX_TOKENS) -> Completion:
        import httpx

        response = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=90,
        )
        response.raise_for_status()
        body = response.json()
        text = "".join(block.get("text", "") for block in body.get("content", []))
        return Completion(text=text, provider=self.name, model=self.model)


class HeuristicProvider:
    """Deterministic offline analysis.

    `complete` is never used for the heuristic path; each AI feature
    checks `provider.is_heuristic` and calls its own rule-based routine
    instead. Keeping the class here means callers only ever resolve one
    provider object.
    """

    name = "heuristic"
    model = "rules-v1"

    def complete(self, system: str, prompt: str, max_tokens: int = MAX_TOKENS) -> Completion:
        raise NotImplementedError(
            "The heuristic provider does not generate free text; callers use its rule-based routines."
        )


def is_heuristic(provider: Provider) -> bool:
    return getattr(provider, "name", "") == "heuristic"


def get_provider(force_heuristic: bool | None = None) -> Provider:
    """Resolve the provider for this process.

    `TESTPILOT_AI=off` forces the offline path, which is what CI uses so
    that a missing key never turns into a red build.
    """
    if force_heuristic:
        return HeuristicProvider()
    if os.getenv("TESTPILOT_AI", "").strip().lower() in {"off", "0", "false", "heuristic"}:
        return HeuristicProvider()

    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return HeuristicProvider()
    try:
        import httpx  # noqa: F401
    except ImportError:
        return HeuristicProvider()
    return AnthropicProvider(api_key)


def describe_provider(provider: Provider) -> dict[str, str]:
    return {
        "provider": getattr(provider, "name", "unknown"),
        "model": getattr(provider, "model", "n/a"),
        "mode": "offline rule-based" if is_heuristic(provider) else "live model",
    }


# The shared guardrail. Every prompt in this package starts with it.
GUARDRAIL = """You are a QA analysis assistant embedded in a test automation platform.

Hard rules you must never break:
1. You must NOT claim that a product defect exists. You may only describe
   what the supplied execution evidence shows. If the evidence is absent,
   ambiguous, or the test did not actually fail, say so plainly.
2. Never invent a test result, a status code, a stack frame, a screenshot
   path, a log line or a timestamp. Quote only what appears in the input.
3. Distinguish clearly between (a) what the evidence shows, (b) what you
   infer from it, and (c) what a human still needs to check.
4. If an observed failure could plausibly be caused by the test harness,
   the environment or test data rather than the product, say that
   explicitly and do not attribute it to the product.
5. Output valid JSON matching the requested schema and nothing else."""
