# Defect Lifecycle

The lifecycle is enforced as a state machine in `testpilot/defects.py`,
not as a free-text status field. Every transition is validated and
appended to `defect_events`, which gives a complete audit trail of who
moved what, when, and why.

---

## 1. The states

```
                 ┌──────────┐
                 │   NEW    │  filed from a recorded failure
                 └────┬─────┘
        ┌─────────────┼─────────────┐
        v             v             v
  ┌──────────┐  ┌──────────┐  ┌──────────┐
  │ TRIAGED  │  │ REJECTED │  │ DEFERRED │
  └────┬─────┘  └────┬─────┘  └────┬─────┘
       v             │             │
 ┌─────────────┐     │             │
 │ IN_PROGRESS │<────┼─────────────┘
 └──────┬──────┘     │
        v            │
   ┌─────────┐       │
   │  FIXED  │       │
   └────┬────┘       │
        v            │
  ┌──────────┐       │
  │ VERIFIED │       │   requires a note recording HOW it was verified
  └────┬─────┘       │
       v             │
  ┌──────────┐       │
  │  CLOSED  │       │
  └────┬─────┘       │
       v             v
  ┌──────────────────────┐
  │      REOPENED        │──> IN_PROGRESS
  └──────────────────────┘
```

| State | Meaning |
| --- | --- |
| `NEW` | Filed from a recorded failing execution. Not yet looked at. |
| `TRIAGED` | A human has reproduced it and accepted it as a real product defect. |
| `IN_PROGRESS` | Assigned; a fix is being written. |
| `FIXED` | The developer believes it is fixed. **Not** the same as verified. |
| `VERIFIED` | QA re-ran the case against the fix and it passed. |
| `CLOSED` | Shipped and confirmed in the target environment. |
| `REJECTED` | Not a defect — working as specified, a test defect, or environmental. |
| `DEFERRED` | Real, accepted, but not being fixed in this release. |
| `REOPENED` | It came back, or the fix was incomplete. |

## 2. Legal transitions

| From | May move to |
| --- | --- |
| `NEW` | `TRIAGED`, `REJECTED`, `DEFERRED` |
| `TRIAGED` | `IN_PROGRESS`, `REJECTED`, `DEFERRED` |
| `IN_PROGRESS` | `FIXED`, `DEFERRED` |
| `FIXED` | `VERIFIED`, `REOPENED` |
| `VERIFIED` | `CLOSED`, `REOPENED` |
| `CLOSED` | `REOPENED` |
| `REJECTED` | `REOPENED` |
| `DEFERRED` | `TRIAGED`, `REJECTED` |
| `REOPENED` | `IN_PROGRESS`, `REJECTED` |

Anything else is refused with a message naming what *is* allowed:

```
$ tp defect move DEF-481FD331 CLOSED
DEF-481FD331 cannot move from FIXED to CLOSED.
Allowed from FIXED: REOPENED, VERIFIED.
```

**Why `FIXED` cannot jump straight to `CLOSED`.** That single missing
edge is the most important rule in the diagram. It makes it structurally
impossible to close a defect that nobody re-tested — the most common way
a "fixed" bug reaches production still broken.

**Why `VERIFIED` requires a note.** Verification without a record of how
it was verified is a claim, not evidence:

```
$ tp defect move DEF-481FD331 VERIFIED
Verifying a fix requires a note recording how it was verified.

$ tp defect move DEF-481FD331 VERIFIED --note "Re-ran TC-CART-041 on build 1.4.1; passes."
DEF-481FD331: FIXED -> VERIFIED
```

---

## 3. Severity and priority

They are different questions and are tracked separately. Severity is
*how bad is the damage*; priority is *how soon do we act*. A cosmetic
typo on the checkout button is S4 but may well be P1.

| Severity | Meaning |
| --- | --- |
| **S1** | Critical — data loss, money incorrect, or a core journey completely blocked. |
| **S2** | Major — a core journey broken with a workaround, or a security control failing. |
| **S3** | Minor — a non-core function misbehaves. |
| **S4** | Trivial — cosmetic or wording. |

| Priority | Meaning |
| --- | --- |
| **P1** | Fix now; blocks the release. |
| **P2** | Fix in this release. |
| **P3** | Fix when convenient. |
| **P4** | Backlog. |

