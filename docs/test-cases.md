# Test Cases

Generated from `testcases/*.yaml` by `tools/build_case_catalogue.py`.
Do not edit by hand; edit the YAML and regenerate.

Each case is a reviewable design document: objective, preconditions,
numbered steps, expected result, priority and requirement trace. The
`Automation` column is the trace link to the pytest node that executes
it, which is what lets TestPilot report coverage of the *design* rather
than a raw test count.


## Summary

**125 documented cases** — 119 automated (95.2%), 6 manual only.

| Dimension | Breakdown |
| --- | --- |
| By layer | api: 82, db: 25, ui: 18 |
| By type | boundary: 22, data: 18, functional: 33, integration: 1, negative: 28, security: 17, smoke: 6 |
| By priority | P1: 60, P2: 51, P3: 13, P4: 1 |
| By module | auth: 20, cart: 27, data: 23, orders: 18, products: 20, storefront: 17 |

### Manual cases

Cases deliberately left unautomated, with the reason recorded in the case itself:

| ID | Title | Why manual |
| --- | --- | --- |
| `TC-AUTH-040` | A password reset link expires after a single use | Password reset is implemented (not yet in build 1.4.0) |
| `TC-CART-050` | Two coupons cannot be stacked on one cart | Multiple coupon support is specified (not implemented in build 1.4.0) |
| `TC-PROD-050` | Catalogue images render at every supported breakpoint | Product imagery is implemented (not yet in build 1.4.0) |
| `TC-SQL-040` | A schema migration is reversible on a populated database | A migration tool is adopted (not yet in build 1.4.0) |
| `TC-ORD-040` | Two customers checking out the last unit concurrently | A load-capable environment and a product with exactly one unit in stock |
| `TC-UI-030` | The storefront is operable with a keyboard alone | An accessibility review has defined the expected focus order |

## Module: auth (20 cases)

| ID | Title | Layer | Type | Pri | Requirement | Automation |
| --- | --- | --- | --- | --- | --- | --- |
| `TC-AUTH-001` | A valid credential pair returns a working bearer token | api | functional | P1 | REQ-AUTH-01 | `test_login_with_seeded_customer_returns_a_usable_token` |
| `TC-AUTH-002` | Registration creates an account that can immediately sign in | api | functional | P1 | REQ-AUTH-02 | `test_register_creates_an_account_that_can_immediately_sign_in` |
| `TC-AUTH-003` | Email addresses are normalised to lowercase | api | functional | P2 | REQ-AUTH-03 | `test_email_is_normalised_to_lowercase_on_registration_and_login` |
| `TC-AUTH-010` | Login with a wrong password is rejected | api | negative | P1 | REQ-AUTH-04 | `test_login_with_a_wrong_password_is_rejected` |
| `TC-AUTH-011` | Login responses do not reveal whether an email is registered | api | security | P1 | REQ-SEC-01 | `test_login_error_does_not_reveal_whether_the_email_exists` |
| `TC-AUTH-012` | A deactivated account cannot sign in | api | negative | P1 | REQ-AUTH-05 | `test_deactivated_account_cannot_sign_in` |
| `TC-AUTH-013` | Registration rejects malformed email addresses | api | negative | P2 | REQ-AUTH-06 | `test_registration_rejects_malformed_email_addresses` |
| `TC-AUTH-014` | Registration enforces the password policy | api | boundary | P1 | REQ-AUTH-07 | `test_registration_enforces_the_password_policy` |
| `TC-AUTH-015` | Registering a duplicate email returns a conflict | api | negative | P2 | REQ-AUTH-08 | `test_registering_a_duplicate_email_returns_conflict` |
| `TC-AUTH-016` | Login is not vulnerable to SQL injection in the email field | api | security | P1 | REQ-SEC-02 | `test_login_is_not_vulnerable_to_sql_injection_in_the_email_field` |
| `TC-AUTH-020` | Protected endpoints reject anonymous requests | api | security | P1 | REQ-SEC-03 | `test_protected_endpoint_rejects_a_request_with_no_credentials` |
| `TC-AUTH-021` | Malformed bearer tokens are rejected | api | negative | P1 | REQ-SEC-04 | `test_malformed_tokens_are_rejected` |
| `TC-AUTH-022` | A token signed with the wrong secret is rejected | api | security | P1 | REQ-SEC-05 | `test_a_token_signed_with_the_wrong_secret_is_rejected` |
| `TC-AUTH-023` | An expired token is rejected | api | security | P1 | REQ-SEC-06 | `test_an_expired_token_is_rejected` |
| `TC-AUTH-024` | An Authorization header without the Bearer scheme is rejected | api | negative | P2 | REQ-SEC-07 | `test_authorization_header_without_the_bearer_scheme_is_rejected` |
| `TC-AUTH-030` | A customer cannot create products | api | security | P1 | REQ-SEC-08 | `test_a_customer_cannot_create_products` |
| `TC-AUTH-031` | An administrator can create products | api | functional | P2 | REQ-SEC-08 | `test_an_admin_can_create_products` |
| `TC-AUTH-032` | A customer cannot read another customer's order | api | security | P1 | REQ-SEC-09 | `test_a_customer_cannot_read_another_customers_order` |
| `TC-AUTH-033` | Order history is scoped to the calling customer | api | security | P1 | REQ-SEC-09 | `test_order_history_is_scoped_to_the_calling_customer` |
| `TC-AUTH-040` | A password reset link expires after a single use | api | security | P2 | REQ-AUTH-09 | _manual_ |

<details><summary><strong>TC-AUTH-001</strong> — A valid credential pair returns a working bearer token</summary>

**Objective.** Confirm the primary authentication path issues a token that is accepted by a protected endpoint.

**Preconditions**

- The seeded customer account casey@example.com exists and is active

**Steps**

1. POST /api/auth/login with the seeded customer email and password
2. Read access_token, token_type and expires_in from the response
3. Call GET /api/auth/me using the returned token as a bearer credential

**Expected result.** Login returns 200 with token_type "bearer" and a positive expires_in. The token authenticates GET /api/auth/me, which returns 200 for the same user. No credential material appears anywhere in the response body.

**Test data.** `{'email': 'casey@example.com'}`

**Priority** P1 &middot; **Suites** smoke, regression &middot; **Automation** tests/api/test_auth.py::test_login_with_seeded_customer_returns_a_usable_token

</details>

<details><summary><strong>TC-AUTH-002</strong> — Registration creates an account that can immediately sign in</summary>

**Objective.** Confirm self-registration persists the account and does not grant elevated privileges.

**Preconditions**

- The email address is not already registered

**Steps**

1. POST /api/auth/register with a unique email, a compliant password and a full name
2. Confirm the response status and the role on the returned user
3. POST /api/auth/login with the same credentials from a fresh client

**Expected result.** Registration returns 201 with role "customer". A subsequent login with the same credentials returns 200. Self-registration never yields role "admin".

**Priority** P1 &middot; **Suites** regression &middot; **Automation** tests/api/test_auth.py::test_register_creates_an_account_that_can_immediately_sign_in

</details>

<details><summary><strong>TC-AUTH-003</strong> — Email addresses are normalised to lowercase</summary>

**Objective.** Confirm address casing cannot create a duplicate identity.

**Preconditions**

- The address is unused in any casing

**Steps**

1. Register with the address in upper case
2. Log in using the lower case form of the same address

**Expected result.** Login succeeds and the stored email is the lowercased form.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/api/test_auth.py::test_email_is_normalised_to_lowercase_on_registration_and_login

</details>

<details><summary><strong>TC-AUTH-010</strong> — Login with a wrong password is rejected</summary>

**Objective.** Confirm an incorrect password never authenticates.

**Preconditions**

- The account exists

**Steps**

1. POST /api/auth/login with a valid email and an incorrect password

**Expected result.** The response is 401 and the body contains no access_token.

**Priority** P1 &middot; **Suites** smoke, regression &middot; **Automation** tests/api/test_auth.py::test_login_with_a_wrong_password_is_rejected

</details>

<details><summary><strong>TC-AUTH-011</strong> — Login responses do not reveal whether an email is registered</summary>

**Objective.** Confirm the login endpoint is not a user-enumeration oracle.

**Preconditions**

- One registered email and one unregistered email are available

**Steps**

1. POST /api/auth/login with an unregistered email
2. POST /api/auth/login with a registered email and a wrong password
3. Compare the two status codes and the two detail messages

**Expected result.** Both calls return 401 with an identical detail message. Any difference lets an attacker discover which addresses hold accounts.

**Priority** P1 &middot; **Suites** regression &middot; **Automation** tests/api/test_auth.py::test_login_error_does_not_reveal_whether_the_email_exists

</details>

<details><summary><strong>TC-AUTH-012</strong> — A deactivated account cannot sign in</summary>

**Objective.** Confirm deactivation is enforced at the login boundary.

**Preconditions**

- The seeded account dormant@example.com exists with is_active = 0

**Steps**

1. POST /api/auth/login with the deactivated account's correct credentials

**Expected result.** The response is 403 and the message states the account is deactivated.

**Priority** P1 &middot; **Suites** regression &middot; **Automation** tests/api/test_auth.py::test_deactivated_account_cannot_sign_in

</details>

<details><summary><strong>TC-AUTH-013</strong> — Registration rejects malformed email addresses</summary>

**Objective.** Exercise every malformed address shape against the validator.

**Preconditions**

- None

**Steps**

1. Register with an address missing the @ sign
2. Repeat with a missing domain, missing local part, missing TLD, empty string, whitespace only, an embedded space and a double @

**Expected result.** Every variant returns 422 and no user row is created.

**Test data.** `{'variants': 8}`

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/api/test_auth.py::test_registration_rejects_malformed_email_addresses

</details>

<details><summary><strong>TC-AUTH-014</strong> — Registration enforces the password policy</summary>

**Objective.** Confirm the documented 8-character, letter-and-digit policy at its edges.

**Preconditions**

- None

**Steps**

1. Register with a 3-character password
2. Register with a 7-character password (one below the minimum)
3. Register with letters only, digits only and an empty password

**Expected result.** Every variant returns 422 with a message naming the policy.

**Test data.** `{'minimum_length': 8}`

**Priority** P1 &middot; **Suites** regression &middot; **Automation** tests/api/test_auth.py::test_registration_enforces_the_password_policy

</details>

<details><summary><strong>TC-AUTH-015</strong> — Registering a duplicate email returns a conflict</summary>

**Objective.** Confirm the second registration is refused rather than overwriting the first.

**Preconditions**

- An account already exists for the address

**Steps**

1. Register an address successfully
2. Register the same address a second time

**Expected result.** The second call returns 409 and the original account is unchanged.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/api/test_auth.py::test_registering_a_duplicate_email_returns_conflict

</details>

<details><summary><strong>TC-AUTH-016</strong> — Login is not vulnerable to SQL injection in the email field</summary>

**Objective.** Confirm credentials are bound as parameters, never concatenated into SQL.

**Preconditions**

- The users table contains data worth protecting

**Steps**

1. Attempt login with "' OR '1'='1" as the email
2. Repeat with a comment terminator, a stacked DROP TABLE and a UNION SELECT
3. Log in normally afterwards to confirm the table still exists

