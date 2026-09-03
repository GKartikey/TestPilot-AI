"""Test case management.

Test cases live in `testcases/*.yaml` as human-authored, reviewable
documents: preconditions, steps, expected result, priority, requirement
trace. A case optionally names the automated test that covers it via the
`automation` field, which is what lets TestPilot report *coverage of the
design*, not just "how many asserts ran".

This is the bridge between manual test design and the automation suite,
and it is deliberately the source of truth for both.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import yaml

from .config import TESTCASES_DIR

VALID_LAYERS = {"api", "ui", "db", "unit", "contract"}
VALID_TYPES = {"functional", "negative", "boundary", "security", "smoke", "regression", "integration", "data"}
VALID_PRIORITIES = {"P1", "P2", "P3", "P4"}


@dataclass
class TestCase:
    id: str
    title: str
    module: str
    layer: str
    type: str
    priority: str
    objective: str = ""
    preconditions: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    expected: str = ""
    test_data: dict[str, Any] = field(default_factory=dict)
    suites: list[str] = field(default_factory=list)
    automation: str | None = None
    requirement: str | None = None

    @property
    def is_automated(self) -> bool:
        return bool(self.automation)

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class Suite:
    name: str
    description: str
    markers: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    deselect_markers: list[str] = field(default_factory=list)
    max_duration_seconds: int | None = None
    fail_fast: bool = False

    def pytest_args(self) -> list[str]:
        """Translate the suite definition into a pytest invocation."""
        args: list[str] = list(self.paths)
        expression_parts = [f"({' or '.join(self.markers)})"] if self.markers else []
        expression_parts += [f"not {m}" for m in self.deselect_markers]
        if expression_parts:
            args += ["-m", " and ".join(expression_parts)]
        if self.fail_fast:
            args.append("-x")
        return args


class RegistryError(ValueError):
    """Raised when the test case library does not validate."""


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


@lru_cache(maxsize=None)
def load_cases(directory: Path | str | None = None) -> tuple[TestCase, ...]:
    root = Path(directory) if directory else TESTCASES_DIR
    cases: list[TestCase] = []
    seen: dict[str, Path] = {}

    for path in sorted(root.glob("*.yaml")):
        if path.name == "suites.yaml":
            continue
        payload = _load_yaml(path)
        for raw in payload.get("cases", []):
            try:
                case = TestCase(**raw)
            except TypeError as exc:
                raise RegistryError(f"{path.name}: malformed case {raw.get('id', '?')}: {exc}") from exc
            _validate(case, path)
            if case.id in seen:
                raise RegistryError(f"Duplicate case id {case.id} in {path.name} and {seen[case.id].name}")
            seen[case.id] = path
            cases.append(case)
    return tuple(cases)


def _validate(case: TestCase, path: Path) -> None:
    where = f"{path.name}:{case.id}"
    if case.layer not in VALID_LAYERS:
        raise RegistryError(f"{where}: layer {case.layer!r} must be one of {sorted(VALID_LAYERS)}")
    if case.type not in VALID_TYPES:
        raise RegistryError(f"{where}: type {case.type!r} must be one of {sorted(VALID_TYPES)}")
    if case.priority not in VALID_PRIORITIES:
        raise RegistryError(f"{where}: priority {case.priority!r} must be one of {sorted(VALID_PRIORITIES)}")
    if not case.expected:
        raise RegistryError(f"{where}: every case needs an expected result")
    if not case.steps:
        raise RegistryError(f"{where}: every case needs at least one step")


@lru_cache(maxsize=None)
def load_suites(directory: Path | str | None = None) -> dict[str, Suite]:
    root = Path(directory) if directory else TESTCASES_DIR
    payload = _load_yaml(root / "suites.yaml")
    suites: dict[str, Suite] = {}
    for name, raw in (payload.get("suites") or {}).items():
        suites[name] = Suite(name=name, **(raw or {}))
    return suites


def get_suite(name: str, directory: Path | str | None = None) -> Suite:
    suites = load_suites(directory)
    if name not in suites:
        raise KeyError(f"Unknown suite {name!r}. Known suites: {', '.join(sorted(suites))}")
    return suites[name]


def cases_for_suite(name: str, directory: Path | str | None = None) -> list[TestCase]:
    """Cases that belong to a suite.

    Membership is declared two ways and both count. A case can name the
    suite explicitly in its `suites` list (that is how `smoke` and
    `regression` are curated), or it can belong implicitly because the
    suite is named after a layer or a type -- the `api`, `db`, `ui`,
    `boundary`, `negative` and `security` suites select by marker, and
    those markers mirror the case's own layer and type fields.
    """
    return [
        c
        for c in load_cases(directory)
        if name in c.suites or name == c.layer or name == c.type
    ]


def case_by_automation(nodeid: str, directory: Path | str | None = None) -> TestCase | None:
    """Map a pytest nodeid back to the manual case that specified it."""
    normalised = nodeid.replace("\\", "/").split("[")[0]
    for case in load_cases(directory):
        if not case.automation:
            continue
        target = case.automation.replace("\\", "/").split("[")[0]
        if normalised == target or normalised.endswith(target):
            return case
    return None


def coverage_summary(directory: Path | str | None = None) -> dict[str, Any]:
    cases = load_cases(directory)
    total = len(cases)
    automated = sum(1 for c in cases if c.is_automated)

    def bucket(key: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for case in cases:
            counts[getattr(case, key)] = counts.get(getattr(case, key), 0) + 1
        return dict(sorted(counts.items()))

    return {
        "total_cases": total,
        "automated": automated,
        "manual_only": total - automated,
        "automation_rate": round(automated / total * 100, 1) if total else 0.0,
        "by_layer": bucket("layer"),
        "by_type": bucket("type"),
        "by_priority": bucket("priority"),
        "by_module": bucket("module"),
        "by_suite": {
            suite: len(cases_for_suite(suite, directory)) for suite in sorted(load_suites(directory))
        },
    }


def filter_cases(
    layer: str | None = None,
    type_: str | None = None,
    priority: str | None = None,
    module: str | None = None,
    directory: Path | str | None = None,
) -> list[TestCase]:
    def keep(case: TestCase) -> bool:
        return (
            (layer is None or case.layer == layer)
            and (type_ is None or case.type == type_)
            and (priority is None or case.priority == priority)
            and (module is None or case.module == module)
        )

    return [c for c in load_cases(directory) if keep(c)]


def as_dicts(cases: Iterable[TestCase]) -> list[dict[str, Any]]:
    return [c.to_dict() for c in cases]


def reload() -> None:
    """Drop caches. Used after the AI generator writes new cases."""
    load_cases.cache_clear()
    load_suites.cache_clear()
