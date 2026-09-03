"""Checkout and order lifecycle tests.

Checkout is where money, inventory and persistence meet, so these tests
verify all three: the response, the stored rows and the stock movement.
"""
from __future__ import annotations

import pytest

from framework.data import builders
from framework.utils.helpers import assert_status, expected_totals, temporarily_set_stock

pytestmark = pytest.mark.api


@pytest.fixture
def cable(customer_api):
    return customer_api.find_product_by_sku(builders.CABLE_SKU)


@pytest.fixture
def keyboard(customer_api):
    return customer_api.find_product_by_sku(builders.KEYBOARD_SKU)


# ------------------------------------------------------------- smoke ---

@pytest.mark.smoke
def test_a_customer_can_complete_a_checkout(customer_api, keyboard):
    """TC-ORD-001: the critical revenue path, end to end."""
    customer_api.add_to_cart(keyboard["id"], quantity=1)

    response = customer_api.checkout()
    assert_status(response, 201, "POST /api/orders")

    order = response.json()
    assert order["order_number"].startswith("SN-")
    assert order["status"] == "PLACED"
    assert len(order["items"]) == 1
    assert order["items"][0]["sku"] == builders.KEYBOARD_SKU
    assert order["total_cents"] > 0


@pytest.mark.smoke
def test_checkout_empties_the_cart(customer_api, cable):
    """TC-ORD-002: a placed order must not leave its items behind."""
    customer_api.add_to_cart(cable["id"], quantity=2)
    assert_status(customer_api.checkout(), 201, "checkout")

    assert customer_api.get_cart().json()["items"] == [], (
        "the cart still contained items after a successful checkout"
    )


# -------------------------------------------------------- correctness ---

@pytest.mark.regression
def test_order_totals_match_the_cart_totals_at_the_moment_of_checkout(customer_api, keyboard, cable):
    """TC-ORD-010: the price the customer saw is the price they are charged."""
    customer_api.add_to_cart(keyboard["id"], quantity=2)
    customer_api.add_to_cart(cable["id"], quantity=1)
    cart_totals = customer_api.get_cart().json()["totals"]

    order = customer_api.checkout().json()

    for field in ("subtotal_cents", "discount_cents", "shipping_cents", "tax_cents", "total_cents"):
        assert order[field] == cart_totals[field], (
            f"{field} changed between cart and order: cart said {cart_totals[field]}, "
            f"the order says {order[field]}."
        )


@pytest.mark.regression
def test_order_totals_match_the_independent_pricing_oracle(customer_api, keyboard):
    """TC-ORD-011: order maths checked against the documented rules."""
    customer_api.add_to_cart(keyboard["id"], quantity=2)
    customer_api.apply_coupon(builders.COUPON_TEN)

    order = customer_api.checkout().json()
    expected = expected_totals([(keyboard["price_cents"], 2)], percent_off=10)

    assert {k: order[k] for k in expected.as_dict()} == expected.as_dict(), (
        f"Order totals disagreed with the documented pricing rules.\n"
        f"  Order:    { {k: order[k] for k in expected.as_dict()} }\n"
        f"  Expected: {expected.as_dict()}"
    )


@pytest.mark.regression
def test_checkout_decrements_stock_by_the_ordered_quantity(customer_api, db):
    """TC-ORD-012: inventory actually moves, verified in SQL."""
    before = db.stock_for(builders.CABLE_SKU)
    product = customer_api.find_product_by_sku(builders.CABLE_SKU)

    customer_api.add_to_cart(product["id"], quantity=3)
    assert_status(customer_api.checkout(), 201, "checkout 3 cables")

    after = db.stock_for(builders.CABLE_SKU)
    assert after == before - 3, f"stock went from {before} to {after}; a decrement of exactly 3 was expected"


@pytest.mark.regression
def test_order_line_items_are_persisted_with_the_price_at_purchase_time(customer_api, db, keyboard):
    """TC-ORD-013: the order stores its own prices, not a live lookup.

    If a line item read today's catalogue price, every historical order
    would silently restate itself after a price change.
    """
    customer_api.add_to_cart(keyboard["id"], quantity=2)
    order = customer_api.checkout().json()

    stored = db.order_by_number(order["order_number"])
    assert stored is not None, f"order {order['order_number']} was returned by the API but not found in the database"

    lines = db.order_items(stored["id"])
    assert len(lines) == 1
    assert lines[0]["sku"] == builders.KEYBOARD_SKU
    assert lines[0]["quantity"] == 2
    assert lines[0]["unit_price_cents"] == keyboard["price_cents"]
    assert lines[0]["line_total_cents"] == keyboard["price_cents"] * 2


@pytest.mark.regression
def test_each_order_receives_a_unique_order_number(customer_api, cable):
    """TC-ORD-014: order numbers must not collide."""
    numbers = set()
    for _ in range(3):
        customer_api.add_to_cart(cable["id"], quantity=1)
        numbers.add(customer_api.checkout()["order_number"])

    assert len(numbers) == 3, f"expected 3 distinct order numbers, got {numbers}"


# ----------------------------------------------------------- negative ---

@pytest.mark.negative
def test_checking_out_an_empty_cart_is_rejected(customer_api):
    """TC-ORD-020: there is nothing to buy, so there is no order."""
    response = customer_api.checkout()

    assert_status(response, 400, "checkout with an empty cart")
    assert "empty" in response.detail.lower()


