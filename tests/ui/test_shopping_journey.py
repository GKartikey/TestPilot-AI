"""End-to-end browser tests for the ShopNest storefront.

These are deliberately few. UI tests are the slowest and most brittle
layer of the pyramid, so they cover journeys that only a browser can
prove -- form submission, navigation, DOM rendering of prices -- while
the exhaustive permutations live in the API suite.

Every test here goes through a page object; no test contains a raw
selector.
"""
from __future__ import annotations

import pytest

from framework.data import builders
from framework.pages.cart_page import CartPage
from framework.utils.helpers import expected_totals, unique_email

pytestmark = pytest.mark.ui


# ------------------------------------------------------------- smoke ---

@pytest.mark.smoke
def test_the_storefront_loads_and_shows_the_catalogue(products_page):
    """TC-UI-001: the application renders at all."""
    products_page.open()

    assert products_page.title_text == "Catalogue"
    assert products_page.cards.count() >= 10, (
        f"the catalogue rendered only {products_page.cards.count()} products"
    )
    assert products_page.result_count >= 10


@pytest.mark.smoke
@pytest.mark.auth
def test_a_customer_can_sign_in_through_the_login_form(login_page):
    """TC-UI-002: the real login form, not an injected token."""
    login_page.open()

    products = login_page.login_expecting_success(
        builders.SEEDED_CUSTOMER["email"], builders.SEEDED_CUSTOMER["password"]
    )

    assert products.current_path == "/products"
    assert products.signed_in_email == builders.SEEDED_CUSTOMER["email"]


@pytest.mark.smoke
def test_a_customer_can_complete_a_purchase_in_the_browser(signed_in_products_page, db):
    """TC-UI-003: the critical revenue journey, driven through the UI.

    Browse -> add -> review cart -> checkout -> see confirmation. This is
    the one test that, if it goes red, blocks a release on its own.
    """
    products = signed_in_products_page
    keyboard_price = products.product_details(builders.KEYBOARD_SKU)["price_cents"]

    products.add_to_cart(builders.KEYBOARD_SKU)
    cart = products.go_to_cart()

    items = cart.line_items()
    assert len(items) == 1
    assert items[0]["sku"] == builders.KEYBOARD_SKU
    assert items[0]["unit_price_cents"] == keyboard_price

    orders = cart.checkout()

    assert "has been placed" in orders.confirmation_text
    assert orders.has_orders()
    placed = orders.latest_order()
    assert placed["status"] == "PLACED"
    assert placed["total_cents"] == expected_totals([(keyboard_price, 1)]).total_cents

    # The browser said the order exists; SQL confirms it was stored.
    stored = db.order_by_number(placed["order_number"])
    assert stored is not None, (
        f"the UI reported order {placed['order_number']} but no such row exists in the database"
    )


# ---------------------------------------------------------- negative ---

@pytest.mark.negative
@pytest.mark.auth
def test_signing_in_with_a_wrong_password_shows_an_error_and_stays_on_the_page(login_page):
    """TC-UI-010: the failure path is handled, not swallowed."""
    login_page.open()

    login_page.login(builders.SEEDED_CUSTOMER["email"], "WrongPassword1")
    error = login_page.wait_for_error()

    assert "invalid" in error.lower(), f"expected an invalid-credentials message, got {error!r}"
    assert login_page.current_path == "/login", "a failed login navigated away from the form"
    assert login_page.signed_in_email is None


@pytest.mark.negative
@pytest.mark.auth
def test_registering_with_a_weak_password_shows_the_policy_error(page, base_url):
    """TC-UI-011: server-side validation surfaces in the browser."""
    from framework.pages.login_page import RegisterPage

    register = RegisterPage(page, base_url).open()
    register.register("Weak Password", unique_email("weak"), "abc")

    error = register.wait_for_error()
    assert "password" in error.lower(), f"expected a password policy message, got {error!r}"
    assert register.current_path == "/register"


@pytest.mark.negative
@pytest.mark.auth
def test_the_cart_page_redirects_an_anonymous_visitor_to_login(page, base_url):
    """TC-UI-012: protected pages are not reachable without a session."""
    cart = CartPage(page, base_url)
    cart.clear_session()
    page.goto(f"{base_url}/cart", wait_until="domcontentloaded")
    page.wait_for_url(f"{base_url}/login", timeout=10_000)

    assert cart.current_path == "/login"


@pytest.mark.negative
def test_an_out_of_stock_product_cannot_be_added_from_the_catalogue(signed_in_products_page):
    """TC-UI-013: the UI disables what the API would refuse."""
    details = signed_in_products_page.product_details(builders.OUT_OF_STOCK_SKU)

    assert details["in_stock"] is False
    assert details["add_button_enabled"] is False, (
        "the add-to-cart button was clickable for a product with no stock"
    )


