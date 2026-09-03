# Test Strategy

**Scope:** ShopNest (the system under test) and TestPilot (the QA
platform that exercises it).
**Status:** in force for release 1.4.x.

A test plan says what we will do on this release. A strategy says what we
believe about testing and why, and it should change rarely.

---

## 1. What we are optimising for

Not "how many tests". The three things that actually matter:

1. **Time to a trustworthy signal.** A developer should know within a
   minute whether their change broke anything important.
2. **Diagnosability.** When a test fails, the report should tell you what
   broke without you re-running anything. That is why failures carry
   screenshots, traces, and the HTTP conversation.
3. **Honesty.** A green suite must mean something. A red one must be
   worth investigating. Both are undermined by flaky tests, so we treat
   flakiness as a defect in the suite, not a fact of life.

---

## 2. The test pyramid, as applied here

```
                 ┌───────────────┐
                 │   UI  (18)    │   Playwright. Journeys only a
                 │   ~30s        │   browser can prove.
              ┌──┴───────────────┴──┐
              │   SQL / data (25)   │  What was actually stored.
              │   ~10s              │
         ┌────┴─────────────────────┴────┐
         │       API  (82)               │  Every permutation:
         │       ~50s                    │  negative, boundary, auth.
    ┌────┴───────────────────────────────┴────┐
    │   Platform unit (54)                    │  The framework itself,
    │   ~5s                                   │  including the AI gate.
    └─────────────────────────────────────────┘
```

**The governing rule: push every test to the lowest layer that can prove
the thing.**

A concrete application of that rule on this project. "A coupon must
discount the cart once" could be tested through the browser. It is not.
It is tested at the API layer (TC-CART-040/041) where it runs in
milliseconds and cannot be defeated by a rendering change, and separately
in SQL (TC-SQL-032) where the stored total is reconciled. The browser
tests one instance of it (TC-UI-026) purely to prove the number reaches
the screen.

**Why the pyramid is shaped, not just described.** Each layer answers a
different question, and the questions do not substitute for one another:

| Layer | The question it answers |
| --- | --- |
| Platform unit | Is the measuring instrument itself correct? |
| API | Does the service honour its contract, including at the edges? |
| SQL | Did it actually *store* what it said it did? |
| UI | Can a human complete the journey in a real browser? |

An endpoint can return `201 Created` and write the wrong row. Only the
SQL layer catches that. This is why the data layer is not folded into the
API layer.

---

## 3. Test levels and types

**Levels:** component (platform unit), integration (API against a real
database), system (browser journeys end to end), and acceptance (the
smoke suite is the build-acceptance gate).

**Types deliberately covered:**

- **Functional** — the documented behaviour works. 33 cases.
- **Negative** — invalid, malformed and hostile input is refused
  *without side effects*. 28 cases. Every negative test asserts both the
  rejection **and** that nothing changed.
- **Boundary** — 22 cases. Every documented limit is tested at the bound
  and one step either side. This is the highest-yield category in the
  suite and is treated as mandatory, not optional.
- **Security** — 17 cases: authentication, authorisation, tenancy
  isolation, injection, and credential storage.
- **Data integrity** — 18 cases reconciling money and stock in SQL.
- **Smoke** — 6 cases, the release gate.
- **Regression** — everything above, run on every pull request.

**Explicitly out of scope for automation** and handled by other means:
performance and load testing, penetration testing, accessibility audit
(the keyboard journey is documented as TC-UI-030 but left manual until an
axe-core audit is integrated), and cross-browser matrix testing beyond
Chromium.

---

## 4. Risk-based prioritisation

Priority is assigned from *business impact if it breaks*, not from how
hard the test was to write.

| Priority | Meaning | Examples |
| --- | --- | --- |
| **P1** | Money, security, or a blocked core journey | checkout, pricing, auth, tenancy isolation |
| **P2** | Important but recoverable, or has a workaround | cart editing, catalogue filtering |
| **P3** | Minor functional detail | sort order, empty states |
| **P4** | Cosmetic | layout at breakpoints |

60 of 125 cases are P1. That ratio is intentional for an ecommerce
system: most of what this application does either takes money or guards
someone's data.

---

## 5. Automation approach

**What we automate:** anything run more than twice, anything guarding
money or security, and anything a human would perform inconsistently.

**What we do not automate:** exploratory testing, usability judgement,
and one-off investigations. Automation is regression protection; it does
not find new classes of problem on its own.

**Framework principles**, each with a concrete consequence in this
repository:

