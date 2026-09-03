"""Shared fixtures for the whole suite.

Scope discipline is the thing to notice here:

  session  the application server and the browser -- expensive, started once
  module   nothing; module scope hides ordering bugs
  function every client, page and browser context -- cheap, and isolated

Function-scoped browser *contexts* (not browsers) give each UI test a
clean cookie jar and localStorage for a few milliseconds, which is what
lets the suite run in any order and in parallel.
"""
from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterator

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from framework.clients.api_client import ShopNestClient  # noqa: E402
from framework.clients.db_client import DbClient  # noqa: E402
from framework.data import builders  # noqa: E402
from framework.utils.helpers import port_is_open, wait_until  # noqa: E402
from testpilot.config import ARTIFACTS, SCREENSHOTS_DIR, TRACES_DIR, ensure_dirs, get_environment  # noqa: E402

pytest_plugins = ["testpilot.plugins.pytest_testpilot"]


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--external-app",
        action="store_true",
        default=os.getenv("TESTPILOT_EXTERNAL_APP", "").lower() in {"1", "true", "yes"},
        help="Do not start ShopNest; assume it is already running at the configured base_url.",
    )
    parser.addoption(
        "--tp-trace",
        action="store",
        default=os.getenv("TESTPILOT_TRACE", "retain-on-failure"),
        choices=["off", "on", "retain-on-failure"],
        help="Playwright tracing policy.",
    )


# ------------------------------------------------------ environment ----

@pytest.fixture(scope="session")
def env():
    """The resolved environment configuration for this run."""
    ensure_dirs()
    return get_environment()


@pytest.fixture(scope="session")
def base_url(app_server) -> str:
    return app_server


# ---------------------------------------------------- the SUT server ---

def _wait_for_health(url: str, timeout: float = 45.0) -> None:
    """Wait until *ShopNest specifically* is answering at this URL.

    Checking only for `{"status": "ok"}` is not enough: any unrelated
    service that happens to hold the port will satisfy it, and the whole
    suite then runs against the wrong host and fails with a confusing
    wall of 404s. The service name is what makes this check honest.
    """
    import httpx

    def healthy() -> bool:
        response = httpx.get(f"{url}/health", timeout=3)
        if response.status_code != 200:
            return False
        body = response.json()
        if body.get("service") != "ShopNest":
            raise RuntimeError(
                f"Something other than ShopNest is listening on {url}. "
                f"Its /health returned {body!r}. Stop that service, or point TestPilot "
                f"elsewhere with TESTPILOT_BASE_URL=http://127.0.0.1:<free port>."
            )
        return body.get("status") == "ok"

    wait_until(healthy, timeout=timeout, interval=0.4, message=f"ShopNest never became healthy at {url}")


@pytest.fixture(scope="session")
def app_server(request: pytest.FixtureRequest, env) -> Iterator[str]:
    """Start ShopNest for the session, or attach to a running instance.

    Owning the server lifecycle in a fixture is what makes `pytest` a
    one-command entry point locally and in CI alike -- no separate
    "start the app first" step that somebody forgets.
    """
    url = env.base_url.rstrip("/")
    host = re.sub(r"^https?://", "", url).split(":")[0]
    port = int(url.rsplit(":", 1)[-1]) if ":" in url.rsplit("/", 1)[-1] else 80

    if request.config.getoption("--external-app") or port_is_open(host, port):
        _wait_for_health(url)
        yield url
        return

    db_path = ROOT / env.db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()  # a known-clean database for every session
    for sidecar in (f"{db_path}-wal", f"{db_path}-shm"):
        Path(sidecar).unlink(missing_ok=True)

    environ = {
        **os.environ,
        "SHOPNEST_DB": str(db_path),
        "SHOPNEST_HOST": host,
        "SHOPNEST_PORT": str(port),
        "SHOPNEST_FAULT_PROFILE": env.fault_profile,
        "PYTHONPATH": str(ROOT),
    }
    # The server's output goes to a file, never to an unread PIPE. Nobody
    # drains a PIPE during the run, so once the OS buffer fills the server
    # blocks on write and silently stops answering mid-suite.
    ensure_dirs()
    log_path = ARTIFACTS / "shopnest-server.log"
    log_handle = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "shopnest.main:app", "--host", host, "--port", str(port), "--log-level", "warning"],
        cwd=str(ROOT),
        env=environ,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    try:
        _wait_for_health(url)
    except Exception as exc:
        process.terminate()
        log_handle.close()
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-3000:] if log_path.exists() else ""
        pytest.fail(f"Could not start ShopNest at {url}: {exc}\n{tail}")

    yield url

    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:  # pragma: no cover
        process.kill()
    finally:
        log_handle.close()


