"""Login and registration page objects."""
from __future__ import annotations

from playwright.sync_api import Locator

from .base_page import BasePage


class LoginPage(BasePage):
    path = "/login"
    page_name = "login"

    @property
    def email_input(self) -> Locator:
        return self.testid("email-input")

    @property
    def password_input(self) -> Locator:
        return self.testid("password-input")

    @property
    def submit_button(self) -> Locator:
        return self.testid("login-submit")

    def fill_credentials(self, email: str, password: str) -> "LoginPage":
        self.email_input.fill(email)
        self.password_input.fill(password)
        return self

    def submit(self) -> "LoginPage":
        self.submit_button.click()
        return self

    def login(self, email: str, password: str) -> "LoginPage":
        """Fill and submit. Does not assert; the caller decides what
        success looks like, so the same method serves the happy path and
        the invalid-credentials test."""
        return self.fill_credentials(email, password).submit()

    def login_expecting_success(self, email: str, password: str) -> "ProductsPage":
        from .products_page import ProductsPage

        self.login(email, password)
        self.page.wait_for_url(f"{self.base_url}/products", timeout=10_000)
        products = ProductsPage(self.page, self.base_url)
        products.wait_until_ready()
        return products

    def go_to_register(self) -> "RegisterPage":
        self.testid("register-link").click()
        return RegisterPage(self.page, self.base_url).wait_until_ready()

    @property
    def error_text(self) -> str:
        return self.flash_message

    def wait_for_error(self, timeout: float = 5_000) -> str:
        return self.wait_for_flash(timeout)


class RegisterPage(BasePage):
    path = "/register"
    page_name = "register"

    @property
    def name_input(self) -> Locator:
        return self.testid("name-input")

    @property
    def email_input(self) -> Locator:
        return self.testid("email-input")

    @property
    def password_input(self) -> Locator:
        return self.testid("password-input")

    def register(self, full_name: str, email: str, password: str) -> "RegisterPage":
        self.name_input.fill(full_name)
        self.email_input.fill(email)
        self.password_input.fill(password)
        self.testid("register-submit").click()
        return self

    def wait_for_error(self, timeout: float = 5_000) -> str:
        return self.wait_for_flash(timeout)
