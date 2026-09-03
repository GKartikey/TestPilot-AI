# TestPilot AI

A QA automation platform, and a sample ecommerce application for it to
test.

Two separate systems live in this repository:

- **ShopNest** — the *system under test*. A FastAPI storefront with
  accounts, catalogue, cart, coupons, checkout, a SQLite database and a
  browser UI.
- **TestPilot** — the QA platform. Test case management, suite
  execution, result storage, analytics, defect tracking, exportable
  reports, and AI assistance that is **not permitted to claim a bug
  exists without execution evidence**.

They share no code. TestPilot reaches ShopNest only over HTTP and SQL,
exactly as it would a third-party service.

```
220 automated tests   125 documented test cases   95.2% automated
 54 platform unit  ·  82 API  ·  25 SQL  ·  18 browser (Playwright)
```

---

## Quick start

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows;  source .venv/bin/activate on Unix
pip install -r requirements.txt
playwright install chromium

python -m testpilot.cli doctor  # check the machine is ready
python -m testpilot.cli run smoke
```

`tp doctor` validates the case library, the suite definitions, the
environment configuration, the results database, and that Chromium
actually launches.

The suite starts and stops ShopNest itself — there is no "start the app
first" step to forget.

---

## Common commands

```bash
tp suites                        # what suites exist and what they select
tp cases --layer api --detail 3  # browse the documented test cases
tp coverage                      # automation coverage of the design

tp run smoke                     # fast build acceptance (~14s)
tp run regression                # everything (~2 min)
tp run ui --trace on             # browser suite, always keep traces

tp show                          # the latest run in detail
tp history --suite regression    # pass rate over time, flaky tests
tp compare <baseline> <candidate>  # what broke since main

tp report <run> --format html    # export html/json/junit/csv/markdown
tp analyse <run>                 # AI triage of the failures

tp defect file <result-id>       # draft and file, evidence permitting
tp defect move <id> TRIAGED --note "..."
tp defect list

tp generate --spec http://127.0.0.1:8077/openapi.json --write
tp edges "cart quantity" --type integer
```

`tp` is `python -m testpilot.cli`.

---

## Running ShopNest on its own

```bash
python -m uvicorn shopnest.main:app --port 8077
```

- Storefront: <http://127.0.0.1:8077/>
- API docs: <http://127.0.0.1:8077/docs>
- Seeded accounts: `casey@example.com` / `Custom3rPass`,
  `admin@shopnest.io` / `AdminPass123`

### The fault-injected build

A suite that has only ever been seen green is unproven. Set
`SHOPNEST_FAULT_PROFILE` to launch a deliberately broken build:

| Profile | Injected defect |
| --- | --- |
| `coupon_stacking` | Discount applied per cart line instead of per cart |
| `stock_oversell` | Off-by-one lets a customer buy one unit more than exists |
| `weak_auth` | Expired tokens accepted; order history leaks other customers |
| `all` | All of the above |

```bash
TESTPILOT_ENV=faulty tp run regression
# regression on faulty: 164 passed, 5 failed - 97.0% pass rate
```

The suite catches all three defect classes. That is the evidence that it
works.

---

## The evidence gate

The central rule of the AI layer:

> **AI may describe evidence. It may never assert that a defect exists.**

This is enforced in code (`testpilot/ai/evidence.py`), not by prompt
wording. A defect claim is admissible only when:

1. a stored test result exists,
2. its outcome is `failed` or `error` — never `passed` or `skipped`,
3. a failure message or traceback was captured, and
4. the run is attributable to a suite, environment and timestamp.

A bug report additionally requires triage to have pointed at the product
rather than at the environment, the test, or the test data.

```bash
$ tp defect file 197
Not filed. Refusing to assert a defect. Test outcome was 'passed', not a
failure. A defect cannot be claimed from a non-failing execution.
```

Both gates have their own tests in
`tests/framework/test_evidence_gate.py`. If those go red, the AI layer is
unsafe to use until fixed.

**AI features:** generate test cases from an OpenAPI spec, suggest edge
cases, summarise a failure, classify a failure, draft a bug report.

**Providers:** the Claude API when `ANTHROPIC_API_KEY` is set, otherwise
a deterministic rule-based provider. The fallback is not a stub — it is
what CI uses, so no build ever depends on a model being reachable. Set
`TESTPILOT_AI=off` to force it.

---

## Documentation

| Document | Contents |
| --- | --- |
| [STLC](docs/stlc.md) | The six phases, and the artefact that evidences each |
| [Test strategy](docs/test-strategy.md) | The pyramid, risk model, automation principles |
| [Test plan](docs/test-plan.md) | Scope, entry/exit criteria, risks, schedule |
| [Test cases](docs/test-cases.md) | All 125 cases, generated from the registry |
| [Defect lifecycle](docs/defect-lifecycle.md) | The state machine and the evidence gate |
| [Automation architecture](docs/automation-architecture.md) | Layers, POM, fixtures, data flow |
| **TestPilot_Project_Guide.pdf** | Full guide, including 40+ QA/SDET interview questions |

---

## CI

`.github/workflows/tests.yml` runs on every pull request as a staircase:
platform unit tests gate the smoke suite, which gates the API, SQL and
browser suites running in parallel. Failure screenshots and Playwright
traces are uploaded as artifacts, and a summary is posted as a pull
request comment.

CI runs with `TESTPILOT_AI=off` so that a missing model key can never
turn a build red.

---

## Configuration

| Variable | Purpose |
| --- | --- |
| `TESTPILOT_ENV` | Environment name: `local`, `headed`, `ci`, `faulty` |
| `TESTPILOT_BASE_URL` | Override the system under test's URL |
| `TESTPILOT_BROWSER` | `chromium`, `firefox` or `webkit` |
| `TESTPILOT_AI` | `off` forces the rule-based provider |
| `TESTPILOT_TRACE` | `off`, `on`, `retain-on-failure` |
| `ANTHROPIC_API_KEY` | Enables live model analysis |
| `SHOPNEST_FAULT_PROFILE` | Inject defects into the system under test |

Environments are declared in `config/environments.yaml`; any single value
can be overridden with `TESTPILOT_<KEY>`.

---

## Layout

```
shopnest/     the system under test        testpilot/    the QA platform
framework/    page objects, clients, data  tests/        the tests
testcases/    125 documented cases         docs/         STLC, strategy, plan
config/       environments                 tools/        PDF and CI generators
```