**Expected result.** Every payload returns 401 or 422 with no token issued, and a normal login still succeeds afterwards, proving nothing was executed as SQL.

**Priority** P1 &middot; **Suites** regression &middot; **Automation** tests/api/test_auth.py::test_login_is_not_vulnerable_to_sql_injection_in_the_email_field

</details>

<details><summary><strong>TC-AUTH-020</strong> — Protected endpoints reject anonymous requests</summary>

**Objective.** Confirm GET /api/auth/me is not reachable without credentials.

**Preconditions**

- No Authorization header is sent

**Steps**

1. GET /api/auth/me with no Authorization header

**Expected result.** The response is 401.

**Priority** P1 &middot; **Suites** smoke, regression &middot; **Automation** tests/api/test_auth.py::test_protected_endpoint_rejects_a_request_with_no_credentials

</details>

<details><summary><strong>TC-AUTH-021</strong> — Malformed bearer tokens are rejected</summary>

**Objective.** Confirm the token parser fails closed on every malformed shape.

**Preconditions**

- None

**Steps**

1. Send an empty token, a non-JWT string, a Basic scheme header, a two-segment JWT and a JWT with a corrupt signature

**Expected result.** Every variant returns 401.

**Priority** P1 &middot; **Suites** regression &middot; **Automation** tests/api/test_auth.py::test_malformed_tokens_are_rejected

</details>

<details><summary><strong>TC-AUTH-022</strong> — A token signed with the wrong secret is rejected</summary>

**Objective.** Confirm signature verification is performed and cannot be bypassed.

**Preconditions**

- None

**Steps**

1. Mint a structurally valid JWT claiming role "admin", signed with an attacker-chosen secret
2. Call GET /api/auth/me with that token

**Expected result.** The response is 401. A forged signature must never authenticate.

**Priority** P1 &middot; **Suites** regression &middot; **Automation** tests/api/test_auth.py::test_a_token_signed_with_the_wrong_secret_is_rejected

</details>

<details><summary><strong>TC-AUTH-023</strong> — An expired token is rejected</summary>

**Objective.** Confirm the exp claim is verified, limiting the lifetime of a leaked token.

**Preconditions**

- The server's signing secret is known to the test so that expiry is the only reason for rejection

**Steps**

1. Mint a token with the correct secret and an exp one hour in the past
2. Call GET /api/auth/me with that token

**Expected result.** The response is 401.

**Priority** P1 &middot; **Suites** regression &middot; **Automation** tests/api/test_auth.py::test_an_expired_token_is_rejected

</details>

<details><summary><strong>TC-AUTH-024</strong> — An Authorization header without the Bearer scheme is rejected</summary>

**Objective.** Confirm the scheme is part of the contract.

**Preconditions**

- A valid token has been issued

**Steps**

1. Send the raw token as the Authorization header with no "Bearer " prefix

**Expected result.** The response is 401.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/api/test_auth.py::test_authorization_header_without_the_bearer_scheme_is_rejected

</details>

<details><summary><strong>TC-AUTH-030</strong> — A customer cannot create products</summary>

**Objective.** Confirm role-based authorisation on a write endpoint.

**Preconditions**

- A customer session is authenticated

**Steps**

1. POST /api/products with a valid product payload as a customer

**Expected result.** The response is 403 and the message states an administrator role is required.

**Priority** P1 &middot; **Suites** regression &middot; **Automation** tests/api/test_auth.py::test_a_customer_cannot_create_products

</details>

<details><summary><strong>TC-AUTH-031</strong> — An administrator can create products</summary>

**Objective.** The positive half of the same authorisation rule.

**Preconditions**

- An admin session is authenticated

**Steps**

1. POST /api/products with a valid, unique product payload as an admin

**Expected result.** The response is 201 and the created product carries the requested SKU.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/api/test_auth.py::test_an_admin_can_create_products

</details>

<details><summary><strong>TC-AUTH-032</strong> — A customer cannot read another customer's order</summary>

**Objective.** Confirm object-level authorisation prevents an insecure direct object reference.

**Preconditions**

- Two distinct customer accounts exist

**Steps**

1. Customer A places an order and notes its id
2. Customer B calls GET /api/orders/{id} for customer A's order

**Expected result.** The response is 404. Returning 403 would confirm the record exists; returning the order would be a data breach.

**Priority** P1 &middot; **Suites** regression &middot; **Automation** tests/api/test_auth.py::test_a_customer_cannot_read_another_customers_order

</details>

<details><summary><strong>TC-AUTH-033</strong> — Order history is scoped to the calling customer</summary>

**Objective.** Confirm the list endpoint is tenant-filtered.

**Preconditions**

- Two distinct customer accounts exist and customer A has an order

**Steps**

1. Customer A places an order
2. Customer B calls GET /api/orders

**Expected result.** Customer B's history contains none of customer A's order numbers.

**Priority** P1 &middot; **Suites** regression &middot; **Automation** tests/api/test_auth.py::test_order_history_is_scoped_to_the_calling_customer

</details>

<details><summary><strong>TC-AUTH-040</strong> — A password reset link expires after a single use</summary>

**Objective.** Confirm reset tokens are single-use once the feature ships.

**Preconditions**

- Password reset is implemented (not yet in build 1.4.0)

**Steps**

1. Request a password reset for a known account
2. Consume the emailed token to set a new password
3. Attempt to consume the same token a second time

**Expected result.** The second attempt is refused. Tracked as manual until the feature exists.

**Priority** P2 &middot; **Suites** manual &middot; **Automation** manual only

</details>

## Module: cart (27 cases)

| ID | Title | Layer | Type | Pri | Requirement | Automation |
| --- | --- | --- | --- | --- | --- | --- |
| `TC-CART-001` | A product can be added to the cart | api | functional | P1 | REQ-CART-01 | `test_a_product_can_be_added_to_the_cart` |
| `TC-CART-002` | Adding the same product twice accumulates the quantity | api | functional | P2 | REQ-CART-02 | `test_adding_the_same_product_twice_accumulates_the_quantity` |
| `TC-CART-003` | Cart quantity can be updated and the line total follows | api | functional | P2 | REQ-CART-03 | `test_cart_quantity_can_be_updated_and_the_line_total_follows` |
| `TC-CART-004` | Setting a quantity of zero removes the line | api | boundary | P2 | REQ-CART-03 | `test_setting_a_quantity_of_zero_removes_the_line` |
| `TC-CART-005` | A product can be removed from the cart | api | functional | P2 | REQ-CART-04 | `test_a_product_can_be_removed_from_the_cart` |
| `TC-CART-006` | Carts are isolated between customers | api | security | P1 | REQ-SEC-09 | `test_carts_are_isolated_between_customers` |
| `TC-CART-010` | The cart requires authentication | api | security | P1 | REQ-SEC-03 | `test_the_cart_requires_authentication` |
| `TC-CART-011` | Adding a product that does not exist returns not found | api | negative | P2 | REQ-CART-05 | `test_adding_a_product_that_does_not_exist_returns_not_found` |
| `TC-CART-012` | Updating a product that is not in the cart returns not found | api | negative | P3 | REQ-CART-05 | `test_updating_a_product_that_is_not_in_the_cart_returns_not_found` |
| `TC-CART-013` | Removing a product that is not in the cart returns not found | api | negative | P3 | REQ-CART-05 | `test_removing_a_product_that_is_not_in_the_cart_returns_not_found` |
| `TC-CART-020` | Cart quantity boundaries are enforced | api | boundary | P1 | REQ-CART-06 | `test_cart_quantity_boundaries` |
| `TC-CART-021` | Accumulating past the maximum quantity is rejected | api | boundary | P1 | REQ-CART-06 | `test_accumulating_past_the_maximum_quantity_is_rejected` |
| `TC-CART-022` | Ordering exactly the remaining stock is allowed | api | boundary | P1 | REQ-CART-07 | `test_ordering_exactly_the_remaining_stock_is_allowed` |
| `TC-CART-023` | Ordering one more than the remaining stock is rejected | api | boundary | P1 | REQ-CART-07 | `test_ordering_one_more_than_the_remaining_stock_is_rejected` |
| `TC-CART-024` | An out-of-stock product cannot be added | api | negative | P2 | REQ-CART-07 | `test_an_out_of_stock_product_cannot_be_added` |
| `TC-CART-030` | Cart totals match the documented pricing rules | api | functional | P1 | REQ-PRICE-01 | `test_cart_totals_match_the_documented_pricing_rules` |
| `TC-CART-031` | Shipping is free at exactly the free-shipping threshold | api | boundary | P1 | REQ-PRICE-02 | `test_shipping_is_free_at_exactly_the_threshold` |
| `TC-CART-032` | Shipping is charged one cent below the threshold | api | boundary | P1 | REQ-PRICE-02 | `test_shipping_is_charged_one_cent_below_the_threshold` |
| `TC-CART-033` | An empty cart has zero totals and no shipping | api | boundary | P2 | REQ-PRICE-03 | `test_an_empty_cart_has_zero_totals_and_no_shipping` |
| `TC-CART-040` | A percentage coupon discounts the cart once | api | functional | P1 | REQ-PRICE-04 | `test_a_percentage_coupon_discounts_the_cart_once` |
| `TC-CART-041` | A coupon discounts a multi-line cart only once | api | functional | P1 | REQ-PRICE-04 | `test_a_coupon_discounts_a_multi_line_cart_only_once` |
| `TC-CART-042` | An unknown coupon code is rejected | api | negative | P2 | REQ-PRICE-05 | `test_an_unknown_coupon_code_is_rejected` |
| `TC-CART-043` | An inactive coupon is rejected | api | negative | P2 | REQ-PRICE-05 | `test_an_inactive_coupon_is_rejected` |
| `TC-CART-044` | A coupon below its minimum spend is refused | api | boundary | P2 | REQ-PRICE-06 | `test_a_coupon_below_its_minimum_spend_is_refused` |
| `TC-CART-045` | A coupon at exactly its minimum spend is accepted | api | boundary | P1 | REQ-PRICE-06 | `test_a_coupon_at_exactly_its_minimum_spend_is_accepted` |
| `TC-CART-046` | Clearing the cart also clears the applied coupon | api | functional | P3 | REQ-PRICE-07 | `test_clearing_the_cart_also_clears_the_applied_coupon` |
| `TC-CART-050` | Two coupons cannot be stacked on one cart | api | negative | P2 | REQ-PRICE-08 | _manual_ |

<details><summary><strong>TC-CART-001</strong> — A product can be added to the cart</summary>

**Objective.** Confirm the core add-to-cart path.

**Preconditions**

- An authenticated customer with an empty cart

**Steps**

1. POST /api/cart/items with a valid product id and quantity 2

**Expected result.** The response is 201 with a single line for that SKU, quantity 2, and a line total equal to unit price multiplied by 2.

**Priority** P1 &middot; **Suites** smoke, regression &middot; **Automation** tests/api/test_cart.py::test_a_product_can_be_added_to_the_cart

</details>

<details><summary><strong>TC-CART-002</strong> — Adding the same product twice accumulates the quantity</summary>

