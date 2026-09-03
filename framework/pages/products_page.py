"""Catalogue page object."""
from __future__ import annotations

import re
from typing import Any

from playwright.sync_api import Locator

from .base_page import BasePage


class ProductsPage(BasePage):
    path = "/products"
    page_name = "products"

    # -- locators ------------------------------------------------------
    @property
    def cards(self) -> Locator:
        return self.testid("product-card")

    def card_for(self, sku: str) -> Locator:
        return self.page.locator(f'[data-testid="product-card"][data-sku="{sku}"]')

    @property
    def result_count_text(self) -> str:
        return (self.testid("result-count").inner_text() or "").strip()

    @property
    def result_count(self) -> int:
        match = re.search(r"(\d+)", self.result_count_text)
        return int(match.group(1)) if match else 0

    # -- actions -------------------------------------------------------
    def search(self, term: str) -> "ProductsPage":
        self.testid("search-input").fill(term)
        self.testid("search-submit").click()
        return self.wait_until_ready()

    def filter_by_category(self, category: str) -> "ProductsPage":
        self.testid("category-select").select_option(category)
        self.testid("search-submit").click()
        return self.wait_until_ready()

    def sort_by(self, key: str) -> "ProductsPage":
        self.testid("sort-select").select_option(key)
        self.testid("search-submit").click()
        return self.wait_until_ready()

    def add_to_cart(self, sku: str) -> "ProductsPage":
        """Add one unit and wait for the cart to actually reflect it.

        The click fires an asynchronous POST. Returning before that
        request completes lets a caller navigate away mid-flight — the
        cart page then loads without the item and the next action fails
        on a slower machine while passing on a fast one. Waiting on the
        badge, which the page updates only after the POST succeeds, ties
        the method to the outcome rather than to the click.
        """
        card = self.card_for(sku)
        card.wait_for(state="visible", timeout=8_000)
        before = self.cart_count
        self.within(card, "add-to-cart").click()
        self.page.wait_for_function(
            "expected => document.querySelector('[data-testid=cart-count]')"
            "?.textContent.trim() === String(expected)",
            arg=before + 1,
            timeout=10_000,
        )
        return self

    def go_to_cart(self) -> "CartPage":
        from .cart_page import CartPage

        self.testid("nav-cart").click()
        return CartPage(self.page, self.base_url).wait_until_ready()

    # -- state ---------------------------------------------------------
    def visible_skus(self) -> list[str]:
        return [
            self.cards.nth(i).get_attribute("data-sku") or ""
            for i in range(self.cards.count())
        ]

    def product_details(self, sku: str) -> dict[str, Any]:
        card = self.card_for(sku)
        price_text = (self.within(card, "product-price").inner_text() or "").strip()
        stock_text = (self.within(card, "product-stock").inner_text() or "").strip()
        return {
            "sku": sku,
            "name": (self.within(card, "product-name").inner_text() or "").strip(),
            "price_text": price_text,
            "price_cents": int(round(float(price_text.replace("$", "").strip()) * 100)),
            "stock_text": stock_text,
            "in_stock": "Out of stock" not in stock_text,
            "add_button_enabled": self.within(card, "add-to-cart").is_enabled(),
        }

    def prices_in_order(self) -> list[int]:
        prices = []
        for i in range(self.cards.count()):
            text = (self.within(self.cards.nth(i), "product-price").inner_text() or "$0").strip()
            prices.append(int(round(float(text.replace("$", "")) * 100)))
        return prices

    def has_no_results(self) -> bool:
        return self.testid("no-results").count() > 0
