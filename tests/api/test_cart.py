"""Cart API tests: quantity rules, stock limits, coupons and pricing.

The pricing assertions here are checked against an independent oracle in
`framework.utils.helpers.expected_totals`, which reimplements the
documented rules rather than importing the application's own maths.
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


# ------------------------------------------------------------ basics ---

@pytest.mark.smoke
def test_a_product_can_be_added_to_the_cart(customer_api, keyboard):
    """TC-CART-001: the core add-to-cart path."""
    response = customer_api.add_to_cart(keyboard["id"], quantity=2)

    assert_status(response, 201, "add 2 keyboards to the cart")
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["sku"] == builders.KEYBOARD_SKU
    assert items[0]["quantity"] == 2
    assert items[0]["line_total_cents"] == keyboard["price_cents"] * 2


@pytest.mark.regression
def test_adding_the_same_product_twice_accumulates_the_quantity(customer_api, cable):
    """TC-CART-002: a second add merges rather than duplicating the line."""
    customer_api.add_to_cart(cable["id"], quantity=2)
    response = customer_api.add_to_cart(cable["id"], quantity=3)

    assert_status(response, 201, "second add of the same product")
    items = response.json()["items"]
    assert len(items) == 1, f"expected one merged line, got {len(items)}"
    assert items[0]["quantity"] == 5


@pytest.mark.regression
def test_cart_quantity_can_be_updated_and_the_line_total_follows(customer_api, cable):
    """TC-CART-003: PATCH replaces the quantity and recomputes the line."""
    customer_api.add_to_cart(cable["id"], quantity=2)

    response = customer_api.update_cart_item(cable["id"], quantity=7)
    assert_status(response, 200, "update quantity to 7")
    item = response.json()["items"][0]
    assert item["quantity"] == 7
    assert item["line_total_cents"] == cable["price_cents"] * 7


@pytest.mark.regression
def test_setting_a_quantity_of_zero_removes_the_line(customer_api, cable):
    """TC-CART-004: zero is documented as 'remove', not as invalid."""
    customer_api.add_to_cart(cable["id"], quantity=3)

    response = customer_api.update_cart_item(cable["id"], quantity=0)
    assert_status(response, 200, "update quantity to 0")
    assert response.json()["items"] == []


@pytest.mark.regression
def test_a_product_can_be_removed_from_the_cart(customer_api, cable, keyboard):
    """TC-CART-005: removal takes out one line and leaves the others."""
    customer_api.add_to_cart(cable["id"], quantity=1)
    customer_api.add_to_cart(keyboard["id"], quantity=1)

    response = customer_api.remove_cart_item(cable["id"])
    assert_status(response, 200, "remove the cable")
    remaining = [item["sku"] for item in response.json()["items"]]
    assert remaining == [builders.KEYBOARD_SKU]


@pytest.mark.regression
def test_carts_are_isolated_between_customers(customer_api, second_customer_api, cable):
    """TC-CART-006: one customer's basket never appears in another's."""
    customer_api.add_to_cart(cable["id"], quantity=4)

    other = second_customer_api.get_cart()
    assert_status(other, 200, "second customer reads their own cart")
    assert other.json()["items"] == [], "the second customer saw the first customer's cart contents"


# ---------------------------------------------------------- negative ---

@pytest.mark.negative
def test_the_cart_requires_authentication(api):
    """TC-CART-010: the cart is never anonymous."""
    assert_status(api.get("/api/cart", authenticate=False), 401, "GET /api/cart with no token")
    assert_status(
        api.post("/api/cart/items", {"product_id": 1, "quantity": 1}, authenticate=False),
        401,
        "POST /api/cart/items with no token",
    )


@pytest.mark.negative
def test_adding_a_product_that_does_not_exist_returns_not_found(customer_api):
    """TC-CART-011: an unknown product id cannot enter a cart."""
    response = customer_api.add_to_cart(999_999, quantity=1)

    assert_status(response, 404, "add a nonexistent product")
    assert customer_api.get_cart().json()["items"] == [], "a failed add must not create a line"


@pytest.mark.negative
def test_updating_a_product_that_is_not_in_the_cart_returns_not_found(customer_api, cable):
    """TC-CART-012: PATCH on an absent line is a 404, not a silent insert."""
    response = customer_api.update_cart_item(cable["id"], quantity=3)

    assert_status(response, 404, "PATCH a line that was never added")


@pytest.mark.negative
def test_removing_a_product_that_is_not_in_the_cart_returns_not_found(customer_api, cable):
    """TC-CART-013: DELETE is not silently idempotent here, by design."""
    assert_status(customer_api.remove_cart_item(cable["id"]), 404, "DELETE an absent line")


# ---------------------------------------------------------- boundary ---

@pytest.mark.boundary
@pytest.mark.parametrize(
    "label,quantity,should_be_accepted",
    builders.CART_QUANTITY_BOUNDARIES,
    ids=[case[0] for case in builders.CART_QUANTITY_BOUNDARIES],
)
def test_cart_quantity_boundaries(customer_api, cable, label, quantity, should_be_accepted):
    """TC-CART-020: the documented 1..10 range, tested at every edge.

    One parametrised test covers below-minimum, at-minimum, at-maximum
    and above-maximum, which is the whole equivalence-partition table for
    this field.
    """
    response = customer_api.add_to_cart(cable["id"], quantity=quantity)

    if should_be_accepted:
        assert response.status == 201, (
            f"quantity={quantity} ({label}) is inside the documented 1..10 range "
            f"but was rejected with {response.status}: {response.detail}"
        )
        assert response.json()["items"][0]["quantity"] == quantity
    else:
        assert response.status == 422, (
            f"quantity={quantity} ({label}) is outside the documented 1..10 range "
            f"but was accepted with {response.status}."
        )
        assert customer_api.get_cart().json()["items"] == []


@pytest.mark.boundary
def test_accumulating_past_the_maximum_quantity_is_rejected(customer_api, cable):
    """TC-CART-021: the cap applies to the line total, not to one request.

    Two legal adds that together exceed the cap must still be refused,
    and the cart must be left at its last valid state.
    """
    assert_status(customer_api.add_to_cart(cable["id"], quantity=6), 201, "first add of 6")

    response = customer_api.add_to_cart(cable["id"], quantity=6)
    assert response.status == 422, (
        f"6 + 6 = 12 exceeds the maximum of 10 but the API returned {response.status}."
    )
    assert customer_api.get_cart().json()["items"][0]["quantity"] == 6, (
        "the rejected add must leave the previous quantity untouched"
    )


@pytest.mark.boundary
def test_ordering_exactly_the_remaining_stock_is_allowed(customer_api, db):
    """TC-CART-022: availability is inclusive at the boundary."""
    product = customer_api.find_product_by_sku(builders.LOW_STOCK_SKU)

    with temporarily_set_stock(db, builders.LOW_STOCK_SKU, 4):
        response = customer_api.add_to_cart(product["id"], quantity=4)

        assert response.status == 201, (
            f"Requesting exactly the 4 units in stock was rejected with {response.status}: {response.detail}"
        )


@pytest.mark.boundary
@pytest.mark.negative
def test_ordering_one_more_than_the_remaining_stock_is_rejected(customer_api, db):
    """TC-CART-023: the oversell case, one unit past the bound."""
    product = customer_api.find_product_by_sku(builders.LOW_STOCK_SKU)

    with temporarily_set_stock(db, builders.LOW_STOCK_SKU, 4):
        response = customer_api.add_to_cart(product["id"], quantity=5)

        assert response.status == 409, (
            f"Requesting 5 units when only 4 are in stock returned {response.status}. "
            "Overselling stock is a revenue and fulfilment defect."
        )
        assert "stock" in response.detail.lower()


@pytest.mark.negative
def test_an_out_of_stock_product_cannot_be_added(customer_api):
    """TC-CART-024: zero stock is the degenerate case of the same rule."""
    product = customer_api.find_product_by_sku(builders.OUT_OF_STOCK_SKU)
    assert product["stock"] == 0, "fixture assumption: this SKU is seeded with no stock"

    response = customer_api.add_to_cart(product["id"], quantity=1)
    assert_status(response, 409, "add a product with zero stock")


# ----------------------------------------------------------- pricing ---

@pytest.mark.regression
def test_cart_totals_match_the_documented_pricing_rules(customer_api, keyboard, cable):
    """TC-CART-030: subtotal, shipping and tax against an independent oracle."""
    customer_api.add_to_cart(keyboard["id"], quantity=1)
    response = customer_api.add_to_cart(cable["id"], quantity=2)
    assert_status(response, 201, "build a two-line cart")

    expected = expected_totals([(keyboard["price_cents"], 1), (cable["price_cents"], 2)])
    assert response.json()["totals"] == expected.as_dict(), (
        f"Totals disagreed with the documented rules.\n"
        f"  API:      {response.json()['totals']}\n"
        f"  Expected: {expected.as_dict()}"
    )


@pytest.mark.boundary
def test_shipping_is_free_at_exactly_the_threshold(customer_api, db):
    """TC-CART-031: the free-shipping rule is documented as inclusive.

    A cart priced to land exactly on the threshold is the single most
    valuable pricing boundary in the application.
    """
    threshold = builders.FREE_SHIPPING_THRESHOLD_CENTS
    sku = "TP-THRESHOLD-EXACT"
    db.execute("DELETE FROM products WHERE sku = ?", (sku,))
    db.execute(
        "INSERT INTO products (sku, name, description, category, price_cents, stock) VALUES (?,?,?,?,?,?)",
        (sku, "Threshold Probe", "", "test-fixtures", threshold, 50),
    )
    try:
        product = customer_api.find_product_by_sku(sku)
        response = customer_api.add_to_cart(product["id"], quantity=1)

        totals = response.json()["totals"]
        assert totals["subtotal_cents"] == threshold
        assert totals["shipping_cents"] == 0, (
            f"A subtotal of exactly {threshold} cents was charged {totals['shipping_cents']} cents shipping. "
            "The documented rule is free shipping at or above the threshold."
        )
    finally:
        customer_api.clear_cart()
        db.execute("DELETE FROM products WHERE sku = ?", (sku,))


@pytest.mark.boundary
def test_shipping_is_charged_one_cent_below_the_threshold(customer_api, db):
    """TC-CART-032: the other side of the free-shipping boundary."""
    threshold = builders.FREE_SHIPPING_THRESHOLD_CENTS
    sku = "TP-THRESHOLD-UNDER"
    db.execute("DELETE FROM products WHERE sku = ?", (sku,))
    db.execute(
        "INSERT INTO products (sku, name, description, category, price_cents, stock) VALUES (?,?,?,?,?,?)",
        (sku, "Threshold Probe Under", "", "test-fixtures", threshold - 1, 50),
    )
    try:
        product = customer_api.find_product_by_sku(sku)
        totals = customer_api.add_to_cart(product["id"], quantity=1).json()["totals"]

        assert totals["subtotal_cents"] == threshold - 1
        assert totals["shipping_cents"] == builders.SHIPPING_FLAT_CENTS, (
            f"A subtotal one cent below the threshold was charged {totals['shipping_cents']} cents shipping; "
            f"the flat rate of {builders.SHIPPING_FLAT_CENTS} was expected."
        )
    finally:
        customer_api.clear_cart()
        db.execute("DELETE FROM products WHERE sku = ?", (sku,))


@pytest.mark.regression
def test_an_empty_cart_has_zero_totals_and_no_shipping(customer_api):
    """TC-CART-033: the empty state must not attract a shipping charge."""
    totals = customer_api.get_cart().json()["totals"]

    assert totals == {
        "subtotal_cents": 0,
        "discount_cents": 0,
        "shipping_cents": 0,
        "tax_cents": 0,
        "total_cents": 0,
    }


# ----------------------------------------------------------- coupons ---

@pytest.mark.regression
def test_a_percentage_coupon_discounts_the_cart_once(customer_api, keyboard):
    """TC-CART-040: the discount applies to the subtotal, exactly once.

    Applying the percentage per line and summing is a real and expensive
    class of pricing defect, so the expected value is computed
    independently rather than mirrored from the application.
    """
    customer_api.add_to_cart(keyboard["id"], quantity=2)

    response = customer_api.apply_coupon(builders.COUPON_TEN)
    assert_status(response, 200, f"apply {builders.COUPON_TEN}")

    expected = expected_totals([(keyboard["price_cents"], 2)], percent_off=10)
    assert response.json()["totals"] == expected.as_dict(), (
        f"Discounted totals were wrong.\n"
        f"  API:      {response.json()['totals']}\n"
        f"  Expected: {expected.as_dict()}"
    )


@pytest.mark.regression
def test_a_coupon_discounts_a_multi_line_cart_only_once(customer_api, keyboard, cable):
    """TC-CART-041: the same rule, on the cart shape that exposes stacking."""
    customer_api.add_to_cart(keyboard["id"], quantity=1)
    customer_api.add_to_cart(cable["id"], quantity=3)

    response = customer_api.apply_coupon(builders.COUPON_TEN)
    assert_status(response, 200, "apply a coupon to a two-line cart")

    lines = [(keyboard["price_cents"], 1), (cable["price_cents"], 3)]
    expected = expected_totals(lines, percent_off=10)
    actual = response.json()["totals"]

    assert actual["discount_cents"] == expected.discount_cents, (
        f"A 10% coupon on a subtotal of {expected.subtotal_cents} cents should discount "
        f"{expected.discount_cents} cents, but {actual['discount_cents']} was applied. "
        "A larger discount indicates the percentage is being applied per line."
    )
    assert actual == expected.as_dict()


@pytest.mark.negative
def test_an_unknown_coupon_code_is_rejected(customer_api, keyboard):
    """TC-CART-042: invented codes must not discount anything."""
    customer_api.add_to_cart(keyboard["id"], quantity=1)

    response = customer_api.apply_coupon("TOTALLY-MADE-UP")
    assert_status(response, 404, "apply a coupon that does not exist")
    assert customer_api.get_cart().json()["totals"]["discount_cents"] == 0


@pytest.mark.negative
def test_an_inactive_coupon_is_rejected(customer_api, keyboard):
    """TC-CART-043: deactivated codes stop working immediately."""
    customer_api.add_to_cart(keyboard["id"], quantity=1)

    response = customer_api.apply_coupon(builders.COUPON_INACTIVE)
    assert_status(response, 404, f"apply the inactive coupon {builders.COUPON_INACTIVE}")


@pytest.mark.boundary
def test_a_coupon_below_its_minimum_spend_is_refused(customer_api, cable):
    """TC-CART-044: minimum-spend gating, just under the bound."""
    customer_api.add_to_cart(cable["id"], quantity=1)  # 999 cents, well under 5000

    response = customer_api.apply_coupon(builders.COUPON_TWENTY)
    assert_status(response, 409, f"apply {builders.COUPON_TWENTY} below its minimum spend")
    assert "minimum" in response.detail.lower()


@pytest.mark.boundary
def test_a_coupon_at_exactly_its_minimum_spend_is_accepted(customer_api, db):
    """TC-CART-045: the inclusive side of the minimum-spend bound."""
    sku = "TP-MINSPEND-EXACT"
    db.execute("DELETE FROM products WHERE sku = ?", (sku,))
    db.execute(
        "INSERT INTO products (sku, name, description, category, price_cents, stock) VALUES (?,?,?,?,?,?)",
        (sku, "Min Spend Probe", "", "test-fixtures", 5000, 50),
    )
    try:
        product = customer_api.find_product_by_sku(sku)
        customer_api.add_to_cart(product["id"], quantity=1)

        response = customer_api.apply_coupon(builders.COUPON_TWENTY)
        assert response.status == 200, (
            f"A subtotal of exactly 5000 cents meets the documented minimum for "
            f"{builders.COUPON_TWENTY} but the coupon was refused with {response.status}: {response.detail}"
        )
        assert response.json()["totals"]["discount_cents"] == 1000
    finally:
        customer_api.clear_cart()
        db.execute("DELETE FROM products WHERE sku = ?", (sku,))


@pytest.mark.regression
def test_clearing_the_cart_also_clears_the_applied_coupon(customer_api, keyboard):
    """TC-CART-046: a coupon must not survive the cart it was applied to."""
    customer_api.add_to_cart(keyboard["id"], quantity=1)
    customer_api.apply_coupon(builders.COUPON_TEN)

    cleared = customer_api.clear_cart()
    assert_status(cleared, 200, "clear the cart")
    assert cleared.json()["coupon"] is None
    assert cleared.json()["totals"]["discount_cents"] == 0
