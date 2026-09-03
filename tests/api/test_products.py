"""Catalogue API tests: search, filtering, pagination and sorting."""
from __future__ import annotations

import pytest

from framework.data import builders
from framework.utils.helpers import assert_status

pytestmark = pytest.mark.api


@pytest.mark.smoke
def test_health_endpoint_reports_the_service_is_up(api):
    """TC-PROD-001: the cheapest possible build-acceptance check."""
    response = api.health()

    assert_status(response, 200, "GET /health")
    body = response.json()
    assert body["status"] == "ok"
    assert body["products"] > 0, "a healthy build must have a seeded catalogue"


@pytest.mark.smoke
def test_product_listing_returns_the_seeded_catalogue(api):
    """TC-PROD-002: the catalogue is readable without authentication."""
    response = api.list_products()

    assert_status(response, 200, "GET /api/products")
    body = response.json()
    assert body["total"] >= 10
    assert len(body["items"]) == min(body["total"], body["page_size"])

    first = body["items"][0]
    for field in ("id", "sku", "name", "category", "price_cents", "price", "stock", "in_stock"):
        assert field in first, f"the product schema is missing {field!r}"
    assert first["price"] == round(first["price_cents"] / 100, 2), "the decimal price must match the cent price"


@pytest.mark.regression
def test_a_single_product_can_be_fetched_by_id(api):
    """TC-PROD-003: detail retrieval agrees with the listing."""
    listed = api.list_products(q=builders.KEYBOARD_SKU).json()["items"][0]

    response = api.get_product(listed["id"])
    assert_status(response, 200, f"GET /api/products/{listed['id']}")
    assert response["sku"] == builders.KEYBOARD_SKU
    assert response["price_cents"] == listed["price_cents"]


@pytest.mark.negative
def test_an_unknown_product_id_returns_not_found(api):
    """TC-PROD-010: unknown resources are reported, never fabricated."""
    response = api.get_product(999_999)

    assert_status(response, 404, "GET a product id that does not exist")
    assert "not found" in response.detail.lower()


@pytest.mark.negative
@pytest.mark.parametrize("product_id", ["abc", "1.5", "-1", "%20"], ids=["letters", "decimal", "negative", "encoded_space"])
def test_a_non_integer_product_id_is_rejected(api, product_id):
    """TC-PROD-011: path parameter typing is enforced."""
    response = api.get(f"/api/products/{product_id}", authenticate=False)

    assert response.status in (404, 422), (
        f"Product id {product_id!r} returned {response.status}; a non-integer id must be a 404 or 422."
    )


@pytest.mark.regression
def test_search_matches_on_both_name_and_sku(api):
    """TC-PROD-020: free-text search covers both documented fields."""
    by_name = api.list_products(q="Keyboard")
    by_sku = api.list_products(q=builders.KEYBOARD_SKU)

    assert_status(by_name, 200, "search by name")
    assert_status(by_sku, 200, "search by SKU")
    assert by_name.json()["total"] >= 1
    assert by_sku.json()["total"] == 1
    assert by_sku.json()["items"][0]["sku"] == builders.KEYBOARD_SKU


@pytest.mark.regression
def test_search_with_no_matches_returns_an_empty_page_not_an_error(api):
    """TC-PROD-021: an empty result set is a success, not a 404."""
    response = api.list_products(q="zzz-no-such-product-zzz")

    assert_status(response, 200, "search with a term that matches nothing")
    body = response.json()
    assert body["total"] == 0
    assert body["items"] == []
    assert body["pages"] == 0


@pytest.mark.regression
def test_category_filter_returns_only_that_category(api):
    """TC-PROD-022: filtering is exact, not a substring match."""
    categories = api.categories()
    assert_status(categories, 200, "GET /api/products/categories")
    category = categories.json()[0]

    response = api.list_products(category=category)
    assert_status(response, 200, f"filter by category {category}")
    assert response.json()["total"] > 0
    assert all(item["category"] == category for item in response.json()["items"])


@pytest.mark.regression
def test_in_stock_filter_excludes_unavailable_products(api):
    """TC-PROD-023: the out-of-stock dock must not appear."""
    unfiltered = api.list_products(page_size=100)
    filtered = api.list_products(in_stock_only=True, page_size=100)

    assert builders.OUT_OF_STOCK_SKU in [i["sku"] for i in unfiltered.json()["items"]]
    assert builders.OUT_OF_STOCK_SKU not in [i["sku"] for i in filtered.json()["items"]]
    assert all(item["stock"] > 0 for item in filtered.json()["items"])


@pytest.mark.regression
def test_sorting_by_price_returns_ascending_prices(api):
    """TC-PROD-024: sort order is actually applied."""
    response = api.list_products(sort="price", page_size=100)

    assert_status(response, 200, "sort by price")
    prices = [item["price_cents"] for item in response.json()["items"]]
    assert prices == sorted(prices), f"prices were not ascending: {prices}"