**Objective.** Confirm a second add merges into the existing line.

**Preconditions**

- An authenticated customer with an empty cart

**Steps**

1. Add 2 units of a product
2. Add 3 more units of the same product

**Expected result.** The cart holds one line for that product with quantity 5.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/api/test_cart.py::test_adding_the_same_product_twice_accumulates_the_quantity

</details>

<details><summary><strong>TC-CART-003</strong> — Cart quantity can be updated and the line total follows</summary>

**Objective.** Confirm PATCH replaces the quantity and recomputes the line.

**Preconditions**

- The product is already in the cart

**Steps**

1. Add 2 units, then PATCH the line to quantity 7

**Expected result.** The line reports quantity 7 and a line total of unit price multiplied by 7.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/api/test_cart.py::test_cart_quantity_can_be_updated_and_the_line_total_follows

</details>

<details><summary><strong>TC-CART-004</strong> — Setting a quantity of zero removes the line</summary>

**Objective.** Confirm zero is treated as removal, as documented, rather than as invalid.

**Preconditions**

- The product is already in the cart

**Steps**

1. Add 3 units, then PATCH the line to quantity 0

**Expected result.** The response is 200 and the cart is empty.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/api/test_cart.py::test_setting_a_quantity_of_zero_removes_the_line

</details>

<details><summary><strong>TC-CART-005</strong> — A product can be removed from the cart</summary>

**Objective.** Confirm removal takes out one line and leaves the others intact.

**Preconditions**

- Two different products are in the cart

**Steps**

1. Add two different products
2. DELETE one of them

**Expected result.** The remaining cart holds only the other product.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/api/test_cart.py::test_a_product_can_be_removed_from_the_cart

</details>

<details><summary><strong>TC-CART-006</strong> — Carts are isolated between customers</summary>

**Objective.** Confirm one customer's basket never leaks into another's.

**Preconditions**

- Two distinct customer accounts exist

**Steps**

1. Customer A adds 4 units of a product
2. Customer B reads their own cart

**Expected result.** Customer B's cart is empty.

**Priority** P1 &middot; **Suites** regression &middot; **Automation** tests/api/test_cart.py::test_carts_are_isolated_between_customers

</details>

<details><summary><strong>TC-CART-010</strong> — The cart requires authentication</summary>

**Objective.** Confirm no cart endpoint is anonymous.

**Preconditions**

- No Authorization header is sent

**Steps**

1. GET /api/cart with no token
2. POST /api/cart/items with no token

**Expected result.** Both calls return 401.

**Priority** P1 &middot; **Suites** smoke, regression &middot; **Automation** tests/api/test_cart.py::test_the_cart_requires_authentication

</details>

<details><summary><strong>TC-CART-011</strong> — Adding a product that does not exist returns not found</summary>

**Objective.** Confirm an unknown product id cannot enter a cart.

**Preconditions**

- An authenticated customer with an empty cart

**Steps**

1. POST /api/cart/items with product id 999999
2. Read the cart back

**Expected result.** The add returns 404 and the cart remains empty.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/api/test_cart.py::test_adding_a_product_that_does_not_exist_returns_not_found

</details>

<details><summary><strong>TC-CART-012</strong> — Updating a product that is not in the cart returns not found</summary>

**Objective.** Confirm PATCH on an absent line does not silently insert it.

**Preconditions**

- The cart is empty

**Steps**

1. PATCH a cart line for a product that was never added

**Expected result.** The response is 404.

**Priority** P3 &middot; **Suites** regression &middot; **Automation** tests/api/test_cart.py::test_updating_a_product_that_is_not_in_the_cart_returns_not_found

</details>

<details><summary><strong>TC-CART-013</strong> — Removing a product that is not in the cart returns not found</summary>

**Objective.** Confirm the documented non-idempotent DELETE behaviour.

**Preconditions**

- The cart is empty

**Steps**

1. DELETE a cart line for a product that was never added

**Expected result.** The response is 404.

**Priority** P3 &middot; **Suites** regression &middot; **Automation** tests/api/test_cart.py::test_removing_a_product_that_is_not_in_the_cart_returns_not_found

</details>

<details><summary><strong>TC-CART-020</strong> — Cart quantity boundaries are enforced</summary>

**Objective.** Cover the full equivalence-partition table for a field documented as 1..10 inclusive.

**Preconditions**

- An authenticated customer with an empty cart and a well-stocked product

**Steps**

1. Attempt quantity 0 and -1 (below the minimum)
2. Attempt quantity 1 and 2 (at and just inside the minimum)
3. Attempt quantity 5 (mid range)
4. Attempt quantity 9 and 10 (just inside and at the maximum)
5. Attempt quantity 11 and 9999 (above the maximum)

**Expected result.** Quantities 1 through 10 are accepted with 201 and stored exactly. Everything outside that range returns 422 and leaves the cart empty.

**Test data.** `{'minimum': 1, 'maximum': 10}`

**Priority** P1 &middot; **Suites** regression &middot; **Automation** tests/api/test_cart.py::test_cart_quantity_boundaries

</details>

<details><summary><strong>TC-CART-021</strong> — Accumulating past the maximum quantity is rejected</summary>

**Objective.** Confirm the cap applies to the line total rather than to a single request.

**Preconditions**

- An authenticated customer with an empty cart

**Steps**

1. Add 6 units (accepted)
2. Add 6 more units, which would total 12
3. Read the cart back

**Expected result.** The second add returns 422 and the line remains at quantity 6.

**Priority** P1 &middot; **Suites** regression &middot; **Automation** tests/api/test_cart.py::test_accumulating_past_the_maximum_quantity_is_rejected

</details>

<details><summary><strong>TC-CART-022</strong> — Ordering exactly the remaining stock is allowed</summary>

**Objective.** Confirm availability is inclusive at its boundary.

**Preconditions**

- A product's stock is set to exactly 4 for the duration of the test

**Steps**

1. Add 4 units of that product

**Expected result.** The response is 201.

**Priority** P1 &middot; **Suites** regression &middot; **Automation** tests/api/test_cart.py::test_ordering_exactly_the_remaining_stock_is_allowed

</details>

<details><summary><strong>TC-CART-023</strong> — Ordering one more than the remaining stock is rejected</summary>

**Objective.** Confirm the oversell case one unit past the boundary is refused.

**Preconditions**

- A product's stock is set to exactly 4 for the duration of the test

**Steps**

1. Add 5 units of that product

**Expected result.** The response is 409 and the message names the remaining stock.

**Priority** P1 &middot; **Suites** regression &middot; **Automation** tests/api/test_cart.py::test_ordering_one_more_than_the_remaining_stock_is_rejected

</details>

<details><summary><strong>TC-CART-024</strong> — An out-of-stock product cannot be added</summary>

**Objective.** Confirm the degenerate case of the availability rule.

**Preconditions**

- A seeded product has zero stock

**Steps**

1. Add 1 unit of the zero-stock product

**Expected result.** The response is 409.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/api/test_cart.py::test_an_out_of_stock_product_cannot_be_added

</details>

<details><summary><strong>TC-CART-030</strong> — Cart totals match the documented pricing rules</summary>

**Objective.** Verify subtotal, shipping and tax against an independent oracle.

**Preconditions**

- An authenticated customer with an empty cart

**Steps**

1. Build a two-line cart
2. Compare every total against values computed from the documented rules

**Expected result.** Subtotal equals the sum of the lines, shipping follows the free-shipping rule, tax is 8% of the discounted subtotal and the total is the sum of all four components.

**Priority** P1 &middot; **Suites** regression &middot; **Automation** tests/api/test_cart.py::test_cart_totals_match_the_documented_pricing_rules

</details>

<details><summary><strong>TC-CART-031</strong> — Shipping is free at exactly the free-shipping threshold</summary>

**Objective.** Confirm the free-shipping rule is inclusive, as documented.

**Preconditions**

- A product priced at exactly the threshold is available

**Steps**

1. Build a cart with a subtotal of exactly 5000 cents
2. Read the shipping component

**Expected result.** Shipping is 0 cents.

**Test data.** `{'threshold_cents': 5000}`

**Priority** P1 &middot; **Suites** regression &middot; **Automation** tests/api/test_cart.py::test_shipping_is_free_at_exactly_the_threshold

</details>

<details><summary><strong>TC-CART-032</strong> — Shipping is charged one cent below the threshold</summary>

**Objective.** Confirm the exclusive side of the free-shipping boundary.

**Preconditions**

- A product priced one cent below the threshold is available

**Steps**

1. Build a cart with a subtotal of exactly 4999 cents
2. Read the shipping component

**Expected result.** Shipping is the flat rate of 499 cents.

**Priority** P1 &middot; **Suites** regression &middot; **Automation** tests/api/test_cart.py::test_shipping_is_charged_one_cent_below_the_threshold

</details>

<details><summary><strong>TC-CART-033</strong> — An empty cart has zero totals and no shipping</summary>

**Objective.** Confirm the empty state does not attract a shipping charge.

**Preconditions**

- The cart is empty

**Steps**

1. GET /api/cart

**Expected result.** Every total component is zero.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/api/test_cart.py::test_an_empty_cart_has_zero_totals_and_no_shipping

</details>

<details><summary><strong>TC-CART-040</strong> — A percentage coupon discounts the cart once</summary>

**Objective.** Confirm the discount applies to the subtotal exactly once.

**Preconditions**

- An active 10% coupon with no minimum spend exists

**Steps**

1. Build a cart with 2 units of one product
2. Apply the coupon
3. Compare the discount with 10% of the subtotal computed independently

**Expected result.** The discount equals 10% of the subtotal, and every other total follows from it.

**Priority** P1 &middot; **Suites** regression &middot; **Automation** tests/api/test_cart.py::test_a_percentage_coupon_discounts_the_cart_once

</details>

<details><summary><strong>TC-CART-041</strong> — A coupon discounts a multi-line cart only once</summary>

**Objective.** Detect per-line discount stacking. A cart with more than one line is the shape in which applying the percentage per line is visible.

**Preconditions**

- An active 10% coupon exists

**Steps**

1. Build a cart with two different products
2. Apply the coupon
3. Compare the discount with 10% of the whole subtotal

**Expected result.** The discount equals 10% of the combined subtotal. A larger discount means the percentage is being applied per line and then summed.

**Priority** P1 &middot; **Suites** regression &middot; **Automation** tests/api/test_cart.py::test_a_coupon_discounts_a_multi_line_cart_only_once

</details>

<details><summary><strong>TC-CART-042</strong> — An unknown coupon code is rejected</summary>

**Objective.** Confirm invented codes discount nothing.

**Preconditions**

- The cart holds at least one item

**Steps**

1. Apply a coupon code that does not exist
2. Read the cart totals back

**Expected result.** The response is 404 and the discount remains zero.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/api/test_cart.py::test_an_unknown_coupon_code_is_rejected

</details>

<details><summary><strong>TC-CART-043</strong> — An inactive coupon is rejected</summary>

**Objective.** Confirm deactivated codes stop working immediately.

**Preconditions**

- A coupon exists with is_active set to 0

**Steps**

1. Apply the inactive coupon to a non-empty cart

