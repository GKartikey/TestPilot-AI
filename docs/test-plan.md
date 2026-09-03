# Test Plan — ShopNest 1.4.x

Written to the shape of IEEE 829, kept to what is actually useful.

| | |
| --- | --- |
| **Plan ID** | TP-PLAN-SHOPNEST-1.4 |
| **System under test** | ShopNest 1.4.0 |
| **Test platform** | TestPilot 1.0.0 |
| **Prepared by** | QA |
| **Status** | Active |

---

## 1. Introduction

ShopNest is a storefront service: accounts, catalogue, cart, coupons and
checkout, over a REST API with a browser front end and a SQLite database.
This plan covers verification of release 1.4.x.

The commercial risk concentrates in three places, and the plan is
weighted accordingly:

1. **Money** — pricing, discounts, shipping thresholds, tax, order totals.
2. **Inventory** — stock must never oversell, and must move exactly once.
3. **Identity** — authentication, authorisation, and tenancy isolation.

---

## 2. Test items

| Item | Version | In scope |
| --- | --- | --- |
| Authentication API | 1.4.0 | Yes |
| Catalogue API | 1.4.0 | Yes |
| Cart and coupon API | 1.4.0 | Yes |
| Orders and checkout API | 1.4.0 | Yes |
| Storefront web UI | 1.4.0 | Yes |
| Database schema | 1.4.0 | Yes |
| Payment gateway integration | — | **No** — not implemented in 1.4.x |
| Email delivery | — | **No** — not implemented in 1.4.x |

---

## 3. Features to be tested

| Feature | Requirements | Cases | Priority |
| --- | --- | --- | --- |
| Registration and login | REQ-AUTH-01..08 | TC-AUTH-001..015 | P1 |
| Token handling | REQ-SEC-03..07 | TC-AUTH-020..024 | P1 |
| Role and object authorisation | REQ-SEC-08..09 | TC-AUTH-030..033 | P1 |
| Catalogue browse, search, filter, sort | REQ-CAT-01..09 | TC-PROD-001..036 | P2 |
| Pagination | REQ-CAT-08 | TC-PROD-030..033 | P2 |
| Cart management | REQ-CART-01..07 | TC-CART-001..024 | P1 |
| Pricing and coupons | REQ-PRICE-01..07 | TC-CART-030..046 | P1 |
| Checkout and stock movement | REQ-ORD-01..12 | TC-ORD-001..034 | P1 |
| Order history and cancellation | REQ-ORD-10..11 | TC-ORD-030..034 | P2 |
| Schema and data integrity | REQ-DATA-01..09 | TC-SQL-001..036 | P1 |
| Credential storage | REQ-SEC-11 | TC-SQL-024..025 | P1 |
| Browser journeys | REQ-UI-01..11 | TC-UI-001..030 | P1 |

## 4. Features not to be tested

| Not tested | Reason |
| --- | --- |
| Performance and load | No non-functional requirement stated for 1.4.x; requires a separate harness and environment. |
| Penetration testing | Handled by an external security review. The suite covers the authentication and authorisation *logic* only. |
| Cross-browser matrix | Chromium only for 1.4.x. Firefox and WebKit are a backlog item; the framework already supports them via `TESTPILOT_BROWSER`. |
| Accessibility audit | TC-UI-030 documents the keyboard journey but remains manual until axe-core is integrated. |
| Password reset | TC-AUTH-040 is written and held as manual; the feature does not exist in 1.4.0. |
| Multi-coupon stacking | TC-CART-050 raised; the requirement is unresolved with product and will not be guessed at. |

---

## 5. Approach

Summarised here; the reasoning is in `docs/test-strategy.md`.

- Test at the lowest layer that can prove the behaviour.
- Every documented boundary is tested at the bound and one step either
  side.
- Every negative test asserts both the rejection and the absence of side
  effects.
- Money is verified three ways: in the API response, against an
  independent pricing oracle, and by reconciling the stored rows in SQL.
