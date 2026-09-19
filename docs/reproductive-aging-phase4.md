# MenoMate Reproductive-Aging — Phase 4 Backend Record (IMPLEMENTED)

> Current-state note (2026-09-19, production `main` `0baa5e7`): Phase 4 is
> **merged to `main` and manually deployed** — not worktree state, not pending
> review. The verification paragraph (§7) below is the historical 2026-09-18
> record (its "nothing committed", "3 pre-existing failures" lines are stale;
> current suite is 373 collected / 373 passed). Body below preserved as written.
> Status: **Phase 4 implementation record. Backend only.**
> Implements the minimal reproductive-aging/perimenopause context foundation
> defined by the Phase 1 design contract (`docs/reproductive-backend-contract.md`
> §4.3, §5.8, §11). No Flutter, no diagnosis, no detection, no predictor change.
> Protected systems (`app/services/cycle_calculator.py`, prediction ledger,
> backtest harness, timezone service, Health Context, pregnancy mode) were not
> modified — verified by `git status` showing no changes to those files and by
> the regression tests listed below.

Implementation date (UTC): 2026-09-18.
Inspection method before building: direct read of backend code, SQL, schemas,
and tests in this repository (contract, Phase 2 fertility implementation,
Phase 3 pregnancy implementation, profile/cycles/logs/summary/health-context
models and routes, timezone service, auth, migrations, existing tests).
Repository code was treated as authoritative throughout.

---

## 1. What was built

A single user-owned free-text singleton — the smallest coherent architecture
the contract supports:

| Piece | Location |
|---|---|
| Table `reproductive_aging_contexts` | `supabase_initial_schema.sql` (Phase 4 section), `migrations/0007_reproductive_aging_context_v1.sql` |
| ORM model | `app/models/reproductive_aging.py` (registered in `app/models/__init__.py`; cascade relationship on `Profile`) |
| Schemas | `app/schemas/reproductive_aging.py` (`AgingContextPut`, `AgingContextResponse`) |
| Service | `app/services/reproductive_aging.py` (`get_aging_row`, `apply_aging_put`) |
| Routes | `GET` + `PUT /api/v1/reproductive/aging-context` in `app/api/v1/reproductive.py` (existing reproductive router) |
| Tests | `tests/test_reproductive_aging_phase4.py` (24 tests) |

Table shape: `user_id UUID PK → profiles.user_id ON DELETE CASCADE`,
`notes TEXT NULL` (verbatim, ≤2000 enforced at the API layer, mirroring
`health_notes`), `created_at/updated_at TIMESTAMPTZ`. Default-deny RLS
(enabled, no policies) in the creating migration, matching the existing
posture. No other columns exist.

---

## 2. State vocabulary decision (no enum invented)

