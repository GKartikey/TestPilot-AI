"""SQL validation tests.

The API can return a perfectly shaped 201 and still have written the
wrong row. These tests go straight to the database and check three
different things:

  * schema      - constraints, keys and indexes exist as designed
  * integrity   - no orphans, no duplicates, no impossible values
  * reconciliation - stored money and stock agree with the documented rules

Together they are the layer that catches "the response looked fine".
"""
from __future__ import annotations

import sqlite3

import pytest

from framework.data import builders
from framework.utils.helpers import assert_status

pytestmark = pytest.mark.db


# ------------------------------------------------------------ schema ---

@pytest.mark.smoke
def test_every_expected_table_exists(db):
    """TC-SQL-001: the schema deployed is the schema designed."""
    expected = {"users", "products", "carts", "cart_items", "coupons", "orders", "order_items"}

    missing = expected - set(db.table_names())
    assert not missing, f"the database is missing tables: {sorted(missing)}"


@pytest.mark.regression
@pytest.mark.parametrize(
    "table,column",
    [
        ("users", "email"),
        ("users", "password_hash"),
        ("users", "role"),
        ("products", "sku"),
        ("products", "price_cents"),
        ("products", "stock"),
        ("orders", "order_number"),
        ("orders", "total_cents"),
        ("order_items", "unit_price_cents"),
        ("order_items", "line_total_cents"),
    ],
)
def test_required_columns_are_present(db, table, column):
    """TC-SQL-002: column-level contract for the tables the app depends on."""
    names = [c["name"] for c in db.columns(table)]

    assert column in names, f"{table}.{column} is missing. Columns present: {names}"


@pytest.mark.regression
def test_money_and_quantity_columns_are_integers(db):
    """TC-SQL-003: money is stored in integer cents, never as a float.

    Floating-point money accumulates rounding error. Catching a schema
    drift to REAL here is far cheaper than reconciling a ledger later.
    """
    money_columns = {
        "products": ["price_cents", "stock"],
        "orders": ["subtotal_cents", "discount_cents", "shipping_cents", "tax_cents", "total_cents"],
        "order_items": ["quantity", "unit_price_cents", "line_total_cents"],
    }
    for table, columns in money_columns.items():
        types = {c["name"]: c["type"].upper() for c in db.columns(table)}
        for column in columns:
            assert types[column] == "INTEGER", (
                f"{table}.{column} is declared {types[column]}, not INTEGER. "
                "Monetary and quantity values must be stored as integers."
            )


@pytest.mark.regression
def test_foreign_keys_are_declared_between_related_tables(db):
    """TC-SQL-004: referential integrity is enforced by the database."""
    relationships = {
        "cart_items": {"carts", "products"},
        "order_items": {"orders", "products"},
        "orders": {"users"},
        "carts": {"users"},
    }
    for table, expected_targets in relationships.items():
        actual = {fk["table"] for fk in db.foreign_keys(table)}
        missing = expected_targets - actual
        assert not missing, f"{table} has no foreign key to {sorted(missing)}; found references to {sorted(actual)}"


@pytest.mark.regression
def test_lookup_columns_are_indexed(db):
    """TC-SQL-005: the queries the app runs on every page have an index."""
    assert any("category" in name for name in db.indexes("products")), (
        "products.category is filtered on every catalogue request but is not indexed"
    )
    assert any("user" in name for name in db.indexes("orders")), (
        "orders.user_id is the tenant filter for order history but is not indexed"
    )


@pytest.mark.negative
def test_the_database_rejects_a_negative_price(db):
    """TC-SQL-006: the CHECK constraint is real, not documentation."""
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO products (sku, name, category, price_cents, stock) VALUES (?,?,?,?,?)",
            ("TP-NEGATIVE-PRICE", "Impossible", "test", -100, 1),
        )


