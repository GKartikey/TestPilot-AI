"""ShopNest application entrypoint.

ShopNest is the *system under test*. It knows nothing about TestPilot;
the QA platform only ever talks to it over HTTP and SQL, exactly as it
would with a third-party service.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db as database
from .config import settings
from .routers import auth, cart, orders, products
from .seed import seed_database

STATIC_DIR = Path(__file__).parent / "static"

DESCRIPTION = """
ShopNest is a small but complete storefront API: accounts, catalogue,
cart, coupons and checkout. It exists so that the TestPilot QA platform
has a realistic, self-hostable target to exercise.

Set `SHOPNEST_FAULT_PROFILE` to one of `coupon_stacking`, `stock_oversell`,
`weak_auth` or `all` to launch a deliberately broken build.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    seed_database(only_if_empty=True)
    yield


app = FastAPI(
    title="ShopNest API",
    version=settings.version,
    description=DESCRIPTION,
    lifespan=lifespan,
)

app.include_router(auth.router)
app.include_router(products.router)
app.include_router(cart.router)
app.include_router(orders.router)


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Flatten FastAPI's validation errors into a single readable string.

    The test suite asserts on `detail` being a human-readable message for
    every 4xx, so schema failures and hand-rolled failures look alike.
    """
    parts = []
    for error in exc.errors():
        location = ".".join(str(p) for p in error.get("loc", []) if p != "body")
        parts.append(f"{location}: {error.get('msg')}" if location else str(error.get("msg")))
    return JSONResponse(status_code=422, content={"detail": "; ".join(parts) or "Invalid request"})


@app.get("/health", tags=["ops"])
def health() -> dict[str, object]:
    with database.session() as conn:
        product_count = conn.execute("SELECT COUNT(*) AS n FROM products").fetchone()["n"]
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.version,
        "products": product_count,
        "fault_profile": settings.fault_profile,
    }


# ---------------------------------------------------------------- UI ----
# Server-hosted static pages give the Playwright suite a real browser
# surface (forms, navigation, dynamic DOM) rather than a mocked one.

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _page(name: str) -> FileResponse:
    return FileResponse(STATIC_DIR / name)


@app.get("/", include_in_schema=False)
def ui_home() -> FileResponse:
    return _page("index.html")


@app.get("/login", include_in_schema=False)
def ui_login() -> FileResponse:
    return _page("login.html")


@app.get("/register", include_in_schema=False)
def ui_register() -> FileResponse:
    return _page("register.html")


@app.get("/products", include_in_schema=False)
def ui_products() -> FileResponse:
    return _page("products.html")


@app.get("/cart", include_in_schema=False)
def ui_cart() -> FileResponse:
    return _page("cart.html")


@app.get("/orders", include_in_schema=False)
def ui_orders() -> FileResponse:
    return _page("orders.html")


def run() -> None:  # pragma: no cover - convenience launcher
    import uvicorn

    uvicorn.run("shopnest.main:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":  # pragma: no cover
    run()
