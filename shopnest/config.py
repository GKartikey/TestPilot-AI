"""Runtime configuration for the ShopNest system under test.

Everything is environment driven so the same build can be pointed at a
local sqlite file, a CI scratch database, or a fault-injected instance
without code changes.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Fault profiles let us stand up a *deliberately* broken build so the QA
# platform has something real to catch.  "none" is the shipping behaviour.
KNOWN_FAULT_PROFILES = {
    "none": "Correct behaviour. Regression suite is expected to be green.",
    "coupon_stacking": "Coupon discount is applied once per cart line instead of once per cart.",
    "stock_oversell": "Stock check uses > instead of >=, allowing one unit of oversell.",
    "weak_auth": "Expired tokens are accepted, and /api/orders leaks other users' orders.",
    "all": "Every fault above enabled at once.",
}


def _flag(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


@dataclass
class Settings:
    app_name: str = "ShopNest"
    version: str = "1.4.0"
    db_path: Path = field(default_factory=lambda: Path(_flag("SHOPNEST_DB", str(ROOT / "artifacts" / "shopnest.db"))))
    jwt_secret: str = field(default_factory=lambda: _flag("SHOPNEST_JWT_SECRET", "shopnest-dev-secret-do-not-use-in-prod"))
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = field(default_factory=lambda: int(_flag("SHOPNEST_TOKEN_MINUTES", "60")))
    fault_profile: str = field(default_factory=lambda: _flag("SHOPNEST_FAULT_PROFILE", "none") or "none")
    host: str = field(default_factory=lambda: _flag("SHOPNEST_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(_flag("SHOPNEST_PORT", "8077")))

    # Business rules that the test suite asserts against.
    max_cart_quantity: int = 10
    min_cart_quantity: int = 1
    free_shipping_threshold: float = 50.00
    shipping_flat_rate: float = 4.99
    tax_rate: float = 0.08

    def fault_enabled(self, fault: str) -> bool:
        profile = self.fault_profile.lower()
        return profile == "all" or profile == fault

    @property
    def faults_active(self) -> bool:
        return self.fault_profile.lower() != "none"


settings = Settings()


def reload_settings() -> Settings:
    """Re-read the environment. Used by tests that flip fault profiles."""
    global settings
    settings = Settings()
    return settings
