"""Cart and order-history page objects."""
from __future__ import annotations

from typing import Any

from playwright.sync_api import Locator

from .base_page import BasePage


def _cents(text: str) -> int:
    """'-$12.34' -> 1234. Totals are compared in cents, never in floats."""
    cleaned = (text or "").replace("$", "").replace("-", "").strip()
    return int(round(float(cleaned or 0) * 100))


class CartPage(BasePage):
    path = "/cart"
    page_name = "cart"

    @property
    def rows(self) -> Locator:
        return self.testid("cart-row")

    def row_for(self, sku: str) -> Locator:
        return self.page.locator(f'[data-testid="cart-row"][data-sku="{sku}"]')

    def is_empty(self) -> bool:
        return self.rows.count() == 0

    def line_items(self) -> list[dict[str, Any]]:
        items = []
        for i in range(self.rows.count()):
            row = self.rows.nth(i)
            items.append(
                {
                    "sku": row.get_attribute("data-sku"),
                    "name": (self.within(row, "row-name").inner_text() or "").split("\n")[0].strip(),
                    "unit_price_cents": _cents(self.within(row, "row-unit-price").inner_text()),
                    "quantity": int(self.within(row, "row-qty").input_value() or 0),
                    "line_total_cents": _cents(self.within(row, "row-line-total").inner_text()),
                }
            )
        return items

    def totals(self) -> dict[str, int]:
        return {
            "subtotal_cents": _cents(self.testid("subtotal").inner_text()),
            "discount_cents": _cents(self.testid("discount").inner_text()),
            "shipping_cents": _cents(self.testid("shipping").inner_text()),
            "tax_cents": _cents(self.testid("tax").inner_text()),
            "total_cents": _cents(self.testid("total").inner_text()),
        }

    # -- actions -------------------------------------------------------
    def set_quantity(self, sku: str, quantity: int) -> "CartPage":
        field = self.within(self.row_for(sku), "row-qty")
        field.fill(str(quantity))
        field.press("Enter")
        field.blur()
        self.page.wait_for_timeout(150)  # let the PATCH round-trip settle
        return self

    def remove(self, sku: str) -> "CartPage":
        self.within(self.row_for(sku), "row-remove").click()
        return self

    def apply_coupon(self, code: str) -> "CartPage":
        self.testid("coupon-input").fill(code)
        self.testid("apply-coupon").click()
        return self

    @property
    def applied_coupon(self) -> str:
        note = self.testid("applied-coupon")
        return (note.inner_text() or "").strip() if note.is_visible() else ""

    def checkout(self) -> "OrdersPage":
        self.testid("checkout-button").click()
        self.page.wait_for_url(lambda url: "/orders" in url, timeout=15_000)
        return OrdersPage(self.page, self.base_url).wait_until_ready()

    def checkout_expecting_failure(self) -> str:
        """Click checkout and return the error, without navigating away."""
        self.testid("checkout-button").click()
        return self.wait_for_flash()

    @property
    def checkout_enabled(self) -> bool:
        return self.testid("checkout-button").is_enabled()


class OrdersPage(BasePage):
    path = "/orders"
    page_name = "orders"

    @property
    def cards(self) -> Locator:
        return self.testid("order-card")

    @property
    def confirmation_text(self) -> str:
        banner = self.testid("order-confirmation")
        return (banner.inner_text() or "").strip() if banner.is_visible() else ""

    def order_numbers(self) -> list[str]:
        return [
            self.cards.nth(i).get_attribute("data-order-number") or ""
            for i in range(self.cards.count())
        ]

    def latest_order(self) -> dict[str, Any]:
        card = self.cards.first
        card.wait_for(state="visible", timeout=8_000)
        return {
            "order_number": card.get_attribute("data-order-number"),
            "status": (self.within(card, "order-status").inner_text() or "").strip(),
            "subtotal_cents": _cents(self.within(card, "order-subtotal").inner_text()),
            "discount_cents": _cents(self.within(card, "order-discount").inner_text()),
            "shipping_cents": _cents(self.within(card, "order-shipping").inner_text()),
            "tax_cents": _cents(self.within(card, "order-tax").inner_text()),
            "total_cents": _cents(self.within(card, "order-total").inner_text()),
        }

    def has_orders(self) -> bool:
        return self.cards.count() > 0
