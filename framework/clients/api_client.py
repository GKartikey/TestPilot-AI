"""HTTP client for the ShopNest API.

One client per test session per identity. It exists so that tests read
like intent (`client.add_to_cart(product_id=3, quantity=2)`) rather than
like plumbing, and so that every request is logged for the failure
report without each test having to remember to do it.

Design notes:
  * The client never asserts. Tests decide what a correct status is;
    the client only reports what happened.
  * Every call is recorded in `history`, which the pytest plugin attaches
    to failing results so a reviewer can see the exact conversation.
  * Credentials are redacted before anything is logged.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Iterator

import httpx

_REDACT_KEYS = {"password", "access_token", "token", "authorization", "api_key"}
_REDACTED = "***redacted***"


def _redact(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {k: (_REDACTED if k.lower() in _REDACT_KEYS else _redact(v)) for k, v in payload.items()}
    if isinstance(payload, list):
        return [_redact(item) for item in payload]
    return payload


@dataclass
class Interaction:
    """One request/response pair, safe to embed in a report."""

    method: str
    url: str
    status: int
    duration_ms: int
    request_body: Any = None
    response_body: Any = None
    authenticated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "url": self.url,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "authenticated": self.authenticated,
            "request": _redact(self.request_body),
            "response": _redact(self.response_body),
        }


class ApiResponse:
    """A thin wrapper that keeps the raw response but is nicer to assert on."""

    def __init__(self, raw: httpx.Response, elapsed_ms: int) -> None:
        self.raw = raw
        self.status = raw.status_code
        self.elapsed_ms = elapsed_ms
        self.headers = raw.headers
        try:
            self._body = raw.json() if raw.content else None
        except (json.JSONDecodeError, ValueError):
            self._body = raw.text

    @property
    def body(self) -> Any:
        return self._body

    @property
    def detail(self) -> str:
        if isinstance(self._body, dict):
            return str(self._body.get("detail", ""))
        return str(self._body or "")

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def json(self) -> Any:
        return self._body

    def __getitem__(self, key: str) -> Any:
        if not isinstance(self._body, dict):
            raise TypeError(f"Response body is {type(self._body).__name__}, not an object")
        return self._body[key]

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ApiResponse {self.status} {self.raw.request.method} {self.raw.request.url.path}>"


@dataclass
class ShopNestClient:
    """Typed access to every ShopNest endpoint the suite exercises."""

    base_url: str
    timeout: float = 15.0
    token: str | None = None
    history: list[Interaction] = field(default_factory=list)
    _client: httpx.Client = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._client = httpx.Client(base_url=self.base_url.rstrip("/"), timeout=self.timeout)

    # -- plumbing ------------------------------------------------------
    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ShopNestClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _headers(self, extra: dict[str, str] | None = None, authenticate: bool = True) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if authenticate and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        headers.update(extra or {})
        return headers

    def request(
        self,
        method: str,
        path: str,
        json_body: Any = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        authenticate: bool = True,
        content: bytes | str | None = None,
    ) -> ApiResponse:
        started = time.perf_counter()
        raw = self._client.request(
            method,
            path,
            json=json_body,
            params=params,
            content=content,
            headers=self._headers(headers, authenticate),
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        response = ApiResponse(raw, elapsed_ms)
        self.history.append(
            Interaction(
                method=method.upper(),
                url=str(raw.request.url),
                status=response.status,
                duration_ms=elapsed_ms,
                request_body=json_body,
                response_body=response.body if isinstance(response.body, (dict, list)) else str(response.body)[:500],
                authenticated=bool(authenticate and self.token),
            )
        )
        return response

    def get(self, path: str, **kwargs: Any) -> ApiResponse:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, json_body: Any = None, **kwargs: Any) -> ApiResponse:
        return self.request("POST", path, json_body=json_body, **kwargs)

    def patch(self, path: str, json_body: Any = None, **kwargs: Any) -> ApiResponse:
        return self.request("PATCH", path, json_body=json_body, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> ApiResponse:
        return self.request("DELETE", path, **kwargs)

    def interactions(self) -> list[dict[str, Any]]:
        return [i.to_dict() for i in self.history]

    def clear_history(self) -> None:
        self.history.clear()

    # -- health --------------------------------------------------------
    def health(self) -> ApiResponse:
        return self.get("/health", authenticate=False)

    # -- auth ----------------------------------------------------------
    def register(self, email: str, password: str, full_name: str = "Test User") -> ApiResponse:
        return self.post(
            "/api/auth/register",
            {"email": email, "password": password, "full_name": full_name},
            authenticate=False,
        )

    def login(self, email: str, password: str) -> ApiResponse:
        return self.post("/api/auth/login", {"email": email, "password": password}, authenticate=False)

    def authenticate(self, email: str, password: str) -> "ShopNestClient":
        """Log in and keep the token. Raises if the credentials are wrong,
        because a fixture that cannot authenticate is a setup error, not
        a test failure."""
        response = self.login(email, password)
        if not response.ok:
            raise RuntimeError(f"Could not authenticate {email}: {response.status} {response.detail}")
        self.token = response["access_token"]
        return self

    def me(self) -> ApiResponse:
        return self.get("/api/auth/me")

    def with_token(self, token: str | None) -> "ShopNestClient":
        self.token = token
        return self

    def anonymous(self) -> "ShopNestClient":
        """A second client against the same host with no credentials."""
        return ShopNestClient(base_url=self.base_url, timeout=self.timeout)

    # -- catalogue -----------------------------------------------------
    def list_products(self, **params: Any) -> ApiResponse:
        return self.get("/api/products", params={k: v for k, v in params.items() if v is not None}, authenticate=False)

    def get_product(self, product_id: int) -> ApiResponse:
        return self.get(f"/api/products/{product_id}", authenticate=False)

    def categories(self) -> ApiResponse:
        return self.get("/api/products/categories", authenticate=False)

    def create_product(self, **payload: Any) -> ApiResponse:
        return self.post("/api/products", payload)

    def find_product_by_sku(self, sku: str) -> dict[str, Any] | None:
        response = self.list_products(q=sku, page_size=100)
        if not response.ok:
            return None
        return next((item for item in response["items"] if item["sku"] == sku), None)

    # -- cart ----------------------------------------------------------
    def get_cart(self) -> ApiResponse:
        return self.get("/api/cart")

    def add_to_cart(self, product_id: int, quantity: int = 1) -> ApiResponse:
        return self.post("/api/cart/items", {"product_id": product_id, "quantity": quantity})

    def update_cart_item(self, product_id: int, quantity: int) -> ApiResponse:
        return self.patch(f"/api/cart/items/{product_id}", {"product_id": product_id, "quantity": quantity})

    def remove_cart_item(self, product_id: int) -> ApiResponse:
        return self.delete(f"/api/cart/items/{product_id}")

    def apply_coupon(self, code: str) -> ApiResponse:
        return self.post("/api/cart/coupon", {"code": code})

    def clear_cart(self) -> ApiResponse:
        return self.delete("/api/cart")

    # -- orders --------------------------------------------------------
    def checkout(self) -> ApiResponse:
        return self.post("/api/orders")

    def list_orders(self) -> ApiResponse:
        return self.get("/api/orders")

    def get_order(self, order_id: int) -> ApiResponse:
        return self.get(f"/api/orders/{order_id}")

    def cancel_order(self, order_id: int) -> ApiResponse:
        return self.post(f"/api/orders/{order_id}/cancel")

    # -- convenience ---------------------------------------------------
    def place_order_with(self, product_id: int, quantity: int = 1, coupon: str | None = None) -> ApiResponse:
        """Set up a whole checkout in one call, for tests whose subject is
        the *order*, not the steps that build it."""
        self.clear_cart()
        self.add_to_cart(product_id, quantity)
        if coupon:
            self.apply_coupon(coupon)
        return self.checkout()

    def iter_products(self) -> Iterator[dict[str, Any]]:
        page = 1
        while True:
            response = self.list_products(page=page, page_size=50)
            if not response.ok:
                return
            body = response.json()
            yield from body["items"]
            if page >= (body["pages"] or 1):
                return
            page += 1
