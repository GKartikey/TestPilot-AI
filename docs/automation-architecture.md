# Automation Architecture

How the pieces fit, and why each boundary is where it is.

---

## 1. The two systems

The most important structural decision in the project: **ShopNest and
TestPilot are separate systems that share no code.**

```
┌────────────────────────────┐         ┌────────────────────────────┐
│   ShopNest                 │         │   TestPilot                │
│   (system under test)      │         │   (QA platform)            │
│                            │  HTTP   │                            │
│   FastAPI + SQLite         │<────────│   pytest + Playwright      │
│   Browser UI               │  SQL    │   results store            │
│                            │<────────│   analytics, defects, AI   │
│   Knows nothing about      │         │   Treats ShopNest as a     │
│   TestPilot                │         │   third-party service      │
└────────────────────────────┘         └────────────────────────────┘
```

TestPilot reaches ShopNest only over HTTP and SQL — exactly as it would a
service written by another team in another language. Point
`TESTPILOT_BASE_URL` somewhere else and the platform tests that instead.

This is why the tests do not import `shopnest.pricing.compute_totals` to
check the pricing. An oracle that shares an implementation with the thing
it checks proves nothing: if the rounding rule is wrong in the
application, it would be wrong identically in the test and the suite
would stay green. `framework/utils/helpers.expected_totals` reimplements
the rules from the specification instead.

---

## 2. Layers

```
┌──────────────────────────────────────────────────────────────┐
│  tests/            The tests. Intent only. No selectors,     │
│                    no URLs, no SQL string building.          │
├──────────────────────────────────────────────────────────────┤
│  framework/pages/  Page objects. Expose state, take actions, │
│                    never assert.                             │
│  framework/clients/ API client and SQL client.               │
│  framework/data/   Builders and seeded constants.            │
│  framework/utils/  Waits, oracles, assertion helpers.        │
├──────────────────────────────────────────────────────────────┤
│  tests/conftest.py Fixtures: server lifecycle, browser,      │
│                    contexts, authenticated clients,          │
│                    screenshot and trace capture.             │
├──────────────────────────────────────────────────────────────┤
│  testpilot/        The platform: registry, store, runner,    │
│                    analytics, defects, reporting, AI.        │
└──────────────────────────────────────────────────────────────┘
```

The rule that keeps this honest: **a test may only call the layer
immediately below it.** A test that contains a CSS selector or a raw
`httpx` call has skipped a layer, and that is a review rejection.

---

## 3. Page Object Model

`BasePage` supplies navigation, readiness, and the shared page chrome;
each page subclass exposes that page's own elements and actions.

```python
class ProductsPage(BasePage):
    path = "/products"
    page_name = "products"

    def card_for(self, sku: str) -> Locator:
        return self.page.locator(f'[data-testid="product-card"][data-sku="{sku}"]')

    def add_to_cart(self, sku: str) -> "ProductsPage":
        card = self.card_for(sku)
        card.wait_for(state="visible", timeout=8_000)
        self.within(card, "add-to-cart").click()
        return self
```

Four rules, each with a reason:

**1. No assertions in page objects.** `add_to_cart` does not check that
the item was added. That is the test's job — and it is what lets the same
method serve the happy path, the out-of-stock rejection and the
quantity-cap boundary.

**2. Locators are `data-testid`.** Class names and visible text change
whenever someone edits copy. A test id is a contract with the
application; changing one is a breaking change.

**3. Methods return page objects**, so a journey reads as one sentence:

```python
orders = products.add_to_cart(KEYBOARD_SKU).go_to_cart().checkout()
```

**4. No sleeps.** Ever. Waiting is always waiting for a *condition*.

---

## 4. How the UI suite avoids being flaky

Flakiness is the reason most UI suites end up ignored, so it is designed
against directly.

**The application tells the tests when it is ready.** Each page sets
`data-ready="true"` on `<body>` once its initial fetches have rendered:

```javascript
function markReady(name) {
  document.body.setAttribute("data-page", name);
  document.body.setAttribute("data-ready", "true");
}
```

and the framework waits on exactly that:

```python
self.page.wait_for_selector(
    f'body[data-page="{self.page_name}"][data-ready="true"]', state="attached"
)
```

This beats `wait_for_load_state("networkidle")`, which is a guess about
the network, and it beats `sleep(2)`, which is a guess about everything.

**Per-test isolation without per-test cost.** The browser is
session-scoped — launching Chromium is expensive. The *context* is
function-scoped, and a context is cheap: each test gets a clean cookie
jar and empty `localStorage` in a few milliseconds. That combination is
what lets the suite run in any order and in parallel.

**Tests that are not about login do not use the login form.** They inject
a token that the `customer_api` fixture already obtained. Only
TC-UI-002 drives the form, because only that case is *about* the form.

---

## 5. Fixtures, and why the scopes are what they are

| Fixture | Scope | Why |
| --- | --- | --- |
| `app_server` | session | Starting the service takes seconds; doing it per test would dominate the run |
| `browser` | session | Launching Chromium is expensive |
| `db` | session | A connection factory, stateless |
| `context` | function | Cheap, and gives real per-test isolation |
| `page` | function | Screenshots the failure before it closes |
| `customer_api` | function | Clears the cart on entry *and* exit |

Nothing is module-scoped. Module scope is the classic source of
order-dependent suites: it makes tests share state within a file, and
the resulting failures depend on which tests you selected.

Two fixtures do real work at teardown:

- `page` takes a full-page screenshot when its test failed, and attaches
  any browser console errors.
