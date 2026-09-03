"""Reusable test utilities.

Small, dependency-free helpers that keep the tests readable. Anything
that shows up in three or more tests belongs here rather than being
copy-pasted.
"""
from __future__ import annotations

import random
import socket
import string
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterator, TypeVar

T = TypeVar("T")


# ------------------------------------------------------------- waits ---

def wait_until(
    condition: Callable[[], bool],
    timeout: float = 10.0,
    interval: float = 0.2,
    message: str = "condition was never met",
) -> None:
    """Poll a condition to a deadline.

    Used only where an event is genuinely asynchronous (a server coming
    up). Never as a substitute for Playwright's auto-waiting: sprinkling
    sleeps through UI tests is how suites become flaky.
    """
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            if condition():
                return
        except Exception as exc:  # the condition itself may not be ready
            last_error = exc
        time.sleep(interval)
    suffix = f" Last error: {last_error}" if last_error else ""
    raise TimeoutError(f"Timed out after {timeout}s: {message}.{suffix}")


def retry(
    action: Callable[[], T],
    attempts: int = 3,
    delay: float = 0.5,
    backoff: float = 2.0,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
) -> T:
    """Retry a genuinely transient action.

    Deliberately *not* used to paper over product flakiness -- only for
    infrastructure operations such as a first connection to a service
    that is still binding its port.
    """
    current_delay = delay
    for attempt in range(1, attempts + 1):
        try:
            return action()
        except retry_on:
            if attempt == attempts:
                raise
            time.sleep(current_delay)
            current_delay *= backoff
    raise AssertionError("unreachable")


def port_is_open(host: str, port: int, timeout: float = 0.5) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


# -------------------------------------------------------------- data ---

def random_suffix(length: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


def unique_email(prefix: str = "qa") -> str:
    """A fresh address per call, so registration tests never collide."""
    return f"{prefix}.{random_suffix()}@testpilot.local"


def unique_sku(prefix: str = "TP") -> str:
    return f"{prefix}-{random_suffix(6).upper()}"


def money(cents: int) -> str:
    return f"${cents / 100:.2f}"


# --------------------------------------------------- pricing oracles ---

@dataclass(frozen=True)
class ExpectedTotals:
    """An independent implementation of the pricing rules.

    The tests must not import the application's own `compute_totals`: an
    oracle that shares code with the thing it checks proves nothing. This
    reimplements the documented rules from the specification instead, so
    a change in the application's maths is caught rather than mirrored.
    """

    subtotal_cents: int
    discount_cents: int
    shipping_cents: int
    tax_cents: int
    total_cents: int

    def as_dict(self) -> dict[str, int]:
        return dict(self.__dict__)


def expected_totals(
    lines: list[tuple[int, int]],
    percent_off: int = 0,
    min_spend_cents: int = 0,
    free_shipping_threshold_cents: int = 5000,
    shipping_flat_cents: int = 499,
    tax_rate: float = 0.08,
) -> ExpectedTotals:
    """`lines` is a list of (unit_price_cents, quantity)."""
    subtotal = sum(price * quantity for price, quantity in lines)
    discount = (subtotal * percent_off) // 100 if percent_off and subtotal >= min_spend_cents else 0
    discount = min(discount, subtotal)
    discounted = subtotal - discount
    shipping = 0 if (discounted >= free_shipping_threshold_cents or discounted == 0) else shipping_flat_cents
    tax = int(round(discounted * tax_rate))
    return ExpectedTotals(subtotal, discount, shipping, tax, discounted + shipping + tax)


# ---------------------------------------------------------- contexts ---

@contextmanager
def temporarily_set_stock(db_client: Any, sku: str, stock: int) -> Iterator[int]:
    """Set a product's stock for the duration of a test, then restore it.

    Boundary tests around availability need an exact stock level, and
    they must not leave the shared database changed for the next test.
    """
    original = db_client.stock_for(sku)
    db_client.set_stock(sku, stock)
    try:
        yield stock
    finally:
        db_client.set_stock(sku, original)


@contextmanager
def timer() -> Iterator[Callable[[], float]]:
    started = time.perf_counter()
    elapsed = 0.0

    def read() -> float:
        return elapsed or (time.perf_counter() - started)

    yield read
    elapsed = time.perf_counter() - started


# ------------------------------------------------------- assertions ----

def assert_status(response: Any, expected: int, context: str = "") -> None:
    """Fail with the response body included.

    A bare `assert response.status == 200` produces a useless report. The
    body is what tells the reader whether it was validation, auth or a
    genuine server error -- and it is what the AI failure analysis reads.
    """
    if response.status != expected:
        where = f" [{context}]" if context else ""
        raise AssertionError(
            f"Expected HTTP {expected} but got {response.status}{where}. "
            f"Response body: {response.body!r}"
        )


def assert_subset(expected: dict[str, Any], actual: dict[str, Any], context: str = "") -> None:
    """Every key in `expected` must match in `actual`, ignoring extras."""
    mismatches = {
        key: {"expected": value, "actual": actual.get(key)}
        for key, value in expected.items()
        if actual.get(key) != value
    }
    if mismatches:
        where = f" [{context}]" if context else ""
        raise AssertionError(f"Response did not match expected fields{where}: {mismatches}")