@pytest.mark.negative
def test_the_database_rejects_a_duplicate_sku(db):
    """TC-SQL-007: the uniqueness constraint is enforced at the storage layer."""
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO products (sku, name, category, price_cents, stock) VALUES (?,?,?,?,?)",
            (builders.KEYBOARD_SKU, "Duplicate Keyboard", "test", 100, 1),
        )


@pytest.mark.negative
def test_the_database_rejects_an_invalid_order_status(db):
    """TC-SQL-008: status is a closed set, guarded by a CHECK."""
    user_id = db.scalar("SELECT id FROM users LIMIT 1")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO orders (order_number, user_id, status, subtotal_cents, total_cents) "
            "VALUES (?,?,?,?,?)",
            ("SN-BADSTATUS", user_id, "TELEPORTED", 100, 100),
        )


@pytest.mark.negative
def test_a_cart_item_cannot_reference_a_product_that_does_not_exist(db):
    """TC-SQL-009: foreign keys are enforced at runtime, not just declared."""
    cart_id = db.scalar("SELECT id FROM carts LIMIT 1")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO cart_items (cart_id, product_id, quantity) VALUES (?,?,?)",
            (cart_id, 999_999, 1),
        )


# --------------------------------------------------------- integrity ---

@pytest.mark.smoke
def test_there_are_no_foreign_key_violations(db):
    """TC-SQL-020: nothing in the database points at a row that is gone."""
    violations = db.integrity_violations()

    assert violations == [], f"foreign key check found {len(violations)} violation(s): {violations[:5]}"


@pytest.mark.regression
def test_no_order_item_is_orphaned(db):
    """TC-SQL-021: every line belongs to an order that exists."""
    orphans = db.orphaned_order_items()

    assert orphans == [], f"{len(orphans)} order line(s) have no parent order: {orphans[:5]}"


@pytest.mark.regression
def test_no_product_has_negative_stock(db):
    """TC-SQL-022: stock can reach zero, never go below it."""
    negative = db.negative_stock()

    assert negative == [], f"products with impossible stock levels: {negative}"


@pytest.mark.regression
def test_no_two_users_share_an_email_address(db):
    """TC-SQL-023: account identity is unique, case-insensitively."""
    duplicates = db.duplicate_emails()

    assert duplicates == [], f"duplicate email addresses found: {duplicates}"


@pytest.mark.regression
@pytest.mark.auth
def test_no_password_is_stored_in_a_recoverable_form(db):
    """TC-SQL-024: every credential is a PBKDF2 hash.

    This is the single most important row-level check in the schema: a
    plaintext or unsalted password is a breach waiting to be reported.
    """
    offenders = db.plaintext_password_rows()

    assert offenders == [], (
        f"{len(offenders)} user row(s) do not hold a PBKDF2 hash: "
        f"{[o['email'] for o in offenders[:5]]}"
    )


@pytest.mark.regression
@pytest.mark.auth
def test_password_hashes_are_uniquely_salted(db):
    """TC-SQL-025: two identical passwords must not produce one hash."""
    total = db.scalar("SELECT COUNT(*) FROM users")
    distinct = db.scalar("SELECT COUNT(DISTINCT password_hash) FROM users")

    assert distinct == total, (
        f"{total} users share only {distinct} distinct hashes. "
        "Identical hashes indicate the salt is missing or constant."
    )


# ---------------------------------------------------- reconciliation ---

@pytest.mark.regression
def test_every_order_line_total_equals_quantity_times_unit_price(db, customer_api, cable):
    """TC-SQL-030: line arithmetic, checked in SQL across every row."""
    customer_api.place_order_with(cable["id"], quantity=3)

    mismatches = db.order_line_total_mismatches()
    assert mismatches == [], (
        f"{len(mismatches)} order line(s) where line_total != quantity * unit_price: {mismatches[:3]}"
    )


