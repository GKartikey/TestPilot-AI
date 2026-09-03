"""Environment configuration for the TestPilot platform.

Environments are declared in `config/environments.yaml` and selected with
`TESTPILOT_ENV`. Anything secret (tokens, API keys) comes from the
process environment only and is never written to disk or to a report.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
ARTIFACTS = ROOT / "artifacts"
RESULTS_DB = ARTIFACTS / "testpilot.db"
REPORTS_DIR = ARTIFACTS / "reports"
SCREENSHOTS_DIR = ARTIFACTS / "screenshots"
TRACES_DIR = ARTIFACTS / "traces"
TESTCASES_DIR = ROOT / "testcases"

_SECRET_KEYS = {"password", "token", "api_key", "secret", "authorization"}


@dataclass
class Environment:
    """A deployment of the system under test that we can point tests at."""

    name: str
    base_url: str
    db_path: str
    admin_email: str
    admin_password: str
    user_email: str
    user_password: str
    headless: bool = True
    slow_mo_ms: int = 0
    default_timeout_ms: int = 10_000
    fault_profile: str = "none"
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def api_url(self) -> str:
        return self.base_url.rstrip("/")

    def redacted(self) -> dict[str, Any]:
        """A copy safe to embed in a report or hand to a model."""
        out: dict[str, Any] = {}
        for key, value in self.__dict__.items():
            out[key] = "***" if any(s in key.lower() for s in _SECRET_KEYS) else value
        return out


DEFAULT_ENVIRONMENTS = {
    "local": {
        "base_url": "http://127.0.0.1:8077",
        "db_path": "artifacts/shopnest.db",
        "admin_email": "admin@shopnest.io",
        "admin_password": "AdminPass123",
        "user_email": "casey@example.com",
        "user_password": "Custom3rPass",
        "headless": True,
        "default_timeout_ms": 10000,
    },
    "ci": {
        "base_url": "http://127.0.0.1:8077",
        "db_path": "artifacts/shopnest.db",
        "admin_email": "admin@shopnest.io",
        "admin_password": "AdminPass123",
        "user_email": "casey@example.com",
        "user_password": "Custom3rPass",
        "headless": True,
        "default_timeout_ms": 20000,
    },
    "faulty": {
        "base_url": "http://127.0.0.1:8078",
        "db_path": "artifacts/shopnest-faulty.db",
        "admin_email": "admin@shopnest.io",
        "admin_password": "AdminPass123",
        "user_email": "casey@example.com",
        "user_password": "Custom3rPass",
        "headless": True,
        "default_timeout_ms": 10000,
        "fault_profile": "all",
    },
}


def _load_file() -> dict[str, Any]:
    path = CONFIG_DIR / "environments.yaml"
    if not path.exists():
        return DEFAULT_ENVIRONMENTS
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return data.get("environments", DEFAULT_ENVIRONMENTS)


def _env_override(key: str, current: Any) -> Any:
    """`TESTPILOT_BASE_URL` beats the YAML file; the YAML beats the default."""
    raw = os.getenv(f"TESTPILOT_{key.upper()}")
    if raw is None:
        return current
    if isinstance(current, bool):
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(current, int):
        return int(raw)
    return raw


@lru_cache(maxsize=None)
def get_environment(name: str | None = None) -> Environment:
    name = (name or os.getenv("TESTPILOT_ENV") or "local").strip()
    environments = _load_file()
    if name not in environments:
        known = ", ".join(sorted(environments))
        raise KeyError(f"Unknown environment {name!r}. Known environments: {known}")

    merged = {**DEFAULT_ENVIRONMENTS.get(name, {}), **(environments[name] or {})}
    resolved = {key: _env_override(key, value) for key, value in merged.items()}
    known_fields = {f for f in Environment.__dataclass_fields__ if f not in {"name", "extra"}}
    extra = {k: v for k, v in resolved.items() if k not in known_fields}
    core = {k: v for k, v in resolved.items() if k in known_fields}
    return Environment(name=name, extra=extra, **core)


def ensure_dirs() -> None:
    for directory in (ARTIFACTS, REPORTS_DIR, SCREENSHOTS_DIR, TRACES_DIR):
        directory.mkdir(parents=True, exist_ok=True)