The contract defines **no state vocabulary** for reproductive aging — §4.3 and
§11 explicitly forbid `perimenopause_stage`, `menopause_status`, and any
diagnosis/staging column, and §5.8 fixes the shape at `{ notes? ≤2000 }`.
Per the Phase 4 STOP rule ("do not introduce enums merely because they sound
reasonable"), **no lifecycle enum was implemented**. The response carries
`has_context` (notes present or not) plus the verbatim notes — a presence
indicator over user input, not a lifecycle stage. Terms such as reproductive
aging, perimenopause/menopausal transition, menopause, and postmenopause are
not represented as values anywhere in this implementation.

## 3. Provenance semantics

The only possible source of the row is the owning user's explicit input
(mirroring the health-notes "user-provided context" pattern), so provenance
is a **fixed response label**, not a stored enum: `provenance =
"user_declared"` on every response, including the unset default.
`CLINICALLY_CONFIRMED` (and any clinician/derived/system vocabulary) is never
emitted by this surface — there is no input path that could produce it, and a
test asserts its absence.

## 4. API behavior

- `GET /api/v1/reproductive/aging-context` → 200. Unset default
  (`has_context: false`, nulls) when never recorded or cleared; read-only,
  creates no profile/row (mirrors the pregnancy GET pattern). 401 when
  unauthenticated.
- `PUT /api/v1/reproductive/aging-context` → 200. Full-replacement upsert:
  `notes` set verbatim; omitted/null clears the recorded context (the
  deactivation path). Creates profile + row on first sync. Over-long notes
  (>2000) → 422. Extra `user_id` keys ignored (JWT `sub` is the sole
  ownership source). Cross-user access is impossible by construction
  (singleton keyed on JWT `sub`; no id-addressed routes).
- No PATCH/DELETE surface exists (the contract requires GET + PUT only);
  tests assert both return 404/405 and change nothing.
- All responses carry the fixed safety disclaimer (context is user input, not
  a diagnosis/staging/fertility statement).

## 5. Interaction guarantees (all tested)

- **Pregnancy mode (Phase 3):** fully independent singletons. Recording,
  changing, or clearing aging context never activates, deactivates, or edits
  pregnancy mode, and vice versa. All four active/inactive combinations
  verified; Phase 3 SUPPRESSED behavior applies exactly as before when
  pregnancy mode is active alongside aging context; erasing pregnancy mode
  restores prior estimate behavior. Legacy `health_contexts.pregnancy_context`
  untouched in both directions.
- **Fertility (Phase 2):** byte-identical estimate responses before/after
  setting aging context (AVAILABLE and INSUFFICIENT_DATA both verified).
  Perimenopause is never equated with infertility; no suppression, warning,
  or confidence change was added — see NEEDS-REVIEW item 2.
- **Period predictor:** `summary/current` and `cycles/current` snapshots are
  identical before/after extensive aging-context writes
  (`test_aging_context_does_not_alter_period_predictions`, extending the
  health-context pattern). `cycle_calculator.py`, `robust_wma_v1`, the
  prediction ledger, and the backtest harness are untouched.
- **Health Context:** values byte-identical across aging writes/clears; no
  field reinterpreted, no duplication.
- **Data retention:** cycles, observations, logs, pregnancy state verified
  identical across record/revise/clear cycles. Profile DELETE cascades the
  singleton (GDPR erasure via the existing path).
- **Dates/timezone:** the table has no DATE columns by design (no context
  start date, LMP/FMP date, or clinician date is defined by the contract), so
  no timezone logic was needed and `app/services/timezone.py` is untouched.
  `created_at/updated_at` are UTC instants.

## 6. Deferred clinical / product decisions (NEEDS-REVIEW)

1. **Structured lifecycle vocabulary (STATES).** No enum for reproductive
   aging / menopausal transition / menopause / postmenopause exists. Adding
   one requires product + clinical sign-off on exact terms and meanings.
2. **Fertility-estimate effect.** The contract specifies no contextual
   warning or reduced-confidence behavior for this phase, so Phase 2 behavior
   is preserved exactly. Any future warning needs clinical wording review
   (must never imply infertility or zero pregnancy possibility).
3. **Menopause 12-month derivation.** The conventional retrospective
   12-month criterion is NOT implemented (no derived state, no diagnosis).
   Requires: contract definition of a menstrual period for gap counting,
   handling of missing history, and an explicit product decision that only an
   informational "meets recorded-data criterion" state — never a diagnosis —
   may be derived.
4. **User-provided dates.** No context start / LMP / FMP / clinician-confirmed
   date fields exist. Each needs a contract decision before being added
   (all would be DATE-only via the canonical timezone rule).
5. **Automatic detection.** No perimenopause/menopause/postmenopause detection
   from age, variability, gaps, symptoms, or prediction behavior exists and
   none is planned without a clinically specified algorithm.
6. **PATCH/DELETE surface.** Only GET + PUT ship per the contract. A partial-
   update or hard-erase endpoint needs a contract decision (clearing via PUT
   covers deactivation today).
7. **Provenance extension.** If a clinician-confirmed aging fact is ever
   needed, it requires a verified-clinician write path first (same rationale
   as the deferred fertility confirm endpoint) — never inferred.

## 7. Verification

- Focused: `tests/test_reproductive_aging_phase4.py` — 24 passed.
- Regressions: Phase 2 (`test_fertility_phase2.py`), Phase 3
  (`test_pregnancy_phase3.py`), and the full suite run; only the 3 known
  pre-existing duplicate-start failures remain (unchanged, unrelated).
- Medical-safety tests assert no response claims menopause/perimenopause
  status, infertility, zero pregnancy possibility, or clinical confirmation.
- Production safety: no deploy, no Render change, no production DB/migration
  activity, no env change; nothing committed or pushed.

## 8. Current-state addendum (2026-09-19, historical record above preserved)

- The implementation above was merged to `main` via `0baa5e7` and manually
  deployed to the Render production service — it is not worktree state and not
  awaiting review.
- The "3 pre-existing duplicate-start failures" line above is historical: those
  stale expectations were corrected without changing the implementation, and the
  current suite is 373 collected / 373 passed, 0 failed.
- "Nothing committed or pushed" above describes the 2026-09-18 worktree moment
  only; the code, migrations (`0007_reproductive_aging_context_v1.sql`), schema,
  and `tests/test_reproductive_aging_phase4.py` (24 tests) are committed on `main`.