- `context` stops tracing and *keeps* the trace only on failure — a full
  timeline for anything broken, without filling CI storage with traces of
  passing tests.

---

## 6. The API client

`ShopNestClient` gives tests intent-level methods
(`client.add_to_cart(product_id=3, quantity=2)`) and does three things
they should not each have to remember:

- **It never asserts.** It reports what happened; the test decides what
  is correct. The same client serves a test expecting 201 and a test
  expecting 409.
- **It records every request and response**, and the fixture attaches
  that conversation to a failing result — so a failure report contains
  the exact exchange that produced it.
- **It redacts credentials** before anything is logged or stored.

---

## 7. The SQL layer

`DbClient` is read-mostly by design. Tests that change state do it
through the API so that real business rules are exercised; direct writes
are reserved for setting up conditions the API cannot reach, such as
forcing a stock level.

Its reconciliation queries are the ones that catch what an API cannot:

```sql
-- Every order's stored total must equal its own components.
SELECT id, order_number, subtotal_cents, discount_cents,
       shipping_cents, tax_cents, total_cents
FROM orders
WHERE total_cents <> subtotal_cents - discount_cents + shipping_cents + tax_cents;
```

An endpoint can return `201 Created` and still write a wrong row. This
layer is the only one that notices.

---

## 8. Recording: how a pytest run becomes queryable

`testpilot/plugins/pytest_testpilot.py` is a pytest plugin that turns
each run into rows:

```
pytest run ──> plugin hooks ──> test_runs   (one row per suite execution)
                            └─> test_results (one row per test)
                                  ├─ outcome, duration, markers
                                  ├─ traceback and failure message
                                  ├─ screenshot path, trace path
                                  ├─ the HTTP conversation
                                  └─ the manual case id it traces to
```

Two design points worth noting:

**It is passive.** If the store is unreachable, the tests still run —
they simply are not recorded. A reporting layer must never turn a green
build red.

**It pins its database path at run start.** The platform's own unit tests
monkeypatch the store's globals to use a temporary database; without
pinning, the recorder would follow that monkeypatch and divert live
results into a test's temp directory. (That was a real bug, found by
noticing a 220-test run had recorded only 185 results.)

Once results are relational, questions that are normally log-scraping
exercises become one query each: which test is flakiest, is the pass rate
trending down, what are the failure hotspots, which documented cases have
never actually been executed.

---

## 9. The AI layer and its gate

```
                        ┌────────────────────┐
   Before execution     │  generate cases    │  from an OpenAPI spec
   (no evidence needed, │  suggest edge cases│  → always marked DRAFT
    no claims allowed)  └────────────────────┘

                        ┌────────────────────┐
   After execution      │  summarise failure │  ← Evidence bundle
   (evidence required)  │  classify failure  │  ← Evidence bundle
                        │  draft bug report  │  ← Evidence + triage
                        └────────────────────┘
```

`testpilot/ai/evidence.py` is the choke point. Every post-execution
feature takes an `Evidence` object built from a stored result, never a
free-text description. A claim is admissible only when a stored result
exists, its outcome is a failure, a message or traceback was captured,
and the run is attributable.

Two providers implement one interface. `AnthropicProvider` calls the
Claude API when `ANTHROPIC_API_KEY` is set; `HeuristicProvider` is
deterministic rule-based analysis needing no network. The fallback is not
a stub — it is real logic, it is what CI uses, and it is covered by its
own tests. Model output is additionally schema-validated, and anything
that does not match falls back to the heuristic rather than being passed
through.

---

## 10. Data flow, end to end

```
testcases/*.yaml  ──── registry ────┐
                                    ├──> tp run <suite>
testcases/suites.yaml ──────────────┘         │
                                              v
                                    pytest + fixtures
                                              │
                              ┌───────────────┼───────────────┐
                              v               v               v
                         API client      Page objects     SQL client
                              │               │               │
                              └──────> ShopNest (SUT) <───────┘
                                              │
                                    results, screenshots, traces
                                              v
                                     testpilot.db (store)
                                              │
                    ┌─────────────────────────┼─────────────────────┐
                    v                         v                     v
              analytics                  reporting              AI + evidence
           pass rate, flakes        HTML/JSON/JUnit/CSV/MD       gate → defects
```

---

## 11. Repository map

```
TestPilot-AI/
├── shopnest/            System under test
│   ├── main.py            FastAPI app, UI routes
│   ├── routers/           auth, products, cart, orders
│   ├── pricing.py         money rules, single source of truth
│   ├── db.py              schema and connections
│   ├── seed.py            deterministic seed data
│   └── static/            browser UI with data-testid hooks
│
├── testpilot/           The QA platform
│   ├── registry.py        test case management
│   ├── store.py           results storage
│   ├── runner.py          suite execution
│   ├── analytics.py       pass/fail, flakes, hotspots
│   ├── defects.py         lifecycle state machine
│   ├── reporting/         five export formats
│   ├── plugins/           the pytest recording plugin
│   ├── ai/                evidence gate + AI features
│   ├── cli.py             the `tp` command line
│   └── api.py             TestPilot's own REST API
│
├── framework/           Automation framework
│   ├── pages/             page object model
│   ├── clients/           API and SQL clients
│   ├── data/              builders and constants
│   └── utils/             waits, oracles, assertions
│
├── tests/               The tests themselves
│   ├── conftest.py        fixtures
│   ├── api/  ui/  db/  framework/
│
├── testcases/           125 documented cases + suite definitions
├── config/              environment configuration
├── docs/                STLC, strategy, plan, lifecycle, architecture
├── tools/               PDF and CI summary generators
└── .github/workflows/   CI pipeline
```
