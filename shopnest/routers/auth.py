"""Registration, login and identity endpoints."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status

from ..config import settings
from ..deps import current_user, get_db
from ..schemas import LoginRequest, RegisterRequest, TokenResponse, UserPublic
from ..security import (
    create_access_token,
    hash_password,
    is_valid_email,
    password_problems,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _public(row: sqlite3.Row) -> UserPublic:
    return UserPublic(id=row["id"], email=row["email"], full_name=row["full_name"], role=row["role"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, conn: sqlite3.Connection = Depends(get_db)) -> TokenResponse:
    email = (payload.email or "").strip().lower()
    errors: list[str] = []
    if not is_valid_email(email):
        errors.append("email is not a valid address")
    if not (payload.full_name or "").strip():
        errors.append("full_name must not be blank")
    errors.extend(password_problems(payload.password or ""))
    if errors:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="; ".join(errors))

    existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Email is already registered")

    cursor = conn.execute(
        "INSERT INTO users (email, full_name, password_hash, role) VALUES (?, ?, ?, 'customer')",
        (email, payload.full_name.strip(), hash_password(payload.password)),
    )
    conn.execute("INSERT OR IGNORE INTO carts (user_id) VALUES (?)", (cursor.lastrowid,))
    row = conn.execute("SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)).fetchone()
    token = create_access_token(str(row["id"]), row["role"])
    return TokenResponse(
        access_token=token,
        expires_in=settings.access_token_minutes * 60,
        user=_public(row),
    )


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, conn: sqlite3.Connection = Depends(get_db)) -> TokenResponse:
    email = (payload.email or "").strip().lower()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

    # Same message and roughly the same work for unknown user and bad
    # password, so the endpoint does not leak which emails are registered.
    if row is None or not verify_password(payload.password or "", row["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    if not row["is_active"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Account is deactivated")

    conn.execute("INSERT OR IGNORE INTO carts (user_id) VALUES (?)", (row["id"],))
    token = create_access_token(str(row["id"]), row["role"])
    return TokenResponse(
        access_token=token,
        expires_in=settings.access_token_minutes * 60,
        user=_public(row),
    )


@router.get("/me", response_model=UserPublic)
def me(user: sqlite3.Row = Depends(current_user)) -> UserPublic:
    return _public(user)
