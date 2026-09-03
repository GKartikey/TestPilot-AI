"""Catalogue browsing and (admin-only) catalogue maintenance."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..deps import get_db, require_admin
from ..schemas import ProductCreate, ProductOut, ProductPage

router = APIRouter(prefix="/api/products", tags=["products"])

MAX_PAGE_SIZE = 100
SORTABLE = {"name": "name", "price": "price_cents", "newest": "created_at"}


def _to_out(row: sqlite3.Row) -> ProductOut:
    return ProductOut(
        id=row["id"],
        sku=row["sku"],
        name=row["name"],
        description=row["description"],
        category=row["category"],
        price_cents=row["price_cents"],
        price=round(row["price_cents"] / 100, 2),
        stock=row["stock"],
        in_stock=row["stock"] > 0,
    )


@router.get("", response_model=ProductPage)
def list_products(
    conn: sqlite3.Connection = Depends(get_db),
    q: str | None = Query(default=None, max_length=100, description="Free-text search over name and SKU"),
    category: str | None = Query(default=None, max_length=40),
    min_price_cents: int | None = Query(default=None, ge=0),
    max_price_cents: int | None = Query(default=None, ge=0),
    in_stock_only: bool = Query(default=False),
    sort: str = Query(default="name", pattern="^(name|price|newest)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=MAX_PAGE_SIZE),
) -> ProductPage:
    if min_price_cents is not None and max_price_cents is not None and min_price_cents > max_price_cents:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="min_price_cents must not exceed max_price_cents")

    where = ["is_active = 1"]
    params: list[object] = []
    if q:
        where.append("(name LIKE ? OR sku LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])
    if category:
        where.append("category = ?")
        params.append(category)
    if min_price_cents is not None:
        where.append("price_cents >= ?")
        params.append(min_price_cents)
    if max_price_cents is not None:
        where.append("price_cents <= ?")
        params.append(max_price_cents)
    if in_stock_only:
        where.append("stock > 0")

    clause = " AND ".join(where)
    total = conn.execute(f"SELECT COUNT(*) AS n FROM products WHERE {clause}", params).fetchone()["n"]
    order_by = SORTABLE[sort]
    direction = "DESC" if sort == "newest" else "ASC"
    rows = conn.execute(
        f"SELECT * FROM products WHERE {clause} ORDER BY {order_by} {direction}, id ASC LIMIT ? OFFSET ?",
        [*params, page_size, (page - 1) * page_size],
    ).fetchall()

    pages = (total + page_size - 1) // page_size if total else 0
    return ProductPage(
        items=[_to_out(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.get("/categories", response_model=list[str])
def categories(conn: sqlite3.Connection = Depends(get_db)) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT category FROM products WHERE is_active = 1 ORDER BY category"
    ).fetchall()
    return [r["category"] for r in rows]


@router.get("/{product_id}", response_model=ProductOut)
def get_product(product_id: int, conn: sqlite3.Connection = Depends(get_db)) -> ProductOut:
    row = conn.execute("SELECT * FROM products WHERE id = ? AND is_active = 1", (product_id,)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Product {product_id} was not found")
    return _to_out(row)


@router.post("", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(
    payload: ProductCreate,
    conn: sqlite3.Connection = Depends(get_db),
    _admin: sqlite3.Row = Depends(require_admin),
) -> ProductOut:
    clash = conn.execute("SELECT id FROM products WHERE sku = ?", (payload.sku,)).fetchone()
    if clash:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"SKU {payload.sku} already exists")
    cursor = conn.execute(
        "INSERT INTO products (sku, name, description, category, price_cents, stock) VALUES (?, ?, ?, ?, ?, ?)",
        (payload.sku, payload.name, payload.description, payload.category, payload.price_cents, payload.stock),
    )
    row = conn.execute("SELECT * FROM products WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return _to_out(row)