**Expected result.** The response is 404.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/api/test_cart.py::test_an_inactive_coupon_is_rejected

</details>

<details><summary><strong>TC-CART-044</strong> — A coupon below its minimum spend is refused</summary>

**Objective.** Confirm minimum-spend gating just under the bound.

**Preconditions**

- A coupon requiring 5000 cents of spend exists

**Steps**

1. Build a cart worth well under 5000 cents
2. Apply the coupon

**Expected result.** The response is 409 and the message names the minimum spend.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/api/test_cart.py::test_a_coupon_below_its_minimum_spend_is_refused

</details>

<details><summary><strong>TC-CART-045</strong> — A coupon at exactly its minimum spend is accepted</summary>

**Objective.** Confirm the inclusive side of the minimum-spend bound.

**Preconditions**

- A coupon requiring 5000 cents of spend exists

**Steps**

1. Build a cart with a subtotal of exactly 5000 cents
2. Apply the coupon

**Expected result.** The coupon is accepted with 200 and discounts exactly 1000 cents.

**Priority** P1 &middot; **Suites** regression &middot; **Automation** tests/api/test_cart.py::test_a_coupon_at_exactly_its_minimum_spend_is_accepted

</details>

<details><summary><strong>TC-CART-046</strong> — Clearing the cart also clears the applied coupon</summary>

**Objective.** Confirm a coupon does not survive the cart it was applied to.

**Preconditions**

- A coupon has been applied to a non-empty cart

**Steps**

1. DELETE /api/cart

**Expected result.** The response is 200 with no coupon and a zero discount.

**Priority** P3 &middot; **Suites** regression &middot; **Automation** tests/api/test_cart.py::test_clearing_the_cart_also_clears_the_applied_coupon

</details>

<details><summary><strong>TC-CART-050</strong> — Two coupons cannot be stacked on one cart</summary>

**Objective.** Confirm only one coupon applies once multi-coupon support is considered.

**Preconditions**

- Multiple coupon support is specified (not implemented in build 1.4.0)

**Steps**

1. Apply one coupon, then apply a second
2. Read the resulting discount

**Expected result.** Only the most recently applied coupon is in force; discounts never compound. Manual until the requirement is confirmed with product.

**Priority** P2 &middot; **Suites** manual &middot; **Automation** manual only

</details>

## Module: data (23 cases)

| ID | Title | Layer | Type | Pri | Requirement | Automation |
| --- | --- | --- | --- | --- | --- | --- |
| `TC-SQL-001` | Every expected table exists | db | smoke | P1 | REQ-DATA-01 | `test_every_expected_table_exists` |
| `TC-SQL-002` | Required columns are present on every core table | db | functional | P2 | REQ-DATA-01 | `test_required_columns_are_present` |
| `TC-SQL-003` | Money and quantity columns are stored as integers | db | data | P1 | REQ-DATA-02 | `test_money_and_quantity_columns_are_integers` |
| `TC-SQL-004` | Foreign keys are declared between related tables | db | data | P1 | REQ-DATA-03 | `test_foreign_keys_are_declared_between_related_tables` |
| `TC-SQL-005` | Lookup columns are indexed | db | data | P3 | REQ-DATA-04 | `test_lookup_columns_are_indexed` |
| `TC-SQL-006` | The database rejects a negative price | db | negative | P2 | REQ-DATA-05 | `test_the_database_rejects_a_negative_price` |
| `TC-SQL-007` | The database rejects a duplicate SKU | db | negative | P2 | REQ-DATA-05 | `test_the_database_rejects_a_duplicate_sku` |
| `TC-SQL-008` | The database rejects an invalid order status | db | negative | P2 | REQ-DATA-05 | `test_the_database_rejects_an_invalid_order_status` |
| `TC-SQL-009` | A cart item cannot reference a product that does not exist | db | negative | P2 | REQ-DATA-03 | `test_a_cart_item_cannot_reference_a_product_that_does_not_exist` |
| `TC-SQL-020` | There are no foreign key violations anywhere in the database | db | data | P1 | REQ-DATA-03 | `test_there_are_no_foreign_key_violations` |
| `TC-SQL-021` | No order item is orphaned | db | data | P2 | REQ-DATA-03 | `test_no_order_item_is_orphaned` |
| `TC-SQL-022` | No product has negative stock | db | data | P1 | REQ-DATA-06 | `test_no_product_has_negative_stock` |
| `TC-SQL-023` | No two users share an email address | db | data | P1 | REQ-DATA-07 | `test_no_two_users_share_an_email_address` |
| `TC-SQL-024` | No password is stored in a recoverable form | db | security | P1 | REQ-SEC-11 | `test_no_password_is_stored_in_a_recoverable_form` |
| `TC-SQL-025` | Password hashes are uniquely salted | db | security | P1 | REQ-SEC-11 | `test_password_hashes_are_uniquely_salted` |
| `TC-SQL-030` | Every order line total equals quantity times unit price | db | data | P1 | REQ-PRICE-01 | `test_every_order_line_total_equals_quantity_times_unit_price` |
| `TC-SQL-031` | Every order subtotal equals the sum of its lines | db | data | P1 | REQ-PRICE-01 | `test_every_order_subtotal_equals_the_sum_of_its_lines` |
| `TC-SQL-032` | Every order total is internally consistent | db | data | P1 | REQ-PRICE-01 | `test_every_order_total_is_internally_consistent` |
| `TC-SQL-033` | A placed order is written with the expected row shape | db | data | P1 | REQ-ORD-05 | `test_a_placed_order_is_written_with_the_expected_row_shape` |
| `TC-SQL-034` | A cancelled order keeps its line items for audit | db | data | P2 | REQ-ORD-11 | `test_a_cancelled_order_keeps_its_line_items_for_audit` |
| `TC-SQL-035` | Revenue by category reconciles with the order items | db | data | P2 | REQ-DATA-08 | `test_revenue_by_category_reconciles_with_the_order_items` |
| `TC-SQL-036` | Cart contents are reachable through the full join path | db | data | P3 | REQ-DATA-08 | `test_cart_contents_are_reachable_through_the_full_join_path` |
| `TC-SQL-040` | A schema migration is reversible on a populated database | db | data | P2 | REQ-DATA-09 | _manual_ |

<details><summary><strong>TC-SQL-001</strong> — Every expected table exists</summary>

**Objective.** Confirm the schema deployed is the schema designed.

**Preconditions**

- The database has been migrated

**Steps**

1. List the user tables in the database
2. Compare against the expected set

**Expected result.** users, products, carts, cart_items, coupons, orders and order_items are all present.

**Priority** P1 &middot; **Suites** smoke, regression &middot; **Automation** tests/db/test_sql_validation.py::test_every_expected_table_exists

</details>

<details><summary><strong>TC-SQL-002</strong> — Required columns are present on every core table</summary>

**Objective.** Confirm the column-level contract the application depends on.

**Preconditions**

- The schema is deployed

**Steps**

1. Read the column list for users, products, orders and order_items
2. Assert each required column is present

**Expected result.** Every column the application reads or writes exists.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/db/test_sql_validation.py::test_required_columns_are_present

</details>

<details><summary><strong>TC-SQL-003</strong> — Money and quantity columns are stored as integers</summary>

**Objective.** Confirm money is held in integer cents. A drift to a floating-point column accumulates rounding error that is expensive to reconcile later.

**Preconditions**

- The schema is deployed

**Steps**

1. Read the declared type of every monetary and quantity column

**Expected result.** Every such column is declared INTEGER.

**Priority** P1 &middot; **Suites** regression &middot; **Automation** tests/db/test_sql_validation.py::test_money_and_quantity_columns_are_integers

</details>

<details><summary><strong>TC-SQL-004</strong> — Foreign keys are declared between related tables</summary>

**Objective.** Confirm referential integrity is enforced by the database itself.

**Preconditions**

- The schema is deployed

**Steps**

1. Read the foreign key list for cart_items, order_items, orders and carts

**Expected result.** Each table references the parents it depends on.

**Priority** P1 &middot; **Suites** regression &middot; **Automation** tests/db/test_sql_validation.py::test_foreign_keys_are_declared_between_related_tables

</details>

<details><summary><strong>TC-SQL-005</strong> — Lookup columns are indexed</summary>

**Objective.** Confirm the columns filtered on every request carry an index.

**Preconditions**

- The schema is deployed

**Steps**

1. Read the index list for products and orders

**Expected result.** products.category and orders.user_id are indexed.

**Priority** P3 &middot; **Suites** regression &middot; **Automation** tests/db/test_sql_validation.py::test_lookup_columns_are_indexed

</details>

<details><summary><strong>TC-SQL-006</strong> — The database rejects a negative price</summary>

**Objective.** Confirm the CHECK constraint is real rather than documentation.

**Preconditions**

- The schema is deployed

**Steps**

1. Attempt to insert a product with price_cents of -100

**Expected result.** The insert raises an integrity error.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/db/test_sql_validation.py::test_the_database_rejects_a_negative_price

</details>

<details><summary><strong>TC-SQL-007</strong> — The database rejects a duplicate SKU</summary>

**Objective.** Confirm uniqueness is enforced at the storage layer, not only in application code.

**Preconditions**

- A product with a known SKU exists

**Steps**

1. Attempt to insert a second product with the same SKU

**Expected result.** The insert raises an integrity error.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/db/test_sql_validation.py::test_the_database_rejects_a_duplicate_sku

</details>

<details><summary><strong>TC-SQL-008</strong> — The database rejects an invalid order status</summary>

**Objective.** Confirm order status is a closed set guarded by a CHECK constraint.

**Preconditions**

- A user row exists

**Steps**

1. Attempt to insert an order with a status outside the documented set

**Expected result.** The insert raises an integrity error.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/db/test_sql_validation.py::test_the_database_rejects_an_invalid_order_status

</details>

<details><summary><strong>TC-SQL-009</strong> — A cart item cannot reference a product that does not exist</summary>

**Objective.** Confirm foreign keys are enforced at runtime, not merely declared.

**Preconditions**

- A cart row exists

**Steps**

1. Attempt to insert a cart item pointing at product id 999999

**Expected result.** The insert raises an integrity error.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/db/test_sql_validation.py::test_a_cart_item_cannot_reference_a_product_that_does_not_exist

</details>

<details><summary><strong>TC-SQL-020</strong> — There are no foreign key violations anywhere in the database</summary>

**Objective.** Confirm nothing in the database points at a row that no longer exists.

**Preconditions**

- The suite has exercised the application

**Steps**

1. Run a full foreign key check across the database

**Expected result.** The check reports no violations.

**Priority** P1 &middot; **Suites** smoke, regression &middot; **Automation** tests/db/test_sql_validation.py::test_there_are_no_foreign_key_violations

</details>

<details><summary><strong>TC-SQL-021</strong> — No order item is orphaned</summary>

**Objective.** Confirm every line belongs to an order that exists.

**Preconditions**

- Orders have been placed

**Steps**

1. Left join order_items to orders and select rows with no parent

**Expected result.** The query returns no rows.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/db/test_sql_validation.py::test_no_order_item_is_orphaned

</details>

