"""FastAPI dependencies: DB handles and the authenticated principal."""
from __future__ import annotations

import sqlite3
from typing import Iterator, Optional

from fastapi import Depends, Header, HTTPException, status

from . import db as database
from .security import TokenError, decode_access_token


def get_db() -> Iterator[sqlite3.Connection]:
    conn = database.connect()
    try:
        yield conn
    finally:
        conn.close()


def _unauthorised(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def current_user(
    authorization: Optional[str] = Header(default=None),
    conn: sqlite3.Connection = Depends(get_db),
) -> sqlite3.Row:
    if not authorization:
        raise _unauthorised("Missing Authorization header")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _unauthorised("Authorization header must use the Bearer scheme")
    try:
        payload = decode_access_token(token.strip())
    except TokenError as exc:
        raise _unauthorised(str(exc)) from exc

    row = conn.execute("SELECT * FROM users WHERE id = ?", (payload.get("sub"),)).fetchone()
    if row is None:
        raise _unauthorised("Token subject no longer exists")
    if not row["is_active"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Account is deactivated")
    return row


def require_admin(user: sqlite3.Row = Depends(current_user)) -> sqlite3.Row:
    if user["role"] != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Administrator role required")
    return user
