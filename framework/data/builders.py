"""Test data builders.

Builders beat literal dicts in tests because a test then states only the
field it cares about: `UserBuilder().with_password("short").build()`
reads as an intention, and the other fields stay valid so the test fails
for the reason it claims to be about.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..utils.helpers import unique_email, unique_sku

# Seeded fixtures from shopnest/seed.py. Tests import these constants
# rather than repeating literals, so a change to the seed data breaks in
# one place.
SEEDED_CUSTOMER = {"email": "casey@example.com", "password": "Custom3rPass"}
SEEDED_SECOND_CUSTOMER = {"email": "riley@example.com", "password": "Ril3yPass99"}
SEEDED_ADMIN = {"email": "admin@shopnest.io", "password": "AdminPass123"}
SEEDED_DISABLED = {"email": "dormant@example.com", "password": "Dorm4ntPass"}

KEYBOARD_SKU = "SN-KEYB-001"      # 8999 cents, stock 25
MOUSE_SKU = "SN-MOUS-002"         # 2499 cents, stock 60
HEADSET_SKU = "SN-HDST-003"       # 14999 cents, stock 12
CABLE_SKU = "SN-CABL-007"         #  999 cents, stock 200
OUT_OF_STOCK_SKU = "SN-DOCK-006"  # 11250 cents, stock 0
LOW_STOCK_SKU = "SN-MICR-009"     # 7999 cents, stock 3

COUPON_TEN = "SAVE10"        # 10% off, no minimum
COUPON_TWENTY = "BIG20"      # 20% off over 5000 cents
COUPON_HALF = "HALFOFF"      # 50% off over 20000 cents
COUPON_INACTIVE = "EXPIRED5"

FREE_SHIPPING_THRESHOLD_CENTS = 5000
SHIPPING_FLAT_CENTS = 499
TAX_RATE = 0.08
MAX_CART_QUANTITY = 10
MIN_CART_QUANTITY = 1
MIN_PASSWORD_LENGTH = 8


@dataclass
class UserBuilder:
    email: str = field(default_factory=lambda: unique_email())
    password: str = "Valid1Password"
    full_name: str = "Quinn Tester"

    def with_email(self, email: str) -> "UserBuilder":
        self.email = email
        return self

    def with_password(self, password: str) -> "UserBuilder":
        self.password = password
        return self

    def with_name(self, full_name: str) -> "UserBuilder":
        self.full_name = full_name
        return self

    def build(self) -> dict[str, Any]:
        return {"email": self.email, "password": self.password, "full_name": self.full_name}


@dataclass
class ProductBuilder:
    sku: str = field(default_factory=lambda: unique_sku())
    name: str = "Test Product"
    description: str = "Created by the automated suite."
    category: str = "test-fixtures"
    price_cents: int = 1999
    stock: int = 10

    def with_sku(self, sku: str) -> "ProductBuilder":
        self.sku = sku
        return self

    def with_price(self, price_cents: int) -> "ProductBuilder":
        self.price_cents = price_cents
        return self

    def with_stock(self, stock: int) -> "ProductBuilder":
        self.stock = stock
        return self

    def with_category(self, category: str) -> "ProductBuilder":
        self.category = category
        return self

    def build(self) -> dict[str, Any]:
        return {
            "sku": self.sku,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "price_cents": self.price_cents,
            "stock": self.stock,
        }


# ------------------------------------------------- negative payloads ---
# Named so a parametrised test's report reads as a sentence.

INVALID_EMAILS = [
    ("no_at_sign", "notanemail.example.com"),
    ("no_domain", "user@"),
    ("no_local_part", "@example.com"),
    ("no_tld", "user@example"),
    ("empty", ""),
    ("spaces_only", "   "),
    ("embedded_space", "user name@example.com"),
    ("double_at", "user@@example.com"),
]

WEAK_PASSWORDS = [
    ("too_short", "Ab1"),
    ("seven_characters", "Abcde12"),
    ("no_digit", "PasswordOnly"),
    ("no_letter", "12345678"),
    ("empty", ""),
]

SQL_INJECTION_STRINGS = [
    ("classic_or", "' OR '1'='1"),
    ("comment_terminator", "admin'--"),
    ("stacked_drop", "'; DROP TABLE users; --"),
    ("union_select", "' UNION SELECT password_hash FROM users --"),
]

XSS_STRINGS = [
    ("script_tag", "<script>alert('xss')</script>"),
    ("img_onerror", "<img src=x onerror=alert(1)>"),
    ("svg_onload", "<svg onload=alert(1)>"),
]

MALFORMED_TOKENS = [
    ("empty", ""),
    ("not_a_jwt", "this-is-not-a-token"),
    ("wrong_scheme", "Basic abcdef"),
    ("two_segments", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0"),
    ("bad_signature", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.deadbeefdeadbeefdeadbeef"),
]

# (label, quantity, should_be_accepted) -- the classic boundary table for
# a field documented as 1..10 inclusive.
CART_QUANTITY_BOUNDARIES = [
    ("below_minimum", 0, False),
    ("negative", -1, False),
    ("at_minimum", 1, True),
    ("just_inside_minimum", 2, True),
    ("mid_range", 5, True),
    ("just_inside_maximum", 9, True),
    ("at_maximum", 10, True),
    ("above_maximum", 11, False),
    ("far_above_maximum", 9999, False),
]