<details><summary><strong>TC-SQL-022</strong> — No product has negative stock</summary>

**Objective.** Confirm stock can reach zero but never go below it.

**Preconditions**

- Orders and cancellations have been exercised

**Steps**

1. Select products with stock below zero

**Expected result.** The query returns no rows.

**Priority** P1 &middot; **Suites** regression &middot; **Automation** tests/db/test_sql_validation.py::test_no_product_has_negative_stock

</details>

<details><summary><strong>TC-SQL-023</strong> — No two users share an email address</summary>

**Objective.** Confirm account identity is unique, case-insensitively.

**Preconditions**

- Registrations have been exercised

**Steps**

1. Group users by lowercased email and select groups larger than one

**Expected result.** The query returns no rows.

**Priority** P1 &middot; **Suites** regression &middot; **Automation** tests/db/test_sql_validation.py::test_no_two_users_share_an_email_address

</details>

<details><summary><strong>TC-SQL-024</strong> — No password is stored in a recoverable form</summary>

**Objective.** The single most important row-level check in the schema. A plaintext or unsalted credential is a breach waiting to be disclosed.

**Preconditions**

- User accounts exist

**Steps**

1. Select any user row whose password_hash is not a PBKDF2 hash

**Expected result.** The query returns no rows.

**Priority** P1 &middot; **Suites** smoke, regression &middot; **Automation** tests/db/test_sql_validation.py::test_no_password_is_stored_in_a_recoverable_form

</details>

<details><summary><strong>TC-SQL-025</strong> — Password hashes are uniquely salted</summary>

**Objective.** Confirm two identical passwords do not produce one hash.

**Preconditions**

- Several user accounts exist

**Steps**

1. Compare the count of users with the count of distinct password hashes

**Expected result.** The two counts are equal.

**Priority** P1 &middot; **Suites** regression &middot; **Automation** tests/db/test_sql_validation.py::test_password_hashes_are_uniquely_salted

</details>

<details><summary><strong>TC-SQL-030</strong> — Every order line total equals quantity times unit price</summary>

**Objective.** Verify line arithmetic in SQL across every stored row.

**Preconditions**

- Orders exist

**Steps**

1. Select order lines where line_total_cents differs from quantity times unit_price_cents

**Expected result.** The query returns no rows.

**Priority** P1 &middot; **Suites** regression &middot; **Automation** tests/db/test_sql_validation.py::test_every_order_line_total_equals_quantity_times_unit_price

</details>

<details><summary><strong>TC-SQL-031</strong> — Every order subtotal equals the sum of its lines</summary>

**Objective.** Confirm the order header agrees with its line items.

**Preconditions**

- A multi-line order has been placed

**Steps**

1. Group order_items by order and compare the sum with the stored subtotal

**Expected result.** The query returns no mismatched orders.

**Priority** P1 &middot; **Suites** regression &middot; **Automation** tests/db/test_sql_validation.py::test_every_order_subtotal_equals_the_sum_of_its_lines

</details>

<details><summary><strong>TC-SQL-032</strong> — Every order total is internally consistent</summary>

**Objective.** Confirm subtotal minus discount plus shipping plus tax equals the stored total, for all rows.

**Preconditions**

- A discounted order has been placed

**Steps**

1. Select orders where the components do not sum to the total

**Expected result.** The query returns no rows.

**Priority** P1 &middot; **Suites** regression &middot; **Automation** tests/db/test_sql_validation.py::test_every_order_total_is_internally_consistent

</details>

<details><summary><strong>TC-SQL-033</strong> — A placed order is written with the expected row shape</summary>

**Objective.** Confirm the API response and the stored row describe the same order.

**Preconditions**

- An order has just been placed through the API

**Steps**

1. Place an order and capture the response
2. Read the corresponding row by order number
3. Compare each monetary field

**Expected result.** Every monetary field matches and the status is PLACED.

**Priority** P1 &middot; **Suites** regression &middot; **Automation** tests/db/test_sql_validation.py::test_a_placed_order_is_written_with_the_expected_row_shape

</details>

<details><summary><strong>TC-SQL-034</strong> — A cancelled order keeps its line items for audit</summary>

**Objective.** Confirm cancellation changes status without destroying history.

**Preconditions**

- An order has been cancelled

**Steps**

1. Cancel an order
2. Read its status and its line items

**Expected result.** The status is CANCELLED and the line items are still present.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/db/test_sql_validation.py::test_a_cancelled_order_keeps_its_line_items_for_audit

</details>

<details><summary><strong>TC-SQL-035</strong> — Revenue by category reconciles with the order items</summary>

**Objective.** Confirm a real multi-table reporting join returns coherent numbers. Aggregates are where a silently wrong JOIN first shows up.

**Preconditions**

- Orders exist across more than one category

**Steps**

1. Run the revenue-by-category report
2. Sum its gross column and compare with the raw sum of non-cancelled lines

**Expected result.** The two totals are equal.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/db/test_sql_validation.py::test_revenue_by_category_reconciles_with_the_order_items

</details>

<details><summary><strong>TC-SQL-036</strong> — Cart contents are reachable through the full join path</summary>

**Objective.** Confirm users, carts, cart_items and products all connect.

**Preconditions**

- A customer has items in their cart

**Steps**

1. Join the four tables filtering by the customer's email

**Expected result.** The join returns exactly the expected line with the correct SKU and quantity.

**Priority** P3 &middot; **Suites** regression &middot; **Automation** tests/db/test_sql_validation.py::test_cart_contents_are_reachable_through_the_full_join_path

</details>

<details><summary><strong>TC-SQL-040</strong> — A schema migration is reversible on a populated database</summary>

**Objective.** Confirm a migration can be rolled back without data loss.

**Preconditions**

- A migration tool is adopted (not yet in build 1.4.0)

**Steps**

1. Take a snapshot of a populated database
2. Apply the migration, then roll it back
3. Compare row counts and checksums with the snapshot

**Expected result.** The rolled-back database is identical to the snapshot. Manual until migrations are introduced.

**Priority** P2 &middot; **Suites** manual &middot; **Automation** manual only

</details>

## Module: orders (18 cases)

| ID | Title | Layer | Type | Pri | Requirement | Automation |
| --- | --- | --- | --- | --- | --- | --- |
| `TC-ORD-001` | A customer can complete a checkout | api | smoke | P1 | REQ-ORD-01 | `test_a_customer_can_complete_a_checkout` |
| `TC-ORD-002` | Checkout empties the cart | api | functional | P1 | REQ-ORD-02 | `test_checkout_empties_the_cart` |
| `TC-ORD-010` | Order totals match the cart totals at the moment of checkout | api | functional | P1 | REQ-ORD-03 | `test_order_totals_match_the_cart_totals_at_the_moment_of_checkout` |
| `TC-ORD-011` | Order totals match the independent pricing oracle | api | functional | P1 | REQ-PRICE-01 | `test_order_totals_match_the_independent_pricing_oracle` |
| `TC-ORD-012` | Checkout decrements stock by the ordered quantity | api | data | P1 | REQ-ORD-04 | `test_checkout_decrements_stock_by_the_ordered_quantity` |
| `TC-ORD-013` | Order line items store the price at purchase time | db | data | P1 | REQ-ORD-05 | `test_order_line_items_are_persisted_with_the_price_at_purchase_time` |
| `TC-ORD-014` | Each order receives a unique order number | api | functional | P2 | REQ-ORD-06 | `test_each_order_receives_a_unique_order_number` |
| `TC-ORD-020` | Checking out an empty cart is rejected | api | negative | P2 | REQ-ORD-07 | `test_checking_out_an_empty_cart_is_rejected` |
| `TC-ORD-021` | Checkout requires authentication | api | security | P1 | REQ-SEC-03 | `test_checkout_requires_authentication` |
| `TC-ORD-022` | Checkout is refused when stock disappears after the cart was built | api | negative | P1 | REQ-ORD-08 | `test_checkout_is_refused_when_stock_disappears_after_the_cart_was_built` |
| `TC-ORD-023` | A failed checkout leaves no partial order | db | data | P1 | REQ-ORD-09 | `test_a_failed_checkout_leaves_no_partial_order` |
| `TC-ORD-024` | Checking out exactly the last unit in stock succeeds | api | boundary | P1 | REQ-ORD-08 | `test_checking_out_exactly_the_last_unit_in_stock_succeeds` |
| `TC-ORD-030` | An order appears in the customer's history | api | functional | P2 | REQ-ORD-10 | `test_an_order_appears_in_the_customers_history` |
| `TC-ORD-031` | An order can be retrieved by id with its line items | api | functional | P2 | REQ-ORD-10 | `test_an_order_can_be_retrieved_by_id_with_its_line_items` |
| `TC-ORD-032` | Retrieving an unknown order returns not found | api | negative | P3 | REQ-ORD-10 | `test_retrieving_an_unknown_order_returns_not_found` |
| `TC-ORD-033` | Cancelling an order restores its stock | api | functional | P1 | REQ-ORD-11 | `test_cancelling_an_order_restores_its_stock` |
| `TC-ORD-034` | Cancelling an already cancelled order is idempotent | api | boundary | P2 | REQ-ORD-11 | `test_cancelling_an_already_cancelled_order_is_idempotent` |
| `TC-ORD-040` | Two customers checking out the last unit concurrently | api | integration | P1 | REQ-ORD-12 | _manual_ |

<details><summary><strong>TC-ORD-001</strong> — A customer can complete a checkout</summary>

**Objective.** Confirm the critical revenue path works at all.

**Preconditions**

- An authenticated customer with one in-stock item in the cart

**Steps**

1. POST /api/orders
2. Inspect the order number, status and line items

**Expected result.** The response is 201 with an order number prefixed "SN-", status "PLACED", the expected line item and a positive total.

**Priority** P1 &middot; **Suites** smoke, regression &middot; **Automation** tests/api/test_orders.py::test_a_customer_can_complete_a_checkout

</details>

<details><summary><strong>TC-ORD-002</strong> — Checkout empties the cart</summary>

**Objective.** Confirm a placed order does not leave its items behind to be bought twice.

**Preconditions**

- An authenticated customer with items in the cart

**Steps**

1. Place an order
2. GET /api/cart

**Expected result.** The cart is empty.

**Priority** P1 &middot; **Suites** smoke, regression &middot; **Automation** tests/api/test_orders.py::test_checkout_empties_the_cart

</details>

<details><summary><strong>TC-ORD-010</strong> — Order totals match the cart totals at the moment of checkout</summary>

**Objective.** Confirm the price the customer saw is the price they are charged.

**Preconditions**

- A multi-line cart has been built

**Steps**

1. Read the cart totals
2. Place the order
3. Compare every total component between cart and order

**Expected result.** Subtotal, discount, shipping, tax and total are identical in both.

**Priority** P1 &middot; **Suites** regression &middot; **Automation** tests/api/test_orders.py::test_order_totals_match_the_cart_totals_at_the_moment_of_checkout

</details>

<details><summary><strong>TC-ORD-011</strong> — Order totals match the independent pricing oracle</summary>

**Objective.** Verify order maths against the documented rules rather than the application's own arithmetic.

**Preconditions**

