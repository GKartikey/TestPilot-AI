"""Shopping cart: add, update, remove, apply coupon."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status

from ..config import settings
from ..deps import current_user, get_db
from ..pricing import Line, compute_totals, has_sufficient_stock
from ..schemas import CartItemIn, CartItemOut, CartOut, CartTotals, CouponApply

router = APIRouter(prefix="/api/cart", tags=["cart"])


def _cart_id(conn: sqlite3.Connection, user_id: int) -> int:
    conn.execute("INSERT OR IGNORE INTO carts (user_id) VALUES (?)", (user_id,))
    return conn.execute("SELECT id FROM carts WHERE user_id = ?", (user_id,)).fetchone()["id"]


def _coupon(conn: sqlite3.Connection, code: str | None) -> sqlite3.Row | None:
    if not code:
        return None
    return conn.execute("SELECT * FROM coupons WHERE code = ? AND is_active = 1", (code,)).fetchone()


def build_cart(conn: sqlite3.Connection, user_id: int) -> CartOut:
    cart = conn.execute("SELECT * FROM carts WHERE user_id = ?", (user_id,)).fetchone()
    if cart is None:
        empty = compute_totals([])
        return CartOut(items=[], coupon=None, totals=CartTotals(**empty.as_dict()))

    rows = conn.execute(
        """
        SELECT ci.product_id, ci.quantity, p.sku, p.name, p.price_cents
        FROM cart_items ci
        JOIN products p ON p.id = ci.product_id
        WHERE ci.cart_id = ?
        ORDER BY p.name
        """,
        (cart["id"],),
    ).fetchall()

    items = [
        CartItemOut(
            product_id=r["product_id"],
            sku=r["sku"],
            name=r["name"],
            unit_price_cents=r["price_cents"],
            quantity=r["quantity"],
            line_total_cents=r["price_cents"] * r["quantity"],
        )
        for r in rows
    ]
    coupon = _coupon(conn, cart["coupon"])
    totals = compute_totals(
        [Line(i.product_id, i.unit_price_cents, i.quantity) for i in items],
        percent_off=coupon["percent_off"] if coupon else 0,
        min_spend_cents=coupon["min_spend_cents"] if coupon else 0,
    )
    return CartOut(items=items, coupon=cart["coupon"], totals=CartTotals(**totals.as_dict()))


@router.get("", response_model=CartOut)
def get_cart(user: sqlite3.Row = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)) -> CartOut:
    return build_cart(conn, user["id"])


@router.post("/items", response_model=CartOut, status_code=status.HTTP_201_CREATED)
def add_item(
    payload: CartItemIn,
    user: sqlite3.Row = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> CartOut:
    if payload.quantity < settings.min_cart_quantity:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"quantity must be at least {settings.min_cart_quantity}",
        )
    if payload.quantity > settings.max_cart_quantity:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"quantity must not exceed {settings.max_cart_quantity}",
        )

    product = conn.execute(
        "SELECT * FROM products WHERE id = ? AND is_active = 1", (payload.product_id,)
    ).fetchone()
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Product {payload.product_id} was not found")

    cart_id = _cart_id(conn, user["id"])
    existing = conn.execute(
        "SELECT quantity FROM cart_items WHERE cart_id = ? AND product_id = ?", (cart_id, payload.product_id)
    ).fetchone()
    new_quantity = (existing["quantity"] if existing else 0) + payload.quantity

    if new_quantity > settings.max_cart_quantity:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"cart quantity for a product must not exceed {settings.max_cart_quantity}",
        )
    if not has_sufficient_stock(product["stock"], new_quantity):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Only {product['stock']} unit(s) of {product['sku']} remain in stock",
        )

    conn.execute(
        """
        INSERT INTO cart_items (cart_id, product_id, quantity) VALUES (?, ?, ?)
        ON CONFLICT (cart_id, product_id) DO UPDATE SET quantity = excluded.quantity
        """,
        (cart_id, payload.product_id, new_quantity),
    )
    conn.execute("UPDATE carts SET updated_at = datetime('now') WHERE id = ?", (cart_id,))
    return build_cart(conn, user["id"])


@router.patch("/items/{product_id}", response_model=CartOut)
def update_item(
    product_id: int,
    payload: CartItemIn,
    user: sqlite3.Row = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> CartOut:
    cart_id = _cart_id(conn, user["id"])
    existing = conn.execute(
        "SELECT * FROM cart_items WHERE cart_id = ? AND product_id = ?", (cart_id, product_id)
    ).fetchone()
    if existing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="That product is not in the cart")

    if payload.quantity == 0:
        conn.execute("DELETE FROM cart_items WHERE id = ?", (existing["id"],))
        return build_cart(conn, user["id"])

    if not (settings.min_cart_quantity <= payload.quantity <= settings.max_cart_quantity):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"quantity must be between {settings.min_cart_quantity} and {settings.max_cart_quantity}",
        )
    product = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    if not has_sufficient_stock(product["stock"], payload.quantity):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Only {product['stock']} unit(s) of {product['sku']} remain in stock",
        )

    conn.execute("UPDATE cart_items SET quantity = ? WHERE id = ?", (payload.quantity, existing["id"]))
    return build_cart(conn, user["id"])


@router.delete("/items/{product_id}", response_model=CartOut)
def remove_item(
    product_id: int,
    user: sqlite3.Row = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> CartOut:
    cart_id = _cart_id(conn, user["id"])
    cursor = conn.execute("DELETE FROM cart_items WHERE cart_id = ? AND product_id = ?", (cart_id, product_id))
    if cursor.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="That product is not in the cart")
    return build_cart(conn, user["id"])


@router.post("/coupon", response_model=CartOut)
def apply_coupon(
    payload: CouponApply,
    user: sqlite3.Row = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> CartOut:
    code = (payload.code or "").strip().upper()
    coupon = _coupon(conn, code)
    if coupon is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Coupon {code or '(blank)'} is not valid")

    cart_id = _cart_id(conn, user["id"])
    cart = build_cart(conn, user["id"])
    if cart.totals.subtotal_cents < coupon["min_spend_cents"]:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Coupon {code} requires a minimum spend of {coupon['min_spend_cents']} cents",
        )
    conn.execute("UPDATE carts SET coupon = ? WHERE id = ?", (code, cart_id))
    return build_cart(conn, user["id"])


@router.delete("", response_model=CartOut)
def clear_cart(user: sqlite3.Row = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)) -> CartOut:
    cart_id = _cart_id(conn, user["id"])
    conn.execute("DELETE FROM cart_items WHERE cart_id = ?", (cart_id,))
    conn.execute("UPDATE carts SET coupon = NULL WHERE id = ?", (cart_id,))
    return build_cart(conn, user["id"])