1. **Page objects expose state; tests make assertions.** No page object
   contains an `assert`. That is what lets one page object serve a
   positive test, a negative test and a boundary test.
2. **Locators are `data-testid`.** CSS classes and visible text change
   with copy edits; test ids are a contract with the application, and
   changing one is a breaking change.
3. **No sleeps.** Waiting is expressed as waiting for a *condition* —
   Playwright's auto-waiting plus the application's own `data-ready`
   flag. `time.sleep` in a UI test is a review rejection.
4. **Independent oracles.** Tests must not import the application's own
   `compute_totals` to check its arithmetic; an oracle that shares code
   with the thing it checks proves nothing. `framework/utils/helpers.py`
   reimplements the pricing rules from the specification.
5. **Tests are order-independent.** Each test cleans up after itself and
   gets a fresh browser context. Any test that requires a predecessor is
   a defect in the suite.
6. **Failures must be self-explanatory.** `assert_status` includes the
   response body, because `assert response.status == 200` produces a
   report nobody can act on.

---

## 6. Test data strategy

- **Deterministic seed data** for anything a test asserts on — known
  SKUs, known prices, known accounts, exported as constants from
  `framework/data/builders.py` so a seed change breaks in one place.
- **Generated unique data** for anything that must not collide, via
  `unique_email()` and `unique_sku()`. Registration tests never fight
  each other.
- **Builders over literal dicts**, so a test states only the field it
  cares about and stays valid in every other respect — which means it
  fails for the reason it claims to be about.
- **Restore what you change.** Tests that manipulate stock use the
  `temporarily_set_stock` context manager, which puts it back.

---

## 7. Environment strategy

| Environment | Purpose |
| --- | --- |
| `local` | Developer machine. Headless, fast. |
| `headed` | Debugging, with `slow_mo` so you can watch. |
| `ci` | GitHub Actions. Longer timeouts for a slower runner. |
| `faulty` | A deliberately broken build, used to prove the suite detects regressions rather than merely passing. |

The `faulty` environment deserves comment. A test suite that has only
ever been seen green is an unproven suite: you do not know whether it
would catch anything. `SHOPNEST_FAULT_PROFILE` injects three real defect
classes — a coupon applied per line instead of per cart, an off-by-one
that allows overselling, and an authentication build that skips expiry
checks and leaks other customers' orders. The regression suite catches
all of them. That is the evidence that the suite works.

---

## 8. AI strategy, and its hard limit

AI is used for four things, all of them *before* or *after* execution,
never as a substitute for it:

- drafting test cases from an API specification,
- suggesting edge cases a designer may not have considered,
- summarising a failure,
- classifying a failure so it reaches the right owner.

**The rule that governs all of it: AI may describe evidence; it may never
assert a defect.**

This is enforced in code, not by prompt wording. `testpilot/ai/evidence.py`
admits a claim only when a stored result exists, its outcome is `failed`
or `error`, a failure message or traceback was captured, and the run is
attributable to a suite and environment. A bug report additionally
requires triage to have pointed at the product. Both gates are covered by
tests in `tests/framework/test_evidence_gate.py`; if any of them go red,
the AI layer is treated as unsafe to use until fixed.

Two supporting decisions:

- **The offline provider is not a stub.** The rule-based analysis is real
  logic that CI runs by default, so no build ever depends on a model
  being reachable or a key being present.
- **Every AI output is labelled.** Generated cases are `status: draft`.
  Bug reports are titled `[DRAFT]` and carry an "open questions for the
  reviewer" section. Nothing produced by a model enters the suite or the
  defect tracker as fact.

---

## 9. Entry and exit criteria

**Entry to test execution:** the build deploys, `/health` reports the
expected service, `tp doctor` passes, and the smoke suite is green.

**Exit from a release cycle:** every P1 case executed; zero open S1/S2
defects; regression pass rate ≥ 98% with every failure triaged; no defect
closed without a recorded verification note.

---

## 10. Metrics we keep, and one we deliberately do not

**Kept:** pass rate over time, flake rate, mean suite duration against
its budget, automation coverage of the documented design, defect density
by component, and defect rejection rate.

**Not kept: code coverage as a target.** Coverage is a useful diagnostic
for finding untested paths and a terrible goal. Optimising it produces
tests that execute lines without asserting anything meaningful. We
measure coverage of the *documented test design* instead — 119 of 125
cases automated, 95.2% — because that number cannot be gamed by writing
assertion-free tests.