# -------------------------------------------------------- API clients ---

@pytest.fixture
def api(base_url: str, request: pytest.FixtureRequest) -> Iterator[ShopNestClient]:
    """An anonymous client. Its HTTP history is attached to failures."""
    client = ShopNestClient(base_url=base_url)
    yield client
    _attach_history(request, client)
    client.close()


@pytest.fixture
def customer_api(base_url: str, request: pytest.FixtureRequest) -> Iterator[ShopNestClient]:
    """A client authenticated as the seeded customer, with an empty cart.

    Clearing the cart on the way in *and* out means a test never inherits
    another test's basket, which is the most common source of order-
    dependent failures in ecommerce suites.
    """
    client = ShopNestClient(base_url=base_url)
    client.authenticate(builders.SEEDED_CUSTOMER["email"], builders.SEEDED_CUSTOMER["password"])
    client.clear_cart()
    client.clear_history()
    yield client
    try:
        client.clear_cart()
    finally:
        _attach_history(request, client)
        client.close()


@pytest.fixture
def second_customer_api(base_url: str, request: pytest.FixtureRequest) -> Iterator[ShopNestClient]:
    """A different customer, for tenancy and isolation tests."""
    client = ShopNestClient(base_url=base_url)
    client.authenticate(builders.SEEDED_SECOND_CUSTOMER["email"], builders.SEEDED_SECOND_CUSTOMER["password"])
    client.clear_cart()
    client.clear_history()
    yield client
    try:
        client.clear_cart()
    finally:
        _attach_history(request, client)
        client.close()


@pytest.fixture
def admin_api(base_url: str, request: pytest.FixtureRequest) -> Iterator[ShopNestClient]:
    client = ShopNestClient(base_url=base_url)
    client.authenticate(builders.SEEDED_ADMIN["email"], builders.SEEDED_ADMIN["password"])
    client.clear_history()
    yield client
    _attach_history(request, client)
    client.close()


def _attach_history(request: pytest.FixtureRequest, client: ShopNestClient) -> None:
    """Park the HTTP conversation on the item so the recorder keeps it."""
    report = getattr(request.node, "_tp_report_call", None)
    if report is not None and report.failed and client.history:
        existing = getattr(request.node, "_tp_requests", None) or []
        request.node._tp_requests = [*existing, *client.interactions()]


# ------------------------------------------------------- DB fixtures ---

@pytest.fixture(scope="session")
def db(env, app_server) -> DbClient:
    """SQL access to the same database the running app is using."""
    return DbClient(db_path=ROOT / env.db_path)


# ------------------------------------------------------- Playwright ----

@pytest.fixture(scope="session")
def playwright_instance() -> Iterator[Any]:
    playwright = pytest.importorskip(
        "playwright.sync_api", reason="Playwright is not installed; UI tests are skipped."
    )
    with playwright.sync_playwright() as instance:
        yield instance


@pytest.fixture(scope="session")
def browser(playwright_instance, env) -> Iterator[Any]:
    """One browser per session; contexts give per-test isolation."""
    browser_name = os.getenv("TESTPILOT_BROWSER", "chromium")
    try:
        launcher = getattr(playwright_instance, browser_name)
        instance = launcher.launch(headless=env.headless, slow_mo=env.slow_mo_ms)
    except Exception as exc:
        pytest.skip(f"Could not launch {browser_name}: {exc}. Run 'playwright install {browser_name}'.")
    yield instance
    instance.close()