@pytest.mark.regression
def test_every_order_subtotal_equals_the_sum_of_its_lines(db, customer_api, cable, keyboard):
    """TC-SQL-031: the header agrees with its lines."""
    customer_api.add_to_cart(cable["id"], quantity=2)
    customer_api.add_to_cart(keyboard["id"], quantity=1)
    assert_status(customer_api.checkout(), 201, "place a two-line order")

    mismatches = db.order_header_mismatches()
    assert mismatches == [], (
        f"{len(mismatches)} order(s) whose subtotal does not match their line items: {mismatches[:3]}"
    )


@pytest.mark.regression
def test_every_order_total_is_internally_consistent(db, customer_api, keyboard):
    """TC-SQL-032: subtotal - discount + shipping + tax == total, for all rows."""
    customer_api.add_to_cart(keyboard["id"], quantity=1)
    customer_api.apply_coupon(builders.COUPON_TEN)
    assert_status(customer_api.checkout(), 201, "place a discounted order")

    mismatches = db.order_arithmetic_mismatches()
    assert mismatches == [], (
        f"{len(mismatches)} order(s) where the stored total does not equal "
        f"subtotal - discount + shipping + tax: {mismatches[:3]}"
    )


@pytest.mark.regression
def test_a_placed_order_is_written_with_the_expected_row_shape(db, customer_api, keyboard):
    """TC-SQL-033: API response and stored row describe the same order."""
    customer_api.add_to_cart(keyboard["id"], quantity=2)
    api_order = customer_api.checkout().json()

    row = db.order_by_number(api_order["order_number"])
    assert row is not None, "the order returned by the API is not in the database"
    for field in ("subtotal_cents", "discount_cents", "shipping_cents", "tax_cents", "total_cents"):
        assert row[field] == api_order[field], (
            f"{field}: the API returned {api_order[field]} but the database stored {row[field]}"
        )
    assert row["status"] == "PLACED"


@pytest.mark.regression
def test_a_cancelled_order_keeps_its_line_items_for_audit(db, customer_api, cable):
    """TC-SQL-034: cancellation changes status; it never deletes history."""
    order = customer_api.place_order_with(cable["id"], quantity=1).json()
    customer_api.cancel_order(order["id"])

    row = db.order_by_number(order["order_number"])
    assert row["status"] == "CANCELLED"
    assert db.order_items(row["id"]), "the cancelled order lost its line items"


@pytest.mark.regression
def test_revenue_by_category_reconciles_with_the_order_items(db, customer_api, keyboard):
    """TC-SQL-035: a real reporting join returns coherent numbers.

    Aggregate queries are where a silently wrong JOIN shows up, so the
    report is cross-checked against the raw sum it is derived from.
    """
    customer_api.place_order_with(keyboard["id"], quantity=1)

    report = db.revenue_by_category()
    assert report, "the revenue report returned no rows despite orders existing"

    reported_total = sum(row["gross_cents"] for row in report)
    raw_total = db.scalar(
        """
        SELECT COALESCE(SUM(oi.line_total_cents), 0)
        FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        WHERE o.status <> 'CANCELLED'
        """
    )
    assert reported_total == raw_total, (
        f"the grouped report totals {reported_total} cents but the raw sum is {raw_total} cents"
    )


@pytest.mark.regression
def test_cart_contents_are_reachable_through_the_full_join_path(db, customer_api, cable):
    """TC-SQL-036: users -> carts -> cart_items -> products all connect."""
    customer_api.add_to_cart(cable["id"], quantity=2)

    rows = db.cart_rows_for(builders.SEEDED_CUSTOMER["email"])
    assert len(rows) == 1, f"the four-table join returned {len(rows)} rows, expected 1"
    assert rows[0]["sku"] == builders.CABLE_SKU
    assert rows[0]["quantity"] == 2


@pytest.fixture
def cable(customer_api):
    return customer_api.find_product_by_sku(builders.CABLE_SKU)


@pytest.fixture
def keyboard(customer_api):
    return customer_api.find_product_by_sku(builders.KEYBOARD_SKU)