- A discounted cart has been built

**Steps**

1. Apply a 10% coupon to a two-unit cart
2. Place the order
3. Compare each total with the independently computed value

**Expected result.** Every component matches the value derived from the documented pricing rules.

**Priority** P1 &middot; **Suites** regression &middot; **Automation** tests/api/test_orders.py::test_order_totals_match_the_independent_pricing_oracle

</details>

<details><summary><strong>TC-ORD-012</strong> — Checkout decrements stock by the ordered quantity</summary>

**Objective.** Confirm inventory actually moves, verified directly in SQL.

**Preconditions**

- The product's stock level is known before the test

**Steps**

1. Read the product's stock from the database
2. Order 3 units
3. Read the stock again

**Expected result.** Stock has decreased by exactly 3.

**Priority** P1 &middot; **Suites** regression &middot; **Automation** tests/api/test_orders.py::test_checkout_decrements_stock_by_the_ordered_quantity

</details>

<details><summary><strong>TC-ORD-013</strong> — Order line items store the price at purchase time</summary>

**Objective.** Confirm an order records its own prices. A line that reads the live catalogue price would silently restate every historical order after a price change.

**Preconditions**

- A known product price

**Steps**

1. Order 2 units of a product
2. Query order_items for that order

**Expected result.** The stored unit price equals the catalogue price at purchase time and the line total equals unit price multiplied by quantity.

**Priority** P1 &middot; **Suites** regression &middot; **Automation** tests/api/test_orders.py::test_order_line_items_are_persisted_with_the_price_at_purchase_time

</details>

<details><summary><strong>TC-ORD-014</strong> — Each order receives a unique order number</summary>

**Objective.** Confirm order numbers do not collide.

**Preconditions**

- An authenticated customer

**Steps**

1. Place three orders in succession
2. Collect the three order numbers

**Expected result.** All three order numbers are distinct.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/api/test_orders.py::test_each_order_receives_a_unique_order_number

</details>

<details><summary><strong>TC-ORD-020</strong> — Checking out an empty cart is rejected</summary>

**Objective.** Confirm an empty cart produces no order.

**Preconditions**

- The cart is empty

**Steps**

1. POST /api/orders

**Expected result.** The response is 400 and the message says the cart is empty.

**Priority** P2 &middot; **Suites** smoke, regression &middot; **Automation** tests/api/test_orders.py::test_checking_out_an_empty_cart_is_rejected

</details>

<details><summary><strong>TC-ORD-021</strong> — Checkout requires authentication</summary>

**Objective.** Confirm anonymous checkout is impossible.

**Preconditions**

- No Authorization header is sent

**Steps**

1. POST /api/orders with no token

**Expected result.** The response is 401.

**Priority** P1 &middot; **Suites** smoke, regression &middot; **Automation** tests/api/test_orders.py::test_checkout_requires_authentication

</details>

<details><summary><strong>TC-ORD-022</strong> — Checkout is refused when stock disappears after the cart was built</summary>

**Objective.** Reproduce the real-world race in which an item sells out between browsing and paying. Failing to revalidate here means taking money for inventory that does not exist.

**Preconditions**

- A product's stock can be manipulated during the test

**Steps**

1. Set stock to 5 and add 5 units to the cart
2. Reduce stock to 2, simulating another customer's purchase
3. Attempt checkout

**Expected result.** Checkout returns 409 rather than creating an unfulfillable order.

**Priority** P1 &middot; **Suites** regression &middot; **Automation** tests/api/test_orders.py::test_checkout_is_refused_when_stock_disappears_after_the_cart_was_built

</details>

<details><summary><strong>TC-ORD-023</strong> — A failed checkout leaves no partial order</summary>

**Objective.** Confirm the checkout transaction is genuinely all-or-nothing.

**Preconditions**

- A cart that will fail its stock revalidation

**Steps**

1. Record the order count before the attempt
2. Force a stock shortfall and attempt checkout
3. Re-check the order count, the stock level and the cart contents

**Expected result.** No order row was created, no stock moved, and the cart still holds its items so the customer can correct the problem.

**Priority** P1 &middot; **Suites** regression &middot; **Automation** tests/api/test_orders.py::test_a_failed_checkout_leaves_no_partial_order

</details>

<details><summary><strong>TC-ORD-024</strong> — Checking out exactly the last unit in stock succeeds</summary>

**Objective.** Confirm the inclusive edge of availability at checkout time.

**Preconditions**

- A product's stock is set to exactly 1

**Steps**

1. Add 1 unit to the cart and check out
2. Read the resulting stock level

**Expected result.** The order is created with 201 and stock falls to exactly 0.

**Priority** P1 &middot; **Suites** regression &middot; **Automation** tests/api/test_orders.py::test_checking_out_exactly_the_last_unit_in_stock_succeeds

</details>

<details><summary><strong>TC-ORD-030</strong> — An order appears in the customer's history</summary>

**Objective.** Confirm placed orders are retrievable afterwards.

**Preconditions**

- An authenticated customer who has just placed an order

**Steps**

1. Place an order
2. GET /api/orders

**Expected result.** The new order number is present in the history.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/api/test_orders.py::test_an_order_appears_in_the_customers_history

</details>

<details><summary><strong>TC-ORD-031</strong> — An order can be retrieved by id with its line items</summary>

**Objective.** Confirm detail retrieval returns the full order.

**Preconditions**

- An order exists for the calling customer

**Steps**

1. Place an order for 2 units
2. GET /api/orders/{id}

**Expected result.** The order number matches and the line item reports quantity 2.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/api/test_orders.py::test_an_order_can_be_retrieved_by_id_with_its_line_items

</details>

<details><summary><strong>TC-ORD-032</strong> — Retrieving an unknown order returns not found</summary>

**Objective.** Confirm an id that does not exist is a 404.

**Preconditions**

- The id does not exist

**Steps**

1. GET /api/orders/999999

**Expected result.** The response is 404.

**Priority** P3 &middot; **Suites** regression &middot; **Automation** tests/api/test_orders.py::test_retrieving_an_unknown_order_returns_not_found

</details>

<details><summary><strong>TC-ORD-033</strong> — Cancelling an order restores its stock</summary>

**Objective.** Confirm cancellation is a correct compensating transaction.

**Preconditions**

- An order exists in status PLACED

**Steps**

1. Record stock, place an order for 2 units and confirm stock fell by 2
2. Cancel the order
3. Read the stock again

**Expected result.** The order status is CANCELLED and stock has returned to its original level.

**Priority** P1 &middot; **Suites** regression &middot; **Automation** tests/api/test_orders.py::test_cancelling_an_order_restores_its_stock

</details>

<details><summary><strong>TC-ORD-034</strong> — Cancelling an already cancelled order is idempotent</summary>

**Objective.** Confirm a double cancel does not credit stock twice.

**Preconditions**

- An order has already been cancelled

**Steps**

1. Cancel an order, then cancel it a second time
2. Read the stock level

**Expected result.** The second call returns 200 with status CANCELLED and stock is unchanged by it.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/api/test_orders.py::test_cancelling_an_already_cancelled_order_is_idempotent

</details>

<details><summary><strong>TC-ORD-040</strong> — Two customers checking out the last unit concurrently</summary>

**Objective.** Confirm the transactional guard holds under genuine concurrency.

**Preconditions**

- A load-capable environment and a product with exactly one unit in stock

**Steps**

1. Two authenticated customers each hold the last unit in their cart
2. Both issue POST /api/orders simultaneously

**Expected result.** Exactly one checkout succeeds and the other returns 409. Stock never goes negative. Manual until a concurrency harness is added.

**Priority** P1 &middot; **Suites** manual &middot; **Automation** manual only

</details>

## Module: products (20 cases)

| ID | Title | Layer | Type | Pri | Requirement | Automation |
| --- | --- | --- | --- | --- | --- | --- |
| `TC-PROD-001` | The health endpoint reports the service is up | api | smoke | P1 | REQ-OPS-01 | `test_health_endpoint_reports_the_service_is_up` |
| `TC-PROD-002` | Product listing returns the seeded catalogue | api | functional | P1 | REQ-CAT-01 | `test_product_listing_returns_the_seeded_catalogue` |
| `TC-PROD-003` | A single product can be fetched by id | api | functional | P2 | REQ-CAT-02 | `test_a_single_product_can_be_fetched_by_id` |
| `TC-PROD-010` | An unknown product id returns not found | api | negative | P2 | REQ-CAT-03 | `test_an_unknown_product_id_returns_not_found` |
| `TC-PROD-011` | A non-integer product id is rejected | api | negative | P3 | REQ-CAT-03 | `test_a_non_integer_product_id_is_rejected` |
| `TC-PROD-020` | Search matches on both product name and SKU | api | functional | P2 | REQ-CAT-04 | `test_search_matches_on_both_name_and_sku` |
| `TC-PROD-021` | A search with no matches returns an empty page, not an error | api | boundary | P2 | REQ-CAT-04 | `test_search_with_no_matches_returns_an_empty_page_not_an_error` |
| `TC-PROD-022` | The category filter returns only that category | api | functional | P2 | REQ-CAT-05 | `test_category_filter_returns_only_that_category` |
| `TC-PROD-023` | The in-stock filter excludes unavailable products | api | functional | P2 | REQ-CAT-06 | `test_in_stock_filter_excludes_unavailable_products` |
| `TC-PROD-024` | Sorting by price returns ascending prices | api | functional | P3 | REQ-CAT-07 | `test_sorting_by_price_returns_ascending_prices` |
| `TC-PROD-030` | Pagination honours the requested page size | api | boundary | P2 | REQ-CAT-08 | `test_pagination_honours_the_requested_page_size` |
| `TC-PROD-031` | A page size outside the documented range is rejected | api | boundary | P2 | REQ-CAT-08 | `test_page_size_outside_the_documented_range_is_rejected` |
| `TC-PROD-032` | Requesting a page beyond the last returns an empty page | api | boundary | P3 | REQ-CAT-08 | `test_requesting_a_page_beyond_the_last_returns_an_empty_page` |
| `TC-PROD-033` | Pages do not overlap or skip products | api | boundary | P2 | REQ-CAT-08 | `test_pages_do_not_overlap_or_skip_products` |
| `TC-PROD-034` | An inverted price range is rejected | api | negative | P3 | REQ-CAT-09 | `test_an_inverted_price_range_is_rejected` |
| `TC-PROD-035` | Price filters are inclusive at both bounds | api | boundary | P2 | REQ-CAT-09 | `test_price_filters_are_inclusive_at_both_bounds` |
| `TC-PROD-036` | Search terms containing markup are handled as data | api | security | P2 | REQ-SEC-10 | `test_search_terms_containing_markup_are_handled_as_data` |
| `TC-PROD-040` | Creating a product with a duplicate SKU is a conflict | api | negative | P2 | REQ-CAT-10 | `test_creating_a_product_with_a_duplicate_sku_is_a_conflict` |
| `TC-PROD-041` | Product creation validates its fields | api | boundary | P2 | REQ-CAT-10 | `test_product_creation_validates_its_fields` |
| `TC-PROD-050` | Catalogue images render at every supported breakpoint | ui | functional | P4 | REQ-CAT-11 | _manual_ |

