# Software Testing Life Cycle (STLC)

How the six STLC phases are actually carried out on this project, and
which artefact in this repository is the evidence for each one. The point
of writing it this way is that every phase has something you can open,
run, or query — not just a paragraph claiming it happened.

---

## Phase 1 — Requirement Analysis

**Purpose.** Decide what is testable, what is ambiguous, and what carries
risk, before a single test is written.

**What we do.** Read the specification of the system under test — for
ShopNest that is the OpenAPI document at `/openapi.json` plus the stated
business rules — and turn each rule into a *testable* statement with an
identifier.

The business rules that drive most of this suite:

| Requirement | Rule | Risk if wrong |
| --- | --- | --- |
| REQ-PRICE-02 | Shipping is free when the discounted subtotal is **at or above** 5000 cents | Revenue leak or angry customers, on an inclusive boundary |
| REQ-PRICE-04 | A coupon discounts the cart subtotal **exactly once** | Direct, silent revenue loss |
| REQ-CART-06 | Cart quantity per product is **1..10 inclusive** | Fulfilment and pricing errors |
| REQ-CART-07 | A customer may buy **at most** the remaining stock | Overselling, refunds, reputational damage |
| REQ-ORD-08 | Stock is revalidated **at checkout**, not only when adding | Taking money for goods that do not exist |
| REQ-SEC-09 | A customer may only ever see **their own** orders | Data breach |
| REQ-SEC-11 | Passwords are stored **only** as salted PBKDF2 hashes | Catastrophic breach |

**Questions raised in this phase** (the useful output of requirement
analysis is usually questions, not tests):

- Is the free-shipping threshold inclusive or exclusive? *Resolved:
  inclusive. This is why TC-CART-031 and TC-CART-032 both exist.*
- Does quantity `0` mean "invalid" or "remove the line"? *Resolved:
  remove. TC-CART-004 pins it.*
- May two coupons stack? *Unresolved with product. Documented as
  TC-CART-050 and left `manual` rather than guessed at.*

**Artefacts:** `docs/test-plan.md`, the `requirement:` field on every
case in `testcases/*.yaml`.

---

## Phase 2 — Test Planning

**Purpose.** Decide scope, approach, effort, environments, entry and exit
criteria, and who does what.

**What we do.** Write the test plan and the test strategy, size the
effort, and fix the risk-based priorities (P1–P4). Choose the tooling:
pytest as the runner, Playwright for the browser, direct SQL for data
validation, GitHub Actions for continuous execution.

**Key planning decision on this project:** the test pyramid is enforced
by construction. Exhaustive permutations live at the API layer because
they are fast and stable there; the browser layer covers only journeys a
browser alone can prove. That decision is *why* there are 82 API cases
and 18 UI cases rather than the reverse.

**Artefacts:** `docs/test-plan.md`, `docs/test-strategy.md`,
`testcases/suites.yaml` (each suite carries a stated time budget).

---

## Phase 3 — Test Case Development

**Purpose.** Design the cases, the data, and the automation that will
execute them.

**What we do.** Author each case as a reviewable document — objective,
preconditions, numbered steps, expected result, priority, requirement
trace — in `testcases/*.yaml`. Only then write the automation, and link
the two with the `automation:` field.

Design techniques used explicitly:

- **Equivalence partitioning** — cart quantity splits into below-range,
  in-range, above-range. TC-CART-020.
- **Boundary value analysis** — every documented limit is tested at the
  bound and one step either side. The free-shipping threshold
  (TC-CART-031/032), the minimum spend (TC-CART-044/045), page size
  (TC-PROD-030/031), stock (TC-CART-022/023).
- **Decision tables** — coupon validity × minimum spend × cart total.
- **State transition testing** — the order lifecycle
  (PLACED → CANCELLED) and the defect lifecycle itself.
- **Error guessing / negative testing** — malformed tokens, SQL
  metacharacters, markup in search terms.

**AI assistance in this phase** is real but bounded: `tp generate` drafts
cases from the OpenAPI specification and `tp edges` proposes edge cases.
Everything it produces is marked `status: draft` and is not part of any
suite until a human reviews it. The AI can suggest a case; it cannot
approve one.

**Artefacts:** `testcases/*.yaml` (125 cases), `tests/**` (the
automation), `framework/data/builders.py` (the test data).

---

## Phase 4 — Test Environment Setup

**Purpose.** Have somewhere reliable to run, and prove it is ready.

**What we do.** Environments are declared in `config/environments.yaml`
and selected with `TESTPILOT_ENV`; any single value can be overridden by
`TESTPILOT_<KEY>`. Four environments are defined: `local`, `headed` (for
debugging), `ci`, and `faulty` — a deliberately broken build used to
prove the suite actually detects regressions.

The suite owns its own environment. The `app_server` fixture starts
ShopNest, waits for it to report healthy *and confirms it is ShopNest and
not some other service holding the port*, and shuts it down afterwards.
There is no "remember to start the app first" step for anyone to forget.

`tp doctor` is the readiness check: it validates the case library, the
suite definitions, the environment configuration, the results database,
and that Playwright can actually launch a browser.

**Artefacts:** `config/environments.yaml`, `tests/conftest.py`,
`tp doctor`.

---

## Phase 5 — Test Execution

**Purpose.** Run the tests, record what happened, and report it.

**What we do.** `tp run <suite>` executes a suite and records every
result — outcome, duration, markers, traceback, screenshot, Playwright
trace, and the HTTP conversation that led to a failure — into the
results database. CI runs the same suites on every pull request.

Execution is *evidence-producing*, not just pass/fail: a failing browser
test leaves a full-page screenshot and a trace you can open with
`playwright show-trace`, and a failing API test leaves the exact request
and response that produced it.

Defects found here are raised through the defect lifecycle
(`docs/defect-lifecycle.md`), and only ever from a recorded failure.

**Artefacts:** `artifacts/testpilot.db`, `artifacts/reports/*`,
`artifacts/screenshots/*`, `artifacts/traces/*`.

---

## Phase 6 — Test Closure

**Purpose.** Decide whether the exit criteria are met, and learn
something for next time.

**What we do.** Check the exit criteria from the test plan, export the
reports, and review the metrics that only exist because results are in a
relational store:

- pass rate over time (`tp history`)
- flaky tests, defined honestly as tests that have *both* passed and
  failed — a test that always fails is broken, not flaky
- failure hotspots by module and failure type
- automation coverage of the documented design (`tp coverage`)
- defect metrics including the rejection rate, which is the check on
  whether QA is filing noise

**Exit criteria for a release** (from the test plan):

1. Every P1 case has been executed.
2. Zero open S1 or S2 defects.
3. Smoke suite green on the release candidate build.
4. Regression pass rate at or above 98%, with every failure triaged and
   either fixed or accepted with a named owner.
5. No defect closed without a `VERIFIED` transition carrying a note on
   how it was verified — the lifecycle state machine enforces this.

**Artefacts:** `tp history`, `tp coverage`, `tp defect list`, the
exported HTML/JSON/JUnit/CSV/Markdown reports.

---

## The phases as a loop

STLC is drawn as a line and lived as a loop. On this project the loop
closes in a specific, visible place: a defect that reaches `VERIFIED`
required somebody to re-run the case that found it. That re-run is a new
execution, recorded in the same store, which updates the pass rate and
the flake statistics — so closure feeds directly back into the next
cycle's planning.