@pytest.mark.negative
def test_checkout_requires_authentication(api):
    """TC-ORD-021: anonymous checkout is not a thing."""
    assert_status(api.post("/api/orders", authenticate=False), 401, "POST /api/orders with no token")


@pytest.mark.negative
def test_checkout_is_refused_when_stock_disappears_after_the_cart_was_built(customer_api, db):
    """TC-ORD-022: stock is revalidated at checkout, not only at add time.

    Reproduces the real-world race where an item sells out between
    browsing and paying. Failing to re-check here is how a shop takes
    money for inventory it does not have.
    """
    product = customer_api.find_product_by_sku(builders.LOW_STOCK_SKU)
    original = db.stock_for(builders.LOW_STOCK_SKU)

    db.set_stock(builders.LOW_STOCK_SKU, 5)
    try:
        assert_status(customer_api.add_to_cart(product["id"], quantity=5), 201, "add 5 while 5 are in stock")

        db.set_stock(builders.LOW_STOCK_SKU, 2)  # somebody else bought three

        response = customer_api.checkout()
        assert response.status == 409, (
            f"Checkout succeeded with status {response.status} for 5 units when only 2 remained. "
            "Stock must be revalidated at checkout."
        )
    finally:
        customer_api.clear_cart()
        db.set_stock(builders.LOW_STOCK_SKU, original)


@pytest.mark.negative
def test_a_failed_checkout_leaves_no_partial_order(customer_api, db):
    """TC-ORD-023: the checkout transaction is all-or-nothing."""
    product = customer_api.find_product_by_sku(builders.LOW_STOCK_SKU)
    original = db.stock_for(builders.LOW_STOCK_SKU)
    orders_before = db.count("orders")

    db.set_stock(builders.LOW_STOCK_SKU, 3)
    try:
        customer_api.add_to_cart(product["id"], quantity=3)
        db.set_stock(builders.LOW_STOCK_SKU, 1)

        assert customer_api.checkout().status == 409

        assert db.count("orders") == orders_before, "a rejected checkout created an order row"
        assert db.stock_for(builders.LOW_STOCK_SKU) == 1, "a rejected checkout moved stock"
        assert customer_api.get_cart().json()["items"], "a rejected checkout cleared the cart"
    finally:
        customer_api.clear_cart()
        db.set_stock(builders.LOW_STOCK_SKU, original)


@pytest.mark.boundary
def test_checking_out_exactly_the_last_unit_in_stock_succeeds(customer_api, db):
    """TC-ORD-024: the inclusive edge of availability, at checkout."""
    product = customer_api.find_product_by_sku(builders.LOW_STOCK_SKU)
    original = db.stock_for(builders.LOW_STOCK_SKU)

    with temporarily_set_stock(db, builders.LOW_STOCK_SKU, 1):
        customer_api.add_to_cart(product["id"], quantity=1)
        response = customer_api.checkout()

        assert response.status == 201, (
            f"Buying the last unit in stock was refused with {response.status}: {response.detail}"
        )
        assert db.stock_for(builders.LOW_STOCK_SKU) == 0
    db.set_stock(builders.LOW_STOCK_SKU, original)


# ---------------------------------------------------------- lifecycle ---

@pytest.mark.regression
def test_an_order_appears_in_the_customers_history(customer_api, cable):
    """TC-ORD-030: placed orders are retrievable afterwards."""
    order = customer_api.place_order_with(cable["id"], quantity=1).json()

    history = customer_api.list_orders()
    assert_status(history, 200, "GET /api/orders")
    assert order["order_number"] in [o["order_number"] for o in history.json()]


@pytest.mark.regression
def test_an_order_can_be_retrieved_by_id_with_its_line_items(customer_api, cable):
    """TC-ORD-031: detail retrieval returns the full order."""
    placed = customer_api.place_order_with(cable["id"], quantity=2).json()

    fetched = customer_api.get_order(placed["id"])
    assert_status(fetched, 200, f"GET /api/orders/{placed['id']}")
    assert fetched["order_number"] == placed["order_number"]
    assert fetched["items"][0]["quantity"] == 2


@pytest.mark.negative
def test_retrieving_an_unknown_order_returns_not_found(customer_api):
    """TC-ORD-032: an id that does not exist is a 404."""
    assert_status(customer_api.get_order(999_999), 404, "GET a nonexistent order")


@pytest.mark.regression
def test_cancelling_an_order_restores_its_stock(customer_api, db, cable):
    """TC-ORD-033: cancellation is a compensating transaction."""
    before = db.stock_for(builders.CABLE_SKU)
    order = customer_api.place_order_with(cable["id"], quantity=2).json()
    assert db.stock_for(builders.CABLE_SKU) == before - 2

    response = customer_api.cancel_order(order["id"])
    assert_status(response, 200, f"cancel order {order['order_number']}")
    assert response["status"] == "CANCELLED"
    assert db.stock_for(builders.CABLE_SKU) == before, "cancelling did not return the units to stock"


@pytest.mark.regression
def test_cancelling_an_already_cancelled_order_is_idempotent(customer_api, db, cable):
    """TC-ORD-034: a double cancel must not double-credit stock."""
    before = db.stock_for(builders.CABLE_SKU)
    order = customer_api.place_order_with(cable["id"], quantity=1).json()

    customer_api.cancel_order(order["id"])
    second = customer_api.cancel_order(order["id"])

    assert_status(second, 200, "cancel the same order twice")
    assert second["status"] == "CANCELLED"
    assert db.stock_for(builders.CABLE_SKU) == before, (
        "the second cancellation credited stock a second time"
    )