@pytest.fixture
def context(browser, env, request: pytest.FixtureRequest) -> Iterator[Any]:
    """A fresh browser context per test, with tracing and video policy.

    The trace is started for every test but only *kept* when the test
    fails, which is the balance that keeps CI storage sane while still
    giving a full timeline for anything that breaks.
    """
    ensure_dirs()
    trace_mode = request.config.getoption("--tp-trace")
    ctx = browser.new_context(
        viewport={"width": 1366, "height": 900},
        ignore_https_errors=True,
        record_video_dir=None,
    )
    ctx.set_default_timeout(env.default_timeout_ms)

    tracing = trace_mode != "off"
    if tracing:
        ctx.tracing.start(screenshots=True, snapshots=True, sources=True)

    yield ctx

    report = getattr(request.node, "_tp_report_call", None)
    failed = report is not None and report.failed
    if tracing:
        if trace_mode == "on" or (trace_mode == "retain-on-failure" and failed):
            trace_path = TRACES_DIR / f"{_safe_name(request.node.nodeid)}.zip"
            try:
                ctx.tracing.stop(path=str(trace_path))
                request.node._tp_trace = str(trace_path.relative_to(ROOT))
            except Exception:
                ctx.tracing.stop()
        else:
            ctx.tracing.stop()
    ctx.close()


@pytest.fixture
def page(context, request: pytest.FixtureRequest) -> Iterator[Any]:
    """A page that screenshots itself when its test fails."""
    browser_page = context.new_page()
    console_errors: list[str] = []
    browser_page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    browser_page.on("pageerror", lambda err: console_errors.append(str(err)))

    yield browser_page

    report = getattr(request.node, "_tp_report_call", None)
    if report is not None and report.failed:
        shot_path = SCREENSHOTS_DIR / f"{_safe_name(request.node.nodeid)}.png"
        try:
            browser_page.screenshot(path=str(shot_path), full_page=True)
            request.node._tp_screenshot = str(shot_path.relative_to(ROOT))
        except Exception:
            pass  # a screenshot failure must never mask the real failure
        if console_errors:
            existing = getattr(request.node, "_tp_requests", None) or []
            request.node._tp_requests = [
                *existing,
                {"type": "browser_console_errors", "entries": console_errors[:20]},
            ]
    browser_page.close()


def _safe_name(nodeid: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", nodeid).strip("_")
    return f"{stem[:120]}_{int(time.time() * 1000) % 100000}"


# ------------------------------------------------------ page objects ---

@pytest.fixture
def login_page(page, base_url):
    from framework.pages.login_page import LoginPage

    return LoginPage(page, base_url)


@pytest.fixture
def products_page(page, base_url):
    from framework.pages.products_page import ProductsPage

    return ProductsPage(page, base_url)


@pytest.fixture
def cart_page(page, base_url):
    from framework.pages.cart_page import CartPage

    return CartPage(page, base_url)


@pytest.fixture
def orders_page(page, base_url):
    from framework.pages.cart_page import OrdersPage

    return OrdersPage(page, base_url)


@pytest.fixture
def signed_in_products_page(page, base_url, customer_api, products_page):
    """A products page with an authenticated session already seeded.

    Depends on `customer_api` purely for the token, so UI tests that are
    not about login skip the form entirely.
    """
    products_page.set_session(
        customer_api.token,
        {"id": 0, "email": builders.SEEDED_CUSTOMER["email"], "full_name": "Casey Customer", "role": "customer"},
    )
    return products_page.open()


# --------------------------------------------------------- cleanup -----

@pytest.fixture(scope="session", autouse=True)
def clean_artifacts_dir() -> Iterator[None]:
    """Start each session with fresh screenshots and traces."""
    if os.getenv("TESTPILOT_KEEP_ARTIFACTS", "").lower() not in {"1", "true", "yes"}:
        for directory in (SCREENSHOTS_DIR, TRACES_DIR):
            if directory.exists():
                shutil.rmtree(directory, ignore_errors=True)
    ensure_dirs()
    yield


@pytest.fixture
def unused_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
