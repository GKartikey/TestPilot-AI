"""Authentication and authorisation tests.

Covers registration validation, login, token handling and the
authorisation boundary between customers and admins. These are the
highest-risk tests in the suite: an auth failure is a security incident,
not a bug.
"""
from __future__ import annotations

import time

import jwt
import pytest

from framework.data import builders
from framework.utils.helpers import assert_status, unique_email

pytestmark = pytest.mark.api


# --------------------------------------------------------- happy path ---

@pytest.mark.smoke
@pytest.mark.auth
def test_login_with_seeded_customer_returns_a_usable_token(api):
    """TC-AUTH-001: a valid credential pair yields a working bearer token."""
    response = api.login(builders.SEEDED_CUSTOMER["email"], builders.SEEDED_CUSTOMER["password"])

    assert_status(response, 200, "login with seeded customer")
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0
    assert body["user"]["email"] == builders.SEEDED_CUSTOMER["email"]
    assert "password" not in body["user"], "the user object must never carry credential material"

    # The token must actually work, not merely be well-formed.
    api.token = body["access_token"]
    assert_status(api.me(), 200, "GET /api/auth/me with the issued token")


@pytest.mark.regression
@pytest.mark.auth
def test_register_creates_an_account_that_can_immediately_sign_in(api):
    """TC-AUTH-002: registration returns a session, and the account persists."""
    payload = builders.UserBuilder().build()

    created = api.register(**payload)
    assert_status(created, 201, "registration with a valid payload")
    assert created["user"]["email"] == payload["email"].lower()
    assert created["user"]["role"] == "customer", "self-registration must never grant admin"

    fresh = api.anonymous()
    try:
        assert_status(fresh.login(payload["email"], payload["password"]), 200, "login after registration")
    finally:
        fresh.close()


@pytest.mark.regression
@pytest.mark.auth
def test_email_is_normalised_to_lowercase_on_registration_and_login(api):
    """TC-AUTH-003: address casing must not create a second account."""
    email = unique_email("Mixed.Case")
    api.register(email=email.upper(), password="Valid1Password", full_name="Case Tester")

    response = api.login(email.lower(), "Valid1Password")
    assert_status(response, 200, "login using the lowercased form of a mixed-case registration")
    assert response["user"]["email"] == email.lower()


# ----------------------------------------------------------- negative ---

@pytest.mark.negative
@pytest.mark.auth
def test_login_with_a_wrong_password_is_rejected(api):
    """TC-AUTH-010: a wrong password must not authenticate."""
    response = api.login(builders.SEEDED_CUSTOMER["email"], "definitely-not-the-password")

    assert_status(response, 401, "login with an incorrect password")
    assert "access_token" not in (response.json() or {})


@pytest.mark.negative
@pytest.mark.auth
def test_login_error_does_not_reveal_whether_the_email_exists(api):
    """TC-AUTH-011: user enumeration must not be possible via login.

    A different message for "no such user" and "wrong password" hands an
    attacker a free account-discovery oracle.
    """
    unknown = api.login(unique_email("ghost"), "Valid1Password")
    known_bad = api.login(builders.SEEDED_CUSTOMER["email"], "WrongPassword1")

    assert unknown.status == known_bad.status == 401
    assert unknown.detail == known_bad.detail, (
        "The response must be identical for an unknown email and a wrong password. "
        f"Unknown email said {unknown.detail!r}; wrong password said {known_bad.detail!r}."
    )


@pytest.mark.negative
@pytest.mark.auth
def test_deactivated_account_cannot_sign_in(api):
    """TC-AUTH-012: deactivation must take effect at the login boundary."""
    response = api.login(builders.SEEDED_DISABLED["email"], builders.SEEDED_DISABLED["password"])

    assert_status(response, 403, "login as a deactivated account")
    assert "deactivated" in response.detail.lower()


@pytest.mark.negative
@pytest.mark.parametrize("label,email", builders.INVALID_EMAILS, ids=[c[0] for c in builders.INVALID_EMAILS])
def test_registration_rejects_malformed_email_addresses(api, label, email):
    """TC-AUTH-013: every malformed address shape is refused with 422."""
    response = api.register(email=email, password="Valid1Password", full_name="Invalid Email")

    assert response.status == 422, (
        f"Email {email!r} ({label}) should have been rejected with 422 "
        f"but the API returned {response.status}: {response.body!r}"
    )


@pytest.mark.negative
@pytest.mark.parametrize("label,password", builders.WEAK_PASSWORDS, ids=[c[0] for c in builders.WEAK_PASSWORDS])
def test_registration_enforces_the_password_policy(api, label, password):
    """TC-AUTH-014: the documented policy is 8+ chars with a letter and a digit."""
    response = api.register(email=unique_email("weakpw"), password=password, full_name="Weak Password")

    assert response.status == 422, (
        f"Password {password!r} ({label}) violates the policy but was accepted with {response.status}."
    )


@pytest.mark.negative
def test_registering_a_duplicate_email_returns_conflict(api):
    """TC-AUTH-015: the second registration must be a 409, not a silent overwrite."""
    payload = builders.UserBuilder().build()
    assert_status(api.register(**payload), 201, "first registration")

    duplicate = api.register(**payload)
    assert_status(duplicate, 409, "second registration with the same email")