@pytest.mark.boundary
@pytest.mark.parametrize("page_size", [1, 2, 10, 100], ids=["one", "two", "ten", "max"])
def test_pagination_honours_the_requested_page_size(api, page_size):
    """TC-PROD-030: page_size is respected across its whole valid range."""
    response = api.list_products(page_size=page_size, page=1)

    assert_status(response, 200, f"page_size={page_size}")
    body = response.json()
    assert len(body["items"]) <= page_size
    assert body["page_size"] == page_size
    assert body["pages"] == (body["total"] + page_size - 1) // page_size


@pytest.mark.boundary
@pytest.mark.negative
@pytest.mark.parametrize("page_size", [0, -1, 101, 10_000], ids=["zero", "negative", "one_over_max", "far_over_max"])
def test_page_size_outside_the_documented_range_is_rejected(api, page_size):
    """TC-PROD-031: the other half of the page_size boundary."""
    response = api.list_products(page_size=page_size)

    assert response.status == 422, (
        f"page_size={page_size} is outside the documented 1..100 range but returned {response.status}."
    )


@pytest.mark.boundary
def test_requesting_a_page_beyond_the_last_returns_an_empty_page(api):
    """TC-PROD-032: over-paging is an empty result, not an error."""
    response = api.list_products(page=9999, page_size=10)

    assert_status(response, 200, "request a page far beyond the end")
    assert response.json()["items"] == []
    assert response.json()["total"] > 0, "the total must still report the real catalogue size"


@pytest.mark.boundary
def test_pages_do_not_overlap_or_skip_products(api):
    """TC-PROD-033: paging through the catalogue yields each product once."""
    first = api.list_products(page=1, page_size=4, sort="name").json()
    second = api.list_products(page=2, page_size=4, sort="name").json()

    first_ids = [i["id"] for i in first["items"]]
    second_ids = [i["id"] for i in second["items"]]
    assert not set(first_ids) & set(second_ids), "the same product appeared on two pages"

    everything = api.list_products(page_size=100, sort="name").json()["items"]
    assert [i["id"] for i in everything][:8] == first_ids + second_ids


@pytest.mark.negative
def test_an_inverted_price_range_is_rejected(api):
    """TC-PROD-034: min above max is a client error, not an empty list."""
    response = api.list_products(min_price_cents=50_000, max_price_cents=100)

    assert_status(response, 400, "min_price_cents greater than max_price_cents")


@pytest.mark.boundary
def test_price_filters_are_inclusive_at_both_bounds(api):
    """TC-PROD-035: the documented range is inclusive on both ends."""
    keyboard = api.list_products(q=builders.KEYBOARD_SKU).json()["items"][0]
    exact = keyboard["price_cents"]

    response = api.list_products(min_price_cents=exact, max_price_cents=exact)
    assert_status(response, 200, "an exact-price window")
    assert builders.KEYBOARD_SKU in [i["sku"] for i in response.json()["items"]], (
        f"A product priced at exactly {exact} was excluded by an inclusive {exact}..{exact} filter."
    )


@pytest.mark.negative
@pytest.mark.parametrize("label,payload", builders.XSS_STRINGS, ids=[c[0] for c in builders.XSS_STRINGS])
def test_search_terms_containing_markup_are_handled_as_data(api, label, payload):
    """TC-PROD-036: markup in a query string must not break the endpoint."""
    response = api.list_products(q=payload)

    assert_status(response, 200, f"search containing {label}")
    assert response.json()["total"] == 0, "markup should not match a real product"


@pytest.mark.negative
def test_creating_a_product_with_a_duplicate_sku_is_a_conflict(admin_api):
    """TC-PROD-040: the SKU uniqueness constraint is enforced by the API."""
    payload = builders.ProductBuilder().build()
    assert_status(admin_api.create_product(**payload), 201, "first creation")

    duplicate = admin_api.create_product(**payload)
    assert_status(duplicate, 409, "second creation with the same SKU")


@pytest.mark.negative
@pytest.mark.boundary
@pytest.mark.parametrize(
    "field,value",
    [("price_cents", -1), ("stock", -5), ("sku", "ab"), ("name", ""), ("price_cents", 999_999_999)],
    ids=["negative_price", "negative_stock", "sku_too_short", "blank_name", "price_over_max"],
)
def test_product_creation_validates_its_fields(admin_api, field, value):
    """TC-PROD-041: every documented constraint on the create schema."""
    payload = builders.ProductBuilder().build()
    payload[field] = value

    response = admin_api.create_product(**payload)
    assert response.status == 422, (
        f"{field}={value!r} violates the documented schema but was accepted with {response.status}."
    )
