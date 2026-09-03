"""Request/response contracts for the ShopNest API."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    email: str = Field(..., examples=["ada@example.com"])
    full_name: str = Field(..., min_length=1, max_length=120)
    password: str = Field(..., examples=["Passw0rd123"])


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: "UserPublic"


class UserPublic(BaseModel):
    id: int
    email: str
    full_name: str
    role: str


class ProductOut(BaseModel):
    id: int
    sku: str
    name: str
    description: str
    category: str
    price_cents: int
    price: float
    stock: int
    in_stock: bool


class ProductPage(BaseModel):
    items: list[ProductOut]
    total: int
    page: int
    page_size: int
    pages: int


class ProductCreate(BaseModel):
    sku: str = Field(..., min_length=3, max_length=32)
    name: str = Field(..., min_length=1, max_length=120)
    description: str = ""
    category: str = Field(..., min_length=1, max_length=40)
    price_cents: int = Field(..., ge=0, le=100_000_00)
    stock: int = Field(0, ge=0, le=100_000)


class CartItemIn(BaseModel):
    product_id: int
    quantity: int = Field(..., description="1..10 inclusive")


class CartItemOut(BaseModel):
    product_id: int
    sku: str
    name: str
    unit_price_cents: int
    quantity: int
    line_total_cents: int


class CartTotals(BaseModel):
    subtotal_cents: int
    discount_cents: int
    shipping_cents: int
    tax_cents: int
    total_cents: int


class CartOut(BaseModel):
    items: list[CartItemOut]
    coupon: Optional[str] = None
    totals: CartTotals


class CouponApply(BaseModel):
    code: str


class OrderItemOut(BaseModel):
    sku: str
    name: str
    quantity: int
    unit_price_cents: int
    line_total_cents: int


class OrderOut(BaseModel):
    id: int
    order_number: str
    status: str
    subtotal_cents: int
    discount_cents: int
    shipping_cents: int
    tax_cents: int
    total_cents: int
    coupon: Optional[str] = None
    created_at: str
    items: list[OrderItemOut] = []


class ErrorResponse(BaseModel):
    detail: str
    code: str = "error"
    errors: list[str] = []


TokenResponse.model_rebuild()