- The suite owns its environment; `pytest` is a single entry point.

**Test design techniques:** equivalence partitioning, boundary value
analysis, decision tables, state transition testing, and error guessing.

---

## 6. Item pass/fail criteria

A test item passes when every P1 and P2 case for it has been executed and
passed, and any P3/P4 failure has a raised defect with an accepted
severity.

---

## 7. Entry and exit criteria

**Entry:**
1. The build deploys and `/health` identifies the expected service.
2. `tp doctor` passes on the execution machine.
3. The smoke suite is green.

**Exit:**
1. 100% of P1 cases executed.
2. Zero open S1 or S2 defects.
3. Regression pass rate ≥ 98%, every failure triaged to an owner.
4. No defect in `CLOSED` without a `VERIFIED` transition carrying a note
   on how the fix was verified.
5. Reports exported and attached to the release record.

**Suspension criteria.** Testing stops and the build is returned if the
smoke suite fails, if the environment cannot be stood up, or if more than
25% of the regression suite fails — at that point the build is not ready
and continuing to run tests only produces noise.

---

## 8. Test deliverables

| Deliverable | Location |
| --- | --- |
| Test plan, strategy, STLC | `docs/` |
| Test cases (125) | `testcases/*.yaml` |
| Automation (220 tests) | `tests/`, `framework/` |
| Execution records | `artifacts/testpilot.db` |
| Reports (HTML/JSON/JUnit/CSV/MD) | `artifacts/reports/` |
| Failure screenshots and traces | `artifacts/screenshots/`, `artifacts/traces/` |
| Defect records | `tp defect list`, exported markdown |

---

## 9. Environment needs

| Need | Detail |
| --- | --- |
| Runtime | Python 3.12+ |
| Browser | Chromium via `playwright install chromium` |
| Database | SQLite, created and seeded by the suite |
| Network | Loopback only; no external service is required |
| CI | GitHub Actions, `ubuntu-latest` |

Environments are declared in `config/environments.yaml`. No credential
for a real environment is ever committed; those come from the process
environment.

---

## 10. Schedule and estimate

| Activity | Effort |
| --- | --- |
| Requirement analysis and planning | 1 day |
| Test case design (125 cases) | 3 days |
| Framework build (POM, clients, fixtures) | 3 days |
| Automation of 119 cases | 5 days |
| CI integration | 1 day |
| Execution, triage and reporting per cycle | 0.5 day |

**Execution time per cycle:** smoke ~14s wall clock; full regression
~2 minutes locally; the CI pipeline runs the layers as parallel jobs.

---

## 11. Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
| --- | --- | --- | --- |
| Flaky UI tests erode trust in the suite | Medium | High | No sleeps; wait on the app's own `data-ready` flag; flake rate tracked per test and treated as a defect in the suite |
| The suite passes but does not actually detect regressions | Low | Critical | The `faulty` environment injects real defects and is used to prove detection |
| Test data collisions between tests | Medium | Medium | Unique generated data; fixtures clear the cart on entry and exit |
| An AI feature reports a bug that does not exist | Medium | High | The evidence gate refuses any claim without a recorded failing execution; covered by its own tests |
| A model or API key is unavailable in CI | High | Low | The rule-based provider is the CI default; no build depends on a model |
| Environment drift between local and CI | Medium | Medium | One environment file, environment-variable overrides, `tp doctor` |
| Slow suites discourage running them | Medium | Medium | Each suite has a declared time budget, checked after every run |

---

## 12. Responsibilities

| Role | Responsibility |
| --- | --- |
| QA engineer | Case design, automation, triage, defect reporting |
| Developer | Fixing product defects; keeping `data-testid` attributes stable |
| Build engineer | CI runners, browser provisioning |
| QA lead | Priorities, exit criteria sign-off, defect verification |

---

## 13. Approvals

| Role | Name | Date |
| --- | --- | --- |
| QA Lead | | |
| Engineering Lead | | |
| Product | | |
