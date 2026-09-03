"""Cart and order pricing rules.

Kept in one module so the API, the UI and the SQL validation tests all
agree on a single source of truth for money maths. All amounts are
integer cents; floats never touch a total.
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import settings


@dataclass(frozen=True)
class Line:
    product_id: int
    unit_price_cents: int
    quantity: int

    @property
    def line_total_cents(self) -> int:
        return self.unit_price_cents * self.quantity


@dataclass(frozen=True)
class Totals:
    subtotal_cents: int
    discount_cents: int
    shipping_cents: int
    tax_cents: int
    total_cents: int

    def as_dict(self) -> dict[str, int]:
        return {
            "subtotal_cents": self.subtotal_cents,
            "discount_cents": self.discount_cents,
            "shipping_cents": self.shipping_cents,
            "tax_cents": self.tax_cents,
            "total_cents": self.total_cents,
        }


def compute_totals(lines: list[Line], percent_off: int = 0, min_spend_cents: int = 0) -> Totals:
    """Subtotal -> discount -> shipping -> tax -> total.

    Discount applies to the cart subtotal exactly once. Shipping is free
    once the discounted subtotal reaches the threshold. Tax is charged on
    the discounted subtotal only, never on shipping.
    """
    subtotal = sum(line.line_total_cents for line in lines)

    discount = 0
    if percent_off and subtotal >= min_spend_cents:
        if settings.fault_enabled("coupon_stacking"):
            # FAULT: discount is computed per line and summed, which for a
            # multi-line cart over-discounts relative to the stated rule.
            discount = sum((line.line_total_cents * percent_off) // 100 for line in lines) * max(len(lines), 1)
        else:
            discount = (subtotal * percent_off) // 100
    discount = min(discount, subtotal)

    discounted = subtotal - discount
    threshold = int(round(settings.free_shipping_threshold * 100))
    shipping = 0 if (discounted >= threshold or discounted == 0) else int(round(settings.shipping_flat_rate * 100))
    tax = int(round(discounted * settings.tax_rate))
    total = discounted + shipping + tax
    return Totals(subtotal, discount, shipping, tax, total)


def has_sufficient_stock(available: int, requested: int) -> bool:
    if settings.fault_enabled("stock_oversell"):
        # FAULT: off-by-one lets a customer buy one more unit than exists.
        return available + 1 >= requested
    return available >= requested