@pytest.mark.negative
@pytest.mark.parametrize("label,payload", builders.SQL_INJECTION_STRINGS, ids=[c[0] for c in builders.SQL_INJECTION_STRINGS])
def test_login_is_not_vulnerable_to_sql_injection_in_the_email_field(api, label, payload):
    """TC-AUTH-016: injection payloads must be treated as ordinary data."""
    response = api.login(payload, "anything")

    assert response.status in (401, 422), (
        f"Injection payload {payload!r} ({label}) returned {response.status}. "
        "It must be rejected as a credential failure, never processed as SQL."
    )
    assert "access_token" not in (response.json() or {})

    # The table must still be there afterwards.
    assert_status(
        api.login(builders.SEEDED_CUSTOMER["email"], builders.SEEDED_CUSTOMER["password"]),
        200,
        "login still works after the injection attempt",
    )


# ------------------------------------------------------ token handling ---

@pytest.mark.negative
@pytest.mark.auth
def test_protected_endpoint_rejects_a_request_with_no_credentials(api):
    """TC-AUTH-020: /api/auth/me must not be anonymous."""
    response = api.get("/api/auth/me", authenticate=False)
    assert_status(response, 401, "GET /api/auth/me with no Authorization header")


@pytest.mark.negative
@pytest.mark.auth
@pytest.mark.parametrize("label,token", builders.MALFORMED_TOKENS, ids=[c[0] for c in builders.MALFORMED_TOKENS])
def test_malformed_tokens_are_rejected(api, label, token):
    """TC-AUTH-021: the token parser must fail closed on every bad shape."""
    # Stripped so the empty-token case sends a bare "Bearer" rather than a
    # header with trailing whitespace, which the HTTP client refuses to
    # transmit at all. Either way the server receives no credential.
    header = f"Bearer {token}".strip()

    response = api.get("/api/auth/me", headers={"Authorization": header}, authenticate=False)

    assert response.status == 401, (
        f"Token {label} ({token[:32]!r}) returned {response.status}; it must be rejected with 401."
    )


@pytest.mark.negative
@pytest.mark.auth
def test_a_token_signed_with_the_wrong_secret_is_rejected(api):
    """TC-AUTH-022: signature verification must not be skipped."""
    forged = jwt.encode(
        {"sub": "1", "role": "admin", "iss": "shopnest", "exp": int(time.time()) + 3600},
        "an-attacker-chosen-secret",
        algorithm="HS256",
    )
    response = api.get("/api/auth/me", headers={"Authorization": f"Bearer {forged}"}, authenticate=False)

    assert_status(response, 401, "a token signed with a secret the server does not know")


@pytest.mark.negative
@pytest.mark.auth
def test_an_expired_token_is_rejected(api):
    """TC-AUTH-023: expiry must actually be enforced.

    The token is minted with the server's own secret so that the *only*
    reason to reject it is the expiry claim.
    """
    from shopnest.config import settings

    expired = jwt.encode(
        {
            "sub": "1",
            "role": "customer",
            "iss": "shopnest",
            "iat": int(time.time()) - 7200,
            "exp": int(time.time()) - 3600,
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    response = api.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"}, authenticate=False)

    assert response.status == 401, (
        f"An expired token was accepted with status {response.status}. "
        "Expiry is the only control that limits the blast radius of a leaked token."
    )


@pytest.mark.negative
@pytest.mark.auth
def test_authorization_header_without_the_bearer_scheme_is_rejected(api):
    """TC-AUTH-024: the scheme is part of the contract."""
    token = api.login(builders.SEEDED_CUSTOMER["email"], builders.SEEDED_CUSTOMER["password"])["access_token"]

    response = api.get("/api/auth/me", headers={"Authorization": token}, authenticate=False)
    assert_status(response, 401, "a raw token with no 'Bearer ' prefix")


# ------------------------------------------------------- authorisation ---

@pytest.mark.regression
@pytest.mark.auth
def test_a_customer_cannot_create_products(customer_api):
    """TC-AUTH-030: role enforcement on a write endpoint."""
    response = customer_api.create_product(**builders.ProductBuilder().build())

    assert_status(response, 403, "product creation as a customer")
    assert "admin" in response.detail.lower()


@pytest.mark.regression
@pytest.mark.auth
def test_an_admin_can_create_products(admin_api):
    """TC-AUTH-031: the positive half of the same authorisation rule."""
    payload = builders.ProductBuilder().build()

    response = admin_api.create_product(**payload)
    assert_status(response, 201, "product creation as an admin")
    assert response["sku"] == payload["sku"]


@pytest.mark.regression
@pytest.mark.auth
def test_a_customer_cannot_read_another_customers_order(customer_api, second_customer_api):
    """TC-AUTH-032: object-level authorisation on order retrieval.

    This is the check that catches the classic IDOR: the endpoint must
    not serve a record just because the caller guessed its id.
    """
    product = customer_api.find_product_by_sku(builders.CABLE_SKU)
    placed = customer_api.place_order_with(product["id"], quantity=1)
    assert_status(placed, 201, "the first customer places an order")
    order_id = placed["id"]

    response = second_customer_api.get_order(order_id)
    assert response.status == 404, (
        f"A second customer read order {order_id} with status {response.status}. "
        "Another customer's order must not be reachable by id."
    )


@pytest.mark.regression
@pytest.mark.auth
def test_order_history_is_scoped_to_the_calling_customer(customer_api, second_customer_api):
    """TC-AUTH-033: list endpoints must be tenant-filtered."""
    cable = customer_api.find_product_by_sku(builders.CABLE_SKU)
    first_order = customer_api.place_order_with(cable["id"], quantity=1)
    assert_status(first_order, 201, "first customer places an order")

    listed = second_customer_api.list_orders()
    assert_status(listed, 200, "second customer lists their own orders")

    numbers = [order["order_number"] for order in listed.json()]
    assert first_order["order_number"] not in numbers, (
        "The second customer's order history contained an order belonging to the first customer. "
        f"Leaked order: {first_order['order_number']}."
    )
