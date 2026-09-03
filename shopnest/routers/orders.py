"""Checkout and order history.

Checkout is the highest-risk transaction in the application: it moves
money, decrements stock and must be atomic. It is therefore the anchor
of the smoke suite and the most heavily covered path in regression.
"""
from __future__ import annotations

import secrets
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status

from ..config import settings
from ..deps import current_user, get_db
from ..pricing import Line, compute_totals, has_sufficient_stock
from ..schemas import OrderItemOut, OrderOut

router = APIRouter(prefix="/api/orders", tags=["orders"])


def _order_number() -> str:
    return "SN-" + secrets.token_hex(4).upper()


def _load_order(conn: sqlite3.Connection, order_id: int) -> OrderOut:
    order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    items = conn.execute(
        """
        SELECT oi.sku, oi.quantity, oi.unit_price_cents, oi.line_total_cents, p.name
        FROM order_items oi
        JOIN products p ON p.id = oi.product_id
        WHERE oi.order_id = ?
        ORDER BY oi.id
        """,
        (order_id,),
    ).fetchall()
    return OrderOut(
        id=order["id"],
        order_number=order["order_number"],
        status=order["status"],
        subtotal_cents=order["subtotal_cents"],
        discount_cents=order["discount_cents"],
        shipping_cents=order["shipping_cents"],
        tax_cents=order["tax_cents"],
        total_cents=order["total_cents"],
        coupon=order["coupon"],
        created_at=order["created_at"],
        items=[
            OrderItemOut(
                sku=i["sku"],
                name=i["name"],
                quantity=i["quantity"],
                unit_price_cents=i["unit_price_cents"],
                line_total_cents=i["line_total_cents"],
            )
            for i in items
        ],
    )


@router.post("", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
def checkout(
    user: sqlite3.Row = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> OrderOut:
    cart = conn.execute("SELECT * FROM carts WHERE user_id = ?", (user["id"],)).fetchone()
    rows = (
        conn.execute(
            """
            SELECT ci.product_id, ci.quantity, p.sku, p.price_cents, p.stock, p.is_active
            FROM cart_items ci
            JOIN products p ON p.id = ci.product_id
            WHERE ci.cart_id = ?
            ORDER BY ci.id
            """,
            (cart["id"],),
        ).fetchall()
        if cart
        else []
    )
    if not rows:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Cannot check out an empty cart")

    for row in rows:
        if not row["is_active"]:
            raise HTTPException(
                status.HTTP_409_CONFLICT, detail=f"{row['sku']} is no longer available for purchase"
            )
        if not has_sufficient_stock(row["stock"], row["quantity"]):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=f"Only {row['stock']} unit(s) of {row['sku']} remain in stock",
            )

    coupon_row = (
        conn.execute("SELECT * FROM coupons WHERE code = ? AND is_active = 1", (cart["coupon"],)).fetchone()
        if cart["coupon"]
        else None
    )
    totals = compute_totals(
        [Line(r["product_id"], r["price_cents"], r["quantity"]) for r in rows],
        percent_off=coupon_row["percent_off"] if coupon_row else 0,
        min_spend_cents=coupon_row["min_spend_cents"] if coupon_row else 0,
    )

    # One transaction: order header, lines, stock decrement and cart
    # clear either all land or none of them do.
    conn.execute("BEGIN IMMEDIATE")
    try:
        cursor = conn.execute(
            """
            INSERT INTO orders (order_number, user_id, status, subtotal_cents, discount_cents,
                                shipping_cents, tax_cents, total_cents, coupon)
            VALUES (?, ?, 'PLACED', ?, ?, ?, ?, ?, ?)
            """,
            (
                _order_number(),
                user["id"],
                totals.subtotal_cents,
                totals.discount_cents,
                totals.shipping_cents,
                totals.tax_cents,
                totals.total_cents,
                cart["coupon"],
            ),
        )
        order_id = cursor.lastrowid
        for row in rows:
            conn.execute(
                """
                INSERT INTO order_items (order_id, product_id, sku, quantity,
                                         unit_price_cents, line_total_cents)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    order_id,
                    row["product_id"],
                    row["sku"],
                    row["quantity"],
                    row["price_cents"],
                    row["price_cents"] * row["quantity"],
                ),
            )
            conn.execute(
                "UPDATE products SET stock = MAX(stock - ?, 0) WHERE id = ?",
                (row["quantity"], row["product_id"]),
            )
        conn.execute("DELETE FROM cart_items WHERE cart_id = ?", (cart["id"],))
        conn.execute("UPDATE carts SET coupon = NULL WHERE id = ?", (cart["id"],))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    return _load_order(conn, order_id)


@router.get("", response_model=list[OrderOut])
def list_orders(
    user: sqlite3.Row = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> list[OrderOut]:
    if settings.fault_enabled("weak_auth"):
        # FAULT: missing tenant filter returns every customer's orders.
        rows = conn.execute("SELECT id FROM orders ORDER BY id DESC").fetchall()
    else:
        rows = conn.execute(
            "SELECT id FROM orders WHERE user_id = ? ORDER BY id DESC", (user["id"],)
        ).fetchall()
    return [_load_order(conn, r["id"]) for r in rows]


@router.get("/{order_id}", response_model=OrderOut)
def get_order(
    order_id: int,
    user: sqlite3.Row = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> OrderOut:
    row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Order {order_id} was not found")
    if row["user_id"] != user["id"] and user["role"] != "admin":
        # 404 rather than 403 so the endpoint does not confirm that an
        # order belonging to somebody else exists.
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Order {order_id} was not found")
    return _load_order(conn, order_id)


@router.post("/{order_id}/cancel", response_model=OrderOut)
def cancel_order(
    order_id: int,
    user: sqlite3.Row = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> OrderOut:
    row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if row is None or (row["user_id"] != user["id"] and user["role"] != "admin"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Order {order_id} was not found")
    if row["status"] == "SHIPPED":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="A shipped order cannot be cancelled")
    if row["status"] == "CANCELLED":
        return _load_order(conn, order_id)

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("UPDATE orders SET status = 'CANCELLED' WHERE id = ?", (order_id,))
        for item in conn.execute(
            "SELECT product_id, quantity FROM order_items WHERE order_id = ?", (order_id,)
        ).fetchall():
            conn.execute(
                "UPDATE products SET stock = stock + ? WHERE id = ?",
                (item["quantity"], item["product_id"]),
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return _load_order(conn, order_id)