<details><summary><strong>TC-PROD-001</strong> — The health endpoint reports the service is up</summary>

**Objective.** The cheapest possible build-acceptance signal.

**Preconditions**

- The service has been deployed

**Steps**

1. GET /health

**Expected result.** The response is 200 with status "ok" and a non-zero product count.

**Priority** P1 &middot; **Suites** smoke, regression &middot; **Automation** tests/api/test_products.py::test_health_endpoint_reports_the_service_is_up

</details>

<details><summary><strong>TC-PROD-002</strong> — Product listing returns the seeded catalogue</summary>

**Objective.** Confirm the catalogue is readable anonymously and matches the documented schema.

**Preconditions**

- The catalogue is seeded with at least ten products

**Steps**

1. GET /api/products with no parameters
2. Inspect total, page_size and the fields on the first item

**Expected result.** The response is 200, total is at least 10, and every item carries id, sku, name, category, price_cents, price, stock and in_stock. The decimal price equals price_cents divided by 100.

**Priority** P1 &middot; **Suites** smoke, regression &middot; **Automation** tests/api/test_products.py::test_product_listing_returns_the_seeded_catalogue

</details>

<details><summary><strong>TC-PROD-003</strong> — A single product can be fetched by id</summary>

**Objective.** Confirm detail retrieval agrees with the listing.

**Preconditions**

- A known SKU exists in the catalogue

**Steps**

1. Look the product up by SKU in the listing
2. GET /api/products/{id} for that product

**Expected result.** The detail response is 200 and its SKU and price match the listing.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/api/test_products.py::test_a_single_product_can_be_fetched_by_id

</details>

<details><summary><strong>TC-PROD-010</strong> — An unknown product id returns not found</summary>

**Objective.** Confirm unknown resources are reported rather than fabricated.

**Preconditions**

- The id is not present in the catalogue

**Steps**

1. GET /api/products/999999

**Expected result.** The response is 404 with a descriptive detail message.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/api/test_products.py::test_an_unknown_product_id_returns_not_found

</details>

<details><summary><strong>TC-PROD-011</strong> — A non-integer product id is rejected</summary>

**Objective.** Confirm path parameter typing is enforced.

**Preconditions**

- None

**Steps**

1. Request the product detail path with letters, a decimal, a negative number and an encoded space in place of the id

**Expected result.** Every variant returns 404 or 422; none returns a product.

**Priority** P3 &middot; **Suites** regression &middot; **Automation** tests/api/test_products.py::test_a_non_integer_product_id_is_rejected

</details>

<details><summary><strong>TC-PROD-020</strong> — Search matches on both product name and SKU</summary>

**Objective.** Confirm both documented search fields are covered.

**Preconditions**

- A product with a known name and SKU exists

**Steps**

1. GET /api/products with q set to part of the product name
2. GET /api/products with q set to the exact SKU

**Expected result.** The name search returns at least one match; the SKU search returns exactly that product.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/api/test_products.py::test_search_matches_on_both_name_and_sku

</details>

<details><summary><strong>TC-PROD-021</strong> — A search with no matches returns an empty page, not an error</summary>

**Objective.** Confirm the empty result set is a success response.

**Preconditions**

- None

**Steps**

1. GET /api/products with a query term that matches nothing

**Expected result.** The response is 200 with total 0, an empty items array and pages 0.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/api/test_products.py::test_search_with_no_matches_returns_an_empty_page_not_an_error

</details>

<details><summary><strong>TC-PROD-022</strong> — The category filter returns only that category</summary>

**Objective.** Confirm filtering is exact rather than a substring match.

**Preconditions**

- At least two categories exist

**Steps**

1. GET /api/products/categories
2. GET /api/products filtered by the first category returned

**Expected result.** Every item in the filtered response carries exactly that category.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/api/test_products.py::test_category_filter_returns_only_that_category

</details>

<details><summary><strong>TC-PROD-023</strong> — The in-stock filter excludes unavailable products</summary>

**Objective.** Confirm out-of-stock products are hidden when requested.

**Preconditions**

- At least one seeded product has zero stock

**Steps**

1. GET /api/products unfiltered and confirm the zero-stock SKU is present
2. GET /api/products with in_stock_only=true

**Expected result.** The filtered response excludes the zero-stock SKU and every item has stock above zero.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/api/test_products.py::test_in_stock_filter_excludes_unavailable_products

</details>

<details><summary><strong>TC-PROD-024</strong> — Sorting by price returns ascending prices</summary>

**Objective.** Confirm the sort parameter is applied.

**Preconditions**

- Products of differing prices exist

**Steps**

1. GET /api/products with sort=price and a page size covering the catalogue

**Expected result.** The returned price_cents values are in non-descending order.

**Priority** P3 &middot; **Suites** regression &middot; **Automation** tests/api/test_products.py::test_sorting_by_price_returns_ascending_prices

</details>

<details><summary><strong>TC-PROD-030</strong> — Pagination honours the requested page size</summary>

**Objective.** Exercise page_size across its documented 1..100 range.

**Preconditions**

- The catalogue holds more products than the smallest page size

**Steps**

1. Request page 1 with page_size 1, 2, 10 and 100
2. Compare the item count and the reported page count each time

**Expected result.** Each response returns at most page_size items, echoes the requested page_size, and reports pages as ceil(total / page_size).

**Test data.** `{'minimum': 1, 'maximum': 100}`

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/api/test_products.py::test_pagination_honours_the_requested_page_size

</details>

<details><summary><strong>TC-PROD-031</strong> — A page size outside the documented range is rejected</summary>

**Objective.** Confirm the other half of the page_size boundary.

**Preconditions**

- None

**Steps**

1. Request page_size 0, -1, 101 and 10000

**Expected result.** Every out-of-range value returns 422.

**Test data.** `{'values': [0, -1, 101, 10000]}`

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/api/test_products.py::test_page_size_outside_the_documented_range_is_rejected

</details>

<details><summary><strong>TC-PROD-032</strong> — Requesting a page beyond the last returns an empty page</summary>

**Objective.** Confirm over-paging is an empty result rather than an error.

**Preconditions**

- The catalogue is not empty

**Steps**

1. GET /api/products with page 9999

**Expected result.** The response is 200 with an empty items array while total still reports the real catalogue size.

**Priority** P3 &middot; **Suites** regression &middot; **Automation** tests/api/test_products.py::test_requesting_a_page_beyond_the_last_returns_an_empty_page

</details>

<details><summary><strong>TC-PROD-033</strong> — Pages do not overlap or skip products</summary>

**Objective.** Confirm paging arithmetic yields each product exactly once.

**Preconditions**

- The catalogue holds at least eight products

**Steps**

1. Fetch page 1 and page 2 at a page size of 4, sorted by name
2. Compare the two id sets, then compare their concatenation with the first eight ids of the unpaginated listing

**Expected result.** The two pages share no ids and together match the first eight products in the same order.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/api/test_products.py::test_pages_do_not_overlap_or_skip_products

</details>

<details><summary><strong>TC-PROD-034</strong> — An inverted price range is rejected</summary>

**Objective.** Confirm a minimum above the maximum is a client error rather than a silent empty list.

**Preconditions**

- None

**Steps**

1. GET /api/products with min_price_cents greater than max_price_cents

**Expected result.** The response is 400.

**Priority** P3 &middot; **Suites** regression &middot; **Automation** tests/api/test_products.py::test_an_inverted_price_range_is_rejected

</details>

<details><summary><strong>TC-PROD-035</strong> — Price filters are inclusive at both bounds</summary>

**Objective.** Confirm a product priced exactly on the bound is included.

**Preconditions**

- A product with a known price exists

**Steps**

1. Read a product's exact price
2. GET /api/products with min_price_cents and max_price_cents both set to that price

**Expected result.** The product appears in the results, proving both bounds are inclusive.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/api/test_products.py::test_price_filters_are_inclusive_at_both_bounds

</details>

<details><summary><strong>TC-PROD-036</strong> — Search terms containing markup are handled as data</summary>

**Objective.** Confirm script and markup payloads are treated as ordinary search text.

**Preconditions**

- None

**Steps**

1. Search using a script tag, an img onerror payload and an svg onload payload

**Expected result.** Each search returns 200 with no matches and no error.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/api/test_products.py::test_search_terms_containing_markup_are_handled_as_data

</details>

<details><summary><strong>TC-PROD-040</strong> — Creating a product with a duplicate SKU is a conflict</summary>

**Objective.** Confirm SKU uniqueness is enforced at the API, not only in the database.

**Preconditions**

- An admin session is authenticated

**Steps**

1. Create a product with a unique SKU
2. Create a second product with the same SKU

**Expected result.** The first call returns 201 and the second returns 409.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/api/test_products.py::test_creating_a_product_with_a_duplicate_sku_is_a_conflict

</details>

<details><summary><strong>TC-PROD-041</strong> — Product creation validates its fields</summary>

**Objective.** Exercise every documented constraint on the product creation schema.

**Preconditions**

- An admin session is authenticated

**Steps**

1. Attempt creation with a negative price, negative stock, a two-character SKU, a blank name and a price above the documented maximum

**Expected result.** Every variant returns 422 and no product row is created.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/api/test_products.py::test_product_creation_validates_its_fields

</details>

<details><summary><strong>TC-PROD-050</strong> — Catalogue images render at every supported breakpoint</summary>

**Objective.** Confirm the responsive grid holds together on small screens.

**Preconditions**

- Product imagery is implemented (not yet in build 1.4.0)

**Steps**

1. Load the catalogue at 360px, 768px and 1366px viewport widths
2. Confirm no card overflows its container and no image is stretched

**Expected result.** The grid reflows without overflow at every breakpoint. Manual until imagery ships.

**Priority** P4 &middot; **Suites** manual &middot; **Automation** manual only

</details>

## Module: storefront (17 cases)

