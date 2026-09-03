"""Deterministic seed data.

Every test that needs a known product, price or account relies on these
constants, so they are exported rather than hard-coded in the tests.
"""
from __future__ import annotations

from . import db as database
from .security import hash_password

ADMIN = {"email": "admin@shopnest.io", "password": "AdminPass123", "full_name": "Ada Admin", "role": "admin"}
CUSTOMER = {"email": "casey@example.com", "password": "Custom3rPass", "full_name": "Casey Customer", "role": "customer"}
SECOND_CUSTOMER = {"email": "riley@example.com", "password": "Ril3yPass99", "full_name": "Riley Rival", "role": "customer"}
DISABLED_USER = {"email": "dormant@example.com", "password": "Dorm4ntPass", "full_name": "Dana Dormant", "role": "customer"}

PRODUCTS = [
    # sku,            name,                     category,      price_cents, stock
    ("SN-KEYB-001", "Mechanical Keyboard",      "peripherals",     8999,  25),
    ("SN-MOUS-002", "Wireless Mouse",           "peripherals",     2499,  60),
    ("SN-HDST-003", "Noise Cancelling Headset", "audio",          14999,  12),
    ("SN-WEBC-004", "1080p Webcam",             "peripherals",     4550,   8),
    ("SN-MONI-005", "27-inch 4K Monitor",       "displays",       32900,   5),
    ("SN-DOCK-006", "USB-C Docking Station",    "peripherals",     11250,  0),   # deliberately out of stock
    ("SN-CABL-007", "Braided USB-C Cable",      "accessories",      999, 200),
    ("SN-STND-008", "Aluminium Laptop Stand",   "accessories",     3499,  40),
    ("SN-MICR-009", "Studio USB Microphone",    "audio",           7999,   3),   # low stock, boundary tests
    ("SN-LAMP-010", "Monitor Light Bar",        "accessories",     5900,  18),
]

COUPONS = [
    # code,      percent_off, min_spend_cents, active
    ("SAVE10",   10,      0,      1),
    ("BIG20",    20,   5000,      1),
    ("HALFOFF",  50,  20000,      1),
    ("EXPIRED5",  5,      0,      0),
]


def seed_database(only_if_empty: bool = False) -> None:
    database.init_db()
    with database.session() as conn:
        if only_if_empty:
            existing = conn.execute("SELECT COUNT(*) AS n FROM products").fetchone()["n"]
            if existing:
                return

        for account in (ADMIN, CUSTOMER, SECOND_CUSTOMER, DISABLED_USER):
            conn.execute(
                """
                INSERT INTO users (email, full_name, password_hash, role, is_active)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (email) DO UPDATE SET
                    password_hash = excluded.password_hash,
                    role          = excluded.role,
                    is_active     = excluded.is_active
                """,
                (
                    account["email"],
                    account["full_name"],
                    hash_password(account["password"]),
                    account["role"],
                    0 if account is DISABLED_USER else 1,
                ),
            )

        for sku, name, category, price_cents, stock in PRODUCTS:
            conn.execute(
                """
                INSERT INTO products (sku, name, description, category, price_cents, stock)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (sku) DO UPDATE SET
                    name        = excluded.name,
                    category    = excluded.category,
                    price_cents = excluded.price_cents,
                    stock       = excluded.stock
                """,
                (sku, name, f"{name} - dependable kit for the daily driver desk.", category, price_cents, stock),
            )

        for code, percent_off, min_spend, active in COUPONS:
            conn.execute(
                """
                INSERT INTO coupons (code, percent_off, min_spend_cents, is_active)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (code) DO UPDATE SET
                    percent_off     = excluded.percent_off,
                    min_spend_cents = excluded.min_spend_cents,
                    is_active       = excluded.is_active
                """,
                (code, percent_off, min_spend, active),
            )

        for row in conn.execute("SELECT id FROM users").fetchall():
            conn.execute("INSERT OR IGNORE INTO carts (user_id) VALUES (?)", (row["id"],))


if __name__ == "__main__":  # pragma: no cover
    seed_database()
    print("ShopNest database seeded.")