@pytest.mark.negative
def test_an_invalid_coupon_shows_an_error_and_does_not_discount(signed_in_products_page):
    """TC-UI-014: a rejected coupon leaves the totals alone."""
    cart = signed_in_products_page.add_to_cart(builders.KEYBOARD_SKU).go_to_cart()
    before = cart.totals()

    cart.apply_coupon("NOT-A-REAL-COUPON")
    error = cart.wait_for_flash()

    assert "not valid" in error.lower(), f"expected a coupon rejection message, got {error!r}"
    assert cart.totals() == before, "an invalid coupon changed the cart totals"


# --------------------------------------------------------- functional ---

@pytest.mark.regression
def test_search_narrows_the_catalogue_to_matching_products(products_page):
    """TC-UI-020: search filters the rendered grid."""
    products_page.open()
    total = products_page.result_count

    products_page.search("Keyboard")

    assert products_page.result_count < total
    assert builders.KEYBOARD_SKU in products_page.visible_skus()


@pytest.mark.regression
def test_a_search_with_no_matches_shows_an_empty_state(products_page):
    """TC-UI-021: the empty state is rendered rather than a blank page."""
    products_page.open().search("zzz-nothing-matches-zzz")

    assert products_page.has_no_results()
    assert products_page.result_count == 0
    assert products_page.cards.count() == 0


@pytest.mark.regression
def test_sorting_by_price_reorders_the_grid(products_page):
    """TC-UI-022: the sort control actually reorders what is displayed."""
    products_page.open().sort_by("price")

    prices = products_page.prices_in_order()
    assert prices == sorted(prices), f"the grid was not in ascending price order: {prices}"


@pytest.mark.regression
def test_the_cart_badge_reflects_what_was_added(signed_in_products_page):
    """TC-UI-023: shared chrome updates after an action."""
    products = signed_in_products_page
    products.add_to_cart(builders.KEYBOARD_SKU)
    products.wait_for_flash()

    assert products.cart_count == 1

    products.add_to_cart(builders.MOUSE_SKU)
    products.page.wait_for_function("() => document.querySelector('[data-testid=cart-count]').textContent === '2'")
    assert products.cart_count == 2


@pytest.mark.regression
def test_changing_the_quantity_in_the_cart_updates_the_totals(signed_in_products_page):
    """TC-UI-024: the cart recalculates without a page reload."""
    cart = signed_in_products_page.add_to_cart(builders.MOUSE_SKU).go_to_cart()
    unit_price = cart.line_items()[0]["unit_price_cents"]

    cart.set_quantity(builders.MOUSE_SKU, 3)

    items = cart.line_items()
    assert items[0]["quantity"] == 3
    assert items[0]["line_total_cents"] == unit_price * 3
    assert cart.totals()["subtotal_cents"] == unit_price * 3


@pytest.mark.regression
def test_removing_the_last_item_empties_the_cart_and_disables_checkout(signed_in_products_page):
    """TC-UI-025: the empty state disables the action that cannot succeed."""
    cart = signed_in_products_page.add_to_cart(builders.CABLE_SKU).go_to_cart()

    cart.remove(builders.CABLE_SKU)
    cart.page.wait_for_function(
        "() => document.querySelectorAll('[data-testid=cart-row]').length === 0"
    )

    assert cart.is_empty()
    assert cart.checkout_enabled is False


@pytest.mark.regression
def test_a_valid_coupon_reduces_the_displayed_total(signed_in_products_page):
    """TC-UI-026: the discount the customer is promised is the one shown."""
    cart = signed_in_products_page.add_to_cart(builders.HEADSET_SKU).go_to_cart()
    subtotal = cart.totals()["subtotal_cents"]

    cart.apply_coupon(builders.COUPON_TEN)
    cart.page.wait_for_function(
        "() => document.querySelector('[data-testid=discount]').textContent !== '-$0.00'"
    )

    expected = expected_totals([(subtotal, 1)], percent_off=10)
    assert cart.totals() == expected.as_dict(), (
        f"the browser showed {cart.totals()} but the documented rules give {expected.as_dict()}"
    )
    assert builders.COUPON_TEN in cart.applied_coupon


@pytest.mark.regression
def test_signing_out_clears_the_session(signed_in_products_page):
    """TC-UI-027: sign-out is real, not cosmetic."""
    products = signed_in_products_page
    assert products.signed_in_email is not None

    products.sign_out()

    assert products.current_path == "/login"
    products.page.goto(f"{products.base_url}/cart", wait_until="domcontentloaded")
    products.page.wait_for_url(f"{products.base_url}/login", timeout=10_000)