| ID | Title | Layer | Type | Pri | Requirement | Automation |
| --- | --- | --- | --- | --- | --- | --- |
| `TC-UI-001` | The storefront loads and shows the catalogue | ui | smoke | P1 | REQ-UI-01 | `test_the_storefront_loads_and_shows_the_catalogue` |
| `TC-UI-002` | A customer can sign in through the login form | ui | smoke | P1 | REQ-UI-02 | `test_a_customer_can_sign_in_through_the_login_form` |
| `TC-UI-003` | A customer can complete a purchase in the browser | ui | smoke | P1 | REQ-UI-03 | `test_a_customer_can_complete_a_purchase_in_the_browser` |
| `TC-UI-010` | Signing in with a wrong password shows an error and stays on the page | ui | negative | P1 | REQ-UI-04 | `test_signing_in_with_a_wrong_password_shows_an_error_and_stays_on_the_page` |
| `TC-UI-011` | Registering with a weak password shows the policy error | ui | negative | P2 | REQ-UI-04 | `test_registering_with_a_weak_password_shows_the_policy_error` |
| `TC-UI-012` | The cart page redirects an anonymous visitor to login | ui | security | P1 | REQ-UI-05 | `test_the_cart_page_redirects_an_anonymous_visitor_to_login` |
| `TC-UI-013` | An out-of-stock product cannot be added from the catalogue | ui | negative | P2 | REQ-UI-06 | `test_an_out_of_stock_product_cannot_be_added_from_the_catalogue` |
| `TC-UI-014` | An invalid coupon shows an error and does not discount | ui | negative | P2 | REQ-UI-07 | `test_an_invalid_coupon_shows_an_error_and_does_not_discount` |
| `TC-UI-020` | Search narrows the catalogue to matching products | ui | functional | P2 | REQ-UI-08 | `test_search_narrows_the_catalogue_to_matching_products` |
| `TC-UI-021` | A search with no matches shows an empty state | ui | boundary | P3 | REQ-UI-08 | `test_a_search_with_no_matches_shows_an_empty_state` |
| `TC-UI-022` | Sorting by price reorders the grid | ui | functional | P3 | REQ-UI-08 | `test_sorting_by_price_reorders_the_grid` |
| `TC-UI-023` | The cart badge reflects what was added | ui | functional | P2 | REQ-UI-09 | `test_the_cart_badge_reflects_what_was_added` |
| `TC-UI-024` | Changing the quantity in the cart updates the totals | ui | functional | P2 | REQ-UI-10 | `test_changing_the_quantity_in_the_cart_updates_the_totals` |
| `TC-UI-025` | Removing the last item empties the cart and disables checkout | ui | boundary | P2 | REQ-UI-10 | `test_removing_the_last_item_empties_the_cart_and_disables_checkout` |
| `TC-UI-026` | A valid coupon reduces the displayed total | ui | functional | P1 | REQ-UI-07 | `test_a_valid_coupon_reduces_the_displayed_total` |
| `TC-UI-027` | Signing out clears the session | ui | security | P1 | REQ-UI-05 | `test_signing_out_clears_the_session` |
| `TC-UI-030` | The storefront is operable with a keyboard alone | ui | functional | P3 | REQ-UI-11 | _manual_ |

<details><summary><strong>TC-UI-001</strong> — The storefront loads and shows the catalogue</summary>

**Objective.** Confirm the application renders in a real browser at all.

**Preconditions**

- The application is deployed and the catalogue is seeded

**Steps**

1. Navigate to /products
2. Wait for the page to signal it has finished rendering
3. Count the rendered product cards

**Expected result.** The heading reads "Catalogue" and at least ten product cards are rendered.

**Priority** P1 &middot; **Suites** smoke, regression &middot; **Automation** tests/ui/test_shopping_journey.py::test_the_storefront_loads_and_shows_the_catalogue

</details>

<details><summary><strong>TC-UI-002</strong> — A customer can sign in through the login form</summary>

**Objective.** Exercise the real login form rather than an injected token.

**Preconditions**

- A seeded customer account exists

**Steps**

1. Navigate to /login
2. Enter the seeded email and password and submit
3. Wait for the redirect

**Expected result.** The browser lands on /products and the header shows the signed-in email.

**Priority** P1 &middot; **Suites** smoke, regression &middot; **Automation** tests/ui/test_shopping_journey.py::test_a_customer_can_sign_in_through_the_login_form

</details>

<details><summary><strong>TC-UI-003</strong> — A customer can complete a purchase in the browser</summary>

**Objective.** The end-to-end revenue journey. If this test fails, the release is blocked regardless of what else is green.

**Preconditions**

- A signed-in customer and an in-stock product

**Steps**

1. Read the displayed price of a product on the catalogue
2. Add it to the cart and open the cart page
3. Confirm the line item and unit price match what was displayed
4. Place the order
5. Confirm the order in the database by its order number

**Expected result.** The confirmation banner names the new order, the order shows status PLACED with the total derived from the documented pricing rules, and a matching row exists in the orders table.

**Priority** P1 &middot; **Suites** smoke, regression &middot; **Automation** tests/ui/test_shopping_journey.py::test_a_customer_can_complete_a_purchase_in_the_browser

</details>

<details><summary><strong>TC-UI-010</strong> — Signing in with a wrong password shows an error and stays on the page</summary>

**Objective.** Confirm the failure path is handled rather than swallowed.

**Preconditions**

- A seeded customer account exists

**Steps**

1. Submit the login form with a valid email and an incorrect password
2. Wait for the error message

**Expected result.** An invalid-credentials message is shown, the URL is still /login and no session is created.

**Priority** P1 &middot; **Suites** regression &middot; **Automation** tests/ui/test_shopping_journey.py::test_signing_in_with_a_wrong_password_shows_an_error_and_stays_on_the_page

</details>

<details><summary><strong>TC-UI-011</strong> — Registering with a weak password shows the policy error</summary>

**Objective.** Confirm server-side validation surfaces in the browser.

**Preconditions**

- None

**Steps**

1. Submit the registration form with a three-character password
2. Wait for the error message

**Expected result.** A message naming the password policy is shown and the URL is still /register.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/ui/test_shopping_journey.py::test_registering_with_a_weak_password_shows_the_policy_error

</details>

<details><summary><strong>TC-UI-012</strong> — The cart page redirects an anonymous visitor to login</summary>

**Objective.** Confirm protected pages are not reachable without a session.

**Preconditions**

- Browser storage holds no session

**Steps**

1. Clear local storage
2. Navigate directly to /cart

**Expected result.** The browser is redirected to /login.

**Priority** P1 &middot; **Suites** regression &middot; **Automation** tests/ui/test_shopping_journey.py::test_the_cart_page_redirects_an_anonymous_visitor_to_login

</details>

<details><summary><strong>TC-UI-013</strong> — An out-of-stock product cannot be added from the catalogue</summary>

**Objective.** Confirm the interface disables what the API would refuse.

**Preconditions**

- A seeded product has zero stock

**Steps**

1. Locate the zero-stock product card
2. Inspect its stock label and its add-to-cart button

**Expected result.** The card reads "Out of stock" and the add button is disabled.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/ui/test_shopping_journey.py::test_an_out_of_stock_product_cannot_be_added_from_the_catalogue

</details>

<details><summary><strong>TC-UI-014</strong> — An invalid coupon shows an error and does not discount</summary>

**Objective.** Confirm a rejected coupon leaves the displayed totals untouched.

**Preconditions**

- A signed-in customer with a non-empty cart

**Steps**

1. Record the cart totals
2. Apply a coupon code that does not exist
3. Re-read the totals

**Expected result.** A rejection message is shown and every total is unchanged.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/ui/test_shopping_journey.py::test_an_invalid_coupon_shows_an_error_and_does_not_discount

</details>

<details><summary><strong>TC-UI-020</strong> — Search narrows the catalogue to matching products</summary>

**Objective.** Confirm search filters the rendered grid, not just the API response.

**Preconditions**

- The catalogue is seeded

**Steps**

1. Record the unfiltered result count
2. Search for a known product name

**Expected result.** Fewer products are shown and the expected SKU is among them.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/ui/test_shopping_journey.py::test_search_narrows_the_catalogue_to_matching_products

</details>

<details><summary><strong>TC-UI-021</strong> — A search with no matches shows an empty state</summary>

**Objective.** Confirm the empty state is rendered rather than a blank page.

**Preconditions**

- None

**Steps**

1. Search for a term that matches nothing

**Expected result.** An explicit no-results message is shown and no product cards remain.

**Priority** P3 &middot; **Suites** regression &middot; **Automation** tests/ui/test_shopping_journey.py::test_a_search_with_no_matches_shows_an_empty_state

</details>

<details><summary><strong>TC-UI-022</strong> — Sorting by price reorders the grid</summary>

**Objective.** Confirm the sort control reorders what is actually displayed.

**Preconditions**

- Products of differing prices exist

**Steps**

1. Select the price sort option and submit
2. Read the displayed prices in DOM order

**Expected result.** The displayed prices are in non-descending order.

**Priority** P3 &middot; **Suites** regression &middot; **Automation** tests/ui/test_shopping_journey.py::test_sorting_by_price_reorders_the_grid

</details>

<details><summary><strong>TC-UI-023</strong> — The cart badge reflects what was added</summary>

**Objective.** Confirm shared page chrome updates after an action.

**Preconditions**

- A signed-in customer with an empty cart

**Steps**

1. Add one product and wait for the confirmation
2. Add a second product and wait for the badge to change

**Expected result.** The badge reads 1 after the first add and 2 after the second.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/ui/test_shopping_journey.py::test_the_cart_badge_reflects_what_was_added

</details>

<details><summary><strong>TC-UI-024</strong> — Changing the quantity in the cart updates the totals</summary>

**Objective.** Confirm the cart recalculates without a page reload.

**Preconditions**

- A signed-in customer with one item in the cart

**Steps**

1. Change the quantity field to 3
2. Read the line total and the subtotal

**Expected result.** The line total and subtotal both equal unit price multiplied by 3.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/ui/test_shopping_journey.py::test_changing_the_quantity_in_the_cart_updates_the_totals

</details>

<details><summary><strong>TC-UI-025</strong> — Removing the last item empties the cart and disables checkout</summary>

**Objective.** Confirm the empty state disables an action that cannot succeed.

**Preconditions**

- A signed-in customer with exactly one item in the cart

**Steps**

1. Remove the only line
2. Wait for the table to empty

**Expected result.** The cart shows as empty and the checkout button is disabled.

**Priority** P2 &middot; **Suites** regression &middot; **Automation** tests/ui/test_shopping_journey.py::test_removing_the_last_item_empties_the_cart_and_disables_checkout

</details>

<details><summary><strong>TC-UI-026</strong> — A valid coupon reduces the displayed total</summary>

**Objective.** Confirm the discount the customer is promised is the one shown.

**Preconditions**

- A signed-in customer with a non-empty cart and an active coupon

**Steps**

1. Record the subtotal
2. Apply the 10% coupon and wait for the discount to appear
3. Compare every total against independently computed values

**Expected result.** The displayed totals match the documented pricing rules and the coupon code is shown as applied.

**Priority** P1 &middot; **Suites** regression &middot; **Automation** tests/ui/test_shopping_journey.py::test_a_valid_coupon_reduces_the_displayed_total

</details>

<details><summary><strong>TC-UI-027</strong> — Signing out clears the session</summary>

**Objective.** Confirm sign-out is real rather than cosmetic.

**Preconditions**

- A signed-in customer

**Steps**

1. Click sign out
2. Attempt to navigate directly to /cart

**Expected result.** The browser lands on /login and the protected page is no longer reachable.

**Priority** P1 &middot; **Suites** regression &middot; **Automation** tests/ui/test_shopping_journey.py::test_signing_out_clears_the_session

</details>

<details><summary><strong>TC-UI-030</strong> — The storefront is operable with a keyboard alone</summary>

**Objective.** Confirm the purchase journey does not require a pointing device.

**Preconditions**

- An accessibility review has defined the expected focus order

**Steps**

1. Tab through the catalogue, add an item, tab to the cart and check out
2. Confirm focus is visible at every step and no trap occurs

**Expected result.** The journey completes using only the keyboard with a visible focus indicator throughout. Manual until an axe-core audit is integrated.

**Priority** P3 &middot; **Suites** manual &middot; **Automation** manual only

</details>
