"""SQL access to the system under test's database.

UI and API tests confirm what the application *says*. These queries
confirm what it actually *stored*. That distinction matters: an endpoint
can return 201 and still write the wrong row, and only SQL catches it.

The client is read-mostly by design. Tests that mutate state should do so
through the API so that they exercise real business rules; direct writes
are reserved for setting up conditions the API cannot reach (deactivating
a product, expiring a coupon).
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


@dataclass
class DbClient:
    db_path: str | Path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            conn.close()

    # -- generic -------------------------------------------------------
    def query(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def scalar(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        row = self.one(sql, params)
        return next(iter(row.values())) if row else None

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        with self.connect() as conn:
            cursor = conn.execute(sql, params)
            conn.commit()
            return cursor.rowcount

    def count(self, table: str, where: str = "1=1", params: tuple[Any, ...] = ()) -> int:
        return int(self.scalar(f"SELECT COUNT(*) FROM {table} WHERE {where}", params) or 0)

    def table_names(self) -> list[str]:
        return [
            r["name"]
            for r in self.query("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
        ]

    def columns(self, table: str) -> list[dict[str, Any]]:
        return self.query(f"PRAGMA table_info({table})")

    def indexes(self, table: str) -> list[str]:
        return [r["name"] for r in self.query(f"PRAGMA index_list({table})")]

    def foreign_keys(self, table: str) -> list[dict[str, Any]]:
        return self.query(f"PRAGMA foreign_key_list({table})")

    def integrity_violations(self) -> list[dict[str, Any]]:
        """Rows whose foreign keys point at nothing. Should always be empty."""
        return self.query("PRAGMA foreign_key_check")

    # -- domain queries ------------------------------------------------
    def user_by_email(self, email: str) -> dict[str, Any] | None:
        return self.one("SELECT * FROM users WHERE email = ?", (email.lower(),))

    def product_by_sku(self, sku: str) -> dict[str, Any] | None:
        return self.one("SELECT * FROM products WHERE sku = ?", (sku,))

    def stock_for(self, sku: str) -> int:
        return int(self.scalar("SELECT stock FROM products WHERE sku = ?", (sku,)) or 0)

    def set_stock(self, sku: str, stock: int) -> None:
        self.execute("UPDATE products SET stock = ? WHERE sku = ?", (stock, sku))

    def order_by_number(self, order_number: str) -> dict[str, Any] | None:
        return self.one("SELECT * FROM orders WHERE order_number = ?", (order_number,))

    def order_items(self, order_id: int) -> list[dict[str, Any]]:
        return self.query("SELECT * FROM order_items WHERE order_id = ? ORDER BY id", (order_id,))

    def cart_rows_for(self, email: str) -> list[dict[str, Any]]:
        return self.query(
            """
            SELECT ci.*, p.sku
            FROM cart_items ci
            JOIN carts c   ON c.id = ci.cart_id
            JOIN users u   ON u.id = c.user_id
            JOIN products p ON p.id = ci.product_id
            WHERE u.email = ?
            """,
            (email.lower(),),
        )

    # -- reconciliation ------------------------------------------------
    def order_line_total_mismatches(self) -> list[dict[str, Any]]:
        """Lines where quantity * unit price does not equal the stored line total."""
        return self.query(
            """
            SELECT id, order_id, sku, quantity, unit_price_cents, line_total_cents,
                   (quantity * unit_price_cents) AS expected_line_total
            FROM order_items
            WHERE line_total_cents <> quantity * unit_price_cents
            """
        )

    def order_header_mismatches(self) -> list[dict[str, Any]]:
        """Orders whose subtotal does not equal the sum of their lines."""
        return self.query(
            """
            SELECT o.id, o.order_number, o.subtotal_cents,
                   COALESCE(SUM(oi.line_total_cents), 0) AS line_sum
            FROM orders o
            LEFT JOIN order_items oi ON oi.order_id = o.id
            GROUP BY o.id
            HAVING o.subtotal_cents <> COALESCE(SUM(oi.line_total_cents), 0)
            """
        )

    def order_arithmetic_mismatches(self) -> list[dict[str, Any]]:
        """Orders where subtotal - discount + shipping + tax != total."""
        return self.query(
            """
            SELECT id, order_number, subtotal_cents, discount_cents,
                   shipping_cents, tax_cents, total_cents,
                   (subtotal_cents - discount_cents + shipping_cents + tax_cents) AS expected_total
            FROM orders
            WHERE total_cents <> subtotal_cents - discount_cents + shipping_cents + tax_cents
            """
        )

    def orphaned_order_items(self) -> list[dict[str, Any]]:
        return self.query(
            """
            SELECT oi.id, oi.order_id
            FROM order_items oi
            LEFT JOIN orders o ON o.id = oi.order_id
            WHERE o.id IS NULL
            """
        )

    def negative_stock(self) -> list[dict[str, Any]]:
        return self.query("SELECT id, sku, stock FROM products WHERE stock < 0")

    def duplicate_emails(self) -> list[dict[str, Any]]:
        return self.query(
            "SELECT LOWER(email) AS email, COUNT(*) AS n FROM users GROUP BY LOWER(email) HAVING n > 1"
        )

    def plaintext_password_rows(self) -> list[dict[str, Any]]:
        """No stored hash may look like a plaintext password."""
        return self.query("SELECT id, email FROM users WHERE password_hash NOT LIKE 'pbkdf2_sha256$%'")

    def revenue_by_category(self) -> list[dict[str, Any]]:
        """A realistic reporting join, used to prove multi-table SQL works."""
        return self.query(
            """
            SELECT p.category,
                   COUNT(DISTINCT o.id)          AS orders,
                   SUM(oi.quantity)              AS units,
                   SUM(oi.line_total_cents)      AS gross_cents
            FROM order_items oi
            JOIN orders   o ON o.id = oi.order_id
            JOIN products p ON p.id = oi.product_id
            WHERE o.status <> 'CANCELLED'
            GROUP BY p.category
            ORDER BY gross_cents DESC
            """
        )