TestPilot's automatic severity assignment is deliberately conservative
and explainable: a reproduced failure in a module that touches money or
authentication is S1/P1; a first occurrence in those modules is S2/P1;
a browser-layer failure defaults to S3. A human can and should override
it — the value is a defensible starting point, not a verdict.

---

## 4. How a defect is raised

**A defect can only be filed from a recorded failing execution.** There
is no code path that creates a defect from a description. This is the
single most important property of the workflow.

```
Test executes  ──>  Result recorded  ──>  Evidence collected
                                               │
                                    ┌──────────┴──────────┐
                                    │  Gate 1: is there   │
                                    │  admissible         │
                                    │  evidence?          │
                                    └──────────┬──────────┘
                                        no ────┴──── yes
                                        │             │
                                   REFUSE with   ┌────┴─────┐
                                   reasons       │ Triage   │
                                                 └────┬─────┘
                                    ┌─────────────────┴──────────────┐
                                    │ Gate 2: does triage point at   │
                                    │ the product?                   │
                                    └─────────────────┬──────────────┘
                                        no ───────────┴─────── yes
                                        │                       │
                                REFUSE, suggest a         Draft the report,
                                human override            file it as NEW
```

**Gate 1 — admissible evidence.** All four must hold:

1. A stored `test_results` row exists.
2. Its outcome is `failed` or `error` — never `passed`, `skipped` or
   `xfailed`.
3. A failure message or traceback was captured.
4. The run is attributable to a suite, environment and timestamp.

**Gate 2 — triage.** The failure must be classified `product_defect`. A
`ConnectionError`, a missing browser binary, a missing fixture or a
stale seed row is not a product defect and will not be filed against the
product. A human may override with `--force`, and the override is
recorded on the defect.

Demonstration of the gate refusing:

```
$ tp defect file 197
Not filed. Refusing to assert a defect. Test outcome was 'passed', not a
failure. A defect cannot be claimed from a non-failing execution.
```

---

## 5. What a filed defect contains

Every defect carries the evidence that justifies it:

- the automated test node id and the manual case it traces to,
- the environment, branch and commit,
- the exact assertion, with expected and actual values quoted from the
  captured output — or an explicit statement that they could not be
  determined, which is preferred over guessing,
- the failure screenshot and Playwright trace where the failure was in a
  browser,
- the HTTP conversation where the failure was in the API,
- how many of the recorded executions of that test have failed,
- the triage category and the signals behind it,
- **open questions for the reviewer**, because a machine-drafted report
  should say what it does not know.

The title is prefixed `[DRAFT]` and the body opens with a banner stating
that it awaits human verification. TestPilot never claims a defect is
real; it presents evidence and a draft.

---

## 6. Worked example

A real defect caught by the suite against the fault-injected build:

```
$ tp run regression                    # against the faulty environment
regression on faulty: 164 passed, 5 failed - 97.0% pass rate

$ tp analyse run_20260904_010352_bfb2e8
tests/api/test_cart.py::test_a_coupon_discounts_a_multi_line_cart_only_once
  Expected : 1199
  Actual   : 2396
  Category : product_defect (medium confidence)
  Fileable : yes -> tp defect file 262

$ tp defect file 262
Filed DEF-481FD331: [DRAFT] test_a_coupon_discounts_a_multi_line_cart_only_once
failed with AssertionError in cart and pricing
Severity S2 / P1, classified product_defect.

$ tp defect move DEF-481FD331 TRIAGED     --note "Reproduced by hand."
$ tp defect move DEF-481FD331 IN_PROGRESS --note "Assigned to pricing."
$ tp defect move DEF-481FD331 FIXED       --note "Discount applied to subtotal once."
$ tp defect move DEF-481FD331 VERIFIED    --note "Re-ran TC-CART-041; passes."
$ tp defect move DEF-481FD331 CLOSED      --note "Shipped in 1.4.1"
```

The defect: a 10% coupon on a subtotal of 11 996 cents discounted 2 396
cents instead of 1 199 — the percentage was being applied per cart line
and then summed. A customer with a two-line cart was silently given
double the advertised discount. It is exactly the class of defect that
never produces an error message and never gets noticed until the revenue
report does not reconcile.

---

## 7. Metrics

`tp defect list` reports:

- open defects by status and by severity,
- the components carrying the most defects,
- **rejection rate** — the share of filed defects later marked
  `REJECTED`. This is the check on QA itself: a climbing rejection rate
  means we are filing noise, and it is the reason the evidence gate
  exists.
