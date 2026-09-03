"""Base class for every page object.

Rules the whole page layer follows:

  * Locators are `data-testid` based. CSS class names and text change
    with copy edits; test ids are a contract.
  * No page object contains an assertion. Pages expose state; tests
    decide what is correct. That keeps a page reusable by a positive
    test, a negative test and a boundary test alike.
  * No page object sleeps. Waiting is expressed as waiting for a
    condition -- Playwright's auto-waiting plus the app's own
    `data-ready` flag -- which is what keeps this suite deterministic.
"""
from __future__ import annotations

from typing import Any

from playwright.sync_api import Locator, Page, expect


class BasePage:
    #: Overridden by each page. Used by `open()` and by `is_displayed()`.
    path: str = "/"
    page_name: str = "base"

    def __init__(self, page: Page, base_url: str) -> None:
        self.page = page
        self.base_url = base_url.rstrip("/")

    # -- navigation ----------------------------------------------------
    def open(self, query: str = "") -> "BasePage":
        self.page.goto(f"{self.base_url}{self.path}{query}", wait_until="domcontentloaded")
        self.wait_until_ready()
        return self

    def wait_until_ready(self, timeout: float | None = None) -> "BasePage":
        """Wait for the page's own readiness flag.

        The application sets `data-ready="true"` on <body> once its
        initial fetches have rendered. Waiting on that instead of on a
        network-idle heuristic is what removes the flake.
        """
        self.page.wait_for_selector(
            f'body[data-page="{self.page_name}"][data-ready="true"]',
            timeout=timeout or 10_000,
            state="attached",
        )
        return self

    def is_displayed(self) -> bool:
        return self.page.locator(f'body[data-page="{self.page_name}"]').count() > 0

    @property
    def current_path(self) -> str:
        from urllib.parse import urlparse

        return urlparse(self.page.url).path

    # -- locators ------------------------------------------------------
    def testid(self, name: str) -> Locator:
        return self.page.locator(f'[data-testid="{name}"]')

    def within(self, scope: Locator, name: str) -> Locator:
        return scope.locator(f'[data-testid="{name}"]')

    # -- shared chrome -------------------------------------------------
    @property
    def title_text(self) -> str:
        return (self.testid("page-title").inner_text() or "").strip()

    @property
    def flash_message(self) -> str:
        flash = self.testid("flash")
        if flash.count() == 0 or flash.is_hidden():
            return ""
        return (flash.inner_text() or "").strip()

    def wait_for_flash(self, timeout: float = 5_000) -> str:
        self.testid("flash").wait_for(state="visible", timeout=timeout)
        return self.flash_message

    @property
    def cart_count(self) -> int:
        text = (self.testid("cart-count").inner_text() or "0").strip()
        return int(text or 0)

    @property
    def signed_in_email(self) -> str | None:
        badge = self.testid("nav-user")
        return (badge.inner_text() or "").strip() if badge.count() else None

    def sign_out(self) -> None:
        self.testid("nav-logout").click()
        self.page.wait_for_url(f"{self.base_url}/login", timeout=10_000)

    # -- session -------------------------------------------------------
    def set_session(self, token: str, user: dict[str, Any]) -> "BasePage":
        """Inject an already-issued token.

        UI tests that are not *about* logging in should not pay the cost
        of the login form. Seeding localStorage keeps each test focused
        on the behaviour it actually covers.
        """
        import json

        self.page.goto(f"{self.base_url}/login", wait_until="domcontentloaded")
        self.page.evaluate(
            "([token, user]) => { localStorage.setItem('shopnest.token', token);"
            " localStorage.setItem('shopnest.user', user); }",
            [token, json.dumps(user)],
        )
        return self

    def clear_session(self) -> "BasePage":
        self.page.goto(f"{self.base_url}/login", wait_until="domcontentloaded")
        self.page.evaluate("() => localStorage.clear()")
        return self

    # -- assertions helpers (used by tests, not by pages) --------------
    def expect_visible(self, name: str, timeout: float = 5_000) -> None:
        expect(self.testid(name)).to_be_visible(timeout=timeout)

    def screenshot(self, path: str, full_page: bool = True) -> str:
        self.page.screenshot(path=path, full_page=full_page)
        return path
