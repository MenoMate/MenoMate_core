# MenoMate Reproductive-Health — Phase 1 Backend Contract (DESIGN ONLY)

> Status: **Phase 1 design document. No implementation.**
> No fertility/ovulation algorithm, no pregnancy calculation, no perimenopause
> logic, no migration, no config/database/deployment change was made in this
> phase. The only repository change in this phase is this file.
> Protected systems (`app/services/cycle_calculator.py`, prediction ledger,
> backtest harness, timezone service, existing cycle semantics) were inspected
> read-only and are not modified by anything proposed here.

Inspection date (UTC): 2026-09-18.
Inspection method: direct read of backend code, SQL, schemas, and tests in this
repository. Backend code is treated as authoritative for existing backend
behavior.

---

## 1. Current backend architecture

### 1.1 Application structure

```text
app/main.py                 # create_app(), CORS, mounts api_v1_router, GET / and GET /health
app/api/router.py           # aggregates 10 v1 routers
app/api/v1/
  auth.py                   # GET /api/v1/auth/me
  profile.py                # GET/PATCH/DELETE /api/v1/profile
  onboarding.py             # POST /api/v1/onboarding/complete
  cycles.py                 # /api/v1/cycles*, incl. /current and /current/end
  logs.py                   # /api/v1/symptoms, /api/v1/logs*, /api/v1/logs/{id}
  summary.py                # GET /api/v1/summary/current, GET /api/v1/summary/history
  devices.py                # GET/POST/DELETE /api/v1/devices*
  therapy.py                # POST /api/v1/therapy/recommend, sessions CRUD
  care.py                   # POST /api/v1/care/interactions (+ /interact alias)
  health_context.py         # /api/v1/health-context* (singleton + conditions + medications)
app/core/config.py          # Settings: DATABASE_URL, SUPABASE_URL, JWT secret/JWKS, CORS, AUTO_CREATE_TABLES, GROQ
app/core/security.py        # get_current_user: Supabase JWT verification -> UUID sub
app/db/base.py              # SQLAlchemy DeclarativeBase
app/db/session.py           # single async engine + async_session_factory; get_db dependency
app/models/                 # ORM tables (source of truth for columns)
app/schemas/                # Pydantic request/response contracts + validators
app/services/
  cycle_calculator.py       # PROTECTED production predictor (robust_wma_v1 logic)
  summary.py                # current-cycle + history summaries; calls predictor + ledger
  prediction_ledger.py      # PROTECTED observational ledger writer/resolver
  backtest.py               # PROTECTED walk-forward harness (evaluation only)
  timezone.py               # PROTECTED canonical user-local date resolver
  profile.py                # get_or_create_profile
  ai_context.py / ai_provider.py / care.py / therapy_policy.py
```

Entrypoint and wiring verified in `app/main.py:24-64` and
`app/api/router.py:1-25`. Production startup is
`uvicorn app.main:app --host 0.0.0.0 --port $PORT` with `/health` as the health
check (`render.yaml:10-12`); `autoDeploy: false` (`render.yaml:12`).

### 1.2 SQLAlchemy models (actual)

Registered in `app/models/__init__.py:1-21`. Ten tables:

| Table | Model file | Grain / key |
|---|---|---|
| `profiles` | `app/models/profile.py` | 1 row per Supabase user; PK `user_id` UUID = `auth.users.id` |
| `cycles` | `app/models/cycle.py` | one row per period occurrence; `UNIQUE(user_id, period_start)` |
| `daily_logs` | `app/models/daily_log.py` | one row per user per calendar day; `UNIQUE(user_id, log_date)` |
| `symptom_logs` | `app/models/symptom_log.py` | child rows of `daily_logs.id` |
| `devices` | `app/models/device.py` (inspected via schema/tests) | user-owned BLE identifiers |
| `therapy_sessions` | `app/models/therapy_session.py` (inspected via schema) | user-owned telemetry, `TIMESTAMPTZ` instants |
| `prediction_ledger` | `app/models/prediction_ledger.py` | one row per *served model prediction* |
| `health_contexts` | `app/models/health_context.py:14-47` | singleton per user (`user_id` PK) |
| `health_conditions` | `app/models/health_context.py:50-94` | one row per user-reported condition |
| `medications` | `app/models/health_context.py:97-128` | one row per user-provided medication |

All user tables FK to `profiles.user_id ON DELETE CASCADE`. Profile deletion
therefore cascades across cycles, logs, devices, therapy, ledger, and all
health tables (verified in model relationships and
`tests/test_health_context.py:468-507`).

### 1.3 Pydantic schemas (actual)

- Cycles: `app/schemas/cycle.py` — `CycleCreate` (`period_start` + nullable
  `period_end`), `CycleUpdate` (partial, explicit-null reopen supported in
  route), `CycleResponse` (+ computed `period_length_days`),
  `CurrentCycleResponse` (status + prediction fields).
- Daily logs: `app/schemas/daily_log.py` — `FlowEnum` (`none/spotting/light/
  medium/heavy`), `MoodEnum` (7 values), `DischargeEnum`
  (`none/light/moderate/heavy` — a volume scale, **not** a cervical-mucus
  fertility scale), 11-item `SUPPORTED_SYMPTOMS` allowlist (pain/digestive/
  energy/physical/skin/sleep/diet/general — **no** LH/BBT/mucus types),
  full-day upsert (`DailyLogCreate`) vs partial PATCH (`DailyLogUpdate` with
  explicit-null clearing).
- Profile: `app/schemas/profile.py` — `usual_cycle_days` 20–45, `usual_period_
  days` 1–12, `timezone` IANA string ≤64, `birth_year`/`birth_month` paired
  month/year precision only (`validate_birth_pair`).
- Health context: `app/schemas/health_context.py` — `ContraceptionMethodEnum`
  (14 values incl. `fertility_awareness`), `PregnancyContextEnum`
  (`trying_to_conceive`, `avoiding_pregnancy`, `pregnant`, `postpartum`,
  `not_applicable`, `prefer_not_to_say`), curated `SUPPORTED_CONDITION_CODES`
  (12 incl. `other`), `other`-label contract, medication-name contract, PUT
  full-replacement vs PATCH partial semantics.
- Summary: `app/schemas/summary.py` — current summary carries `phase`,
  `predicted_next_period`, `days_until_next_period` (never negative),
  `prediction_status` (`upcoming/today/awaiting_next_start`), confidence;
  history carries per-period lengths + symptom frequencies.
- Onboarding: `app/schemas/onboarding.py` — atomic profile + first period
  (`last_period_start`, nullable `last_period_end`, usuals, timezone).

### 1.4 API routers (actual)

Prefix default `/api/v1` (`app/core/config.py:22`):

- `GET /api/v1/auth/me` — identity + auto-provision profile.
- `GET/PATCH/DELETE /api/v1/profile` — preferences, usuals, IANA timezone,
  paired birth fields; DELETE cascades all user data (PostgreSQL only, not
  Supabase Auth user).
- `POST /api/v1/onboarding/complete` — atomic profile + first period,
  idempotent re-onboarding, per-user asyncio lock.
- `GET /api/v1/cycles/current` — active-cycle status + prediction (commits
  ledger snapshot).
- `POST /api/v1/cycles/current/end` — retrospective "ended today" on user-local
  today; strict `period_end <= today`, duration ≤30d.
- `GET/POST /api/v1/cycles`, `PATCH /api/v1/cycles/{id}` — list/create/update;
  overlap validation; duplicate-start **upserts** (returns 201) rather than
  409 (see §2.7); `period_start` keeps intentional +1-day display-only
  tolerance anchored to user-local today; `period_end` is strict.
- `GET /api/v1/symptoms` (public catalogue), `GET /api/v1/logs/{date}`,
  `GET /api/v1/logs`, `POST /api/v1/logs` (full-day upsert, 200),
  `PATCH /api/v1/logs/{id}` (partial, explicit-null clearing).
- `GET /api/v1/summary/current`, `GET /api/v1/summary/history`.
- Devices, therapy, care routes as listed in §1.1 (unchanged by this design).
- Health context (9 routes): `GET/PUT/PATCH /api/v1/health-context`,
  `GET/POST /api/v1/health-context/conditions`,
  `PATCH/DELETE /api/v1/health-context/conditions/{id}`,
  `GET/POST /api/v1/health-context/medications`,
  `PATCH/DELETE /api/v1/health-context/medications/{id}`.

### 1.5 Authentication / JWT handling (actual)

`app/core/security.py:30-211` (`get_current_user`):

- Source: `Authorization: Bearer <Supabase access token>`.
- Header `alg` allowlist: `HS256`, `RS256`, `ES256`; `none`/missing/unknown →
  401.
- `HS256`: verifies with `SUPABASE_JWT_SECRET`; missing secret → 401.
- `RS256/ES256`: verifies via cached JWKS client at `settings.jwks_url`
  (derived from `SUPABASE_URL`, overridable by `SUPABASE_JWKS_URL`); key-fetch
  failures return generic 401 without leaking internals.
- Requires `exp`, `aud`, `iss`, `sub`; verifies expiry; then enforces
  `aud == "authenticated"` exactly and `iss == "{SUPABASE_URL}/auth/v1"`
  exactly; `sub` must parse as UUID.
- Returns the UUID. **Every protected route** depends on it
  (verified across all v1 routers); no route accepts a client-provided
  `user_id` for ownership (extra `user_id` keys are ignored — proven by
  `tests/test_health_context.py:448-465`).

### 1.6 User-scoping rules (actual)

- Every query filters on the JWT `sub` (`Cycle.user_id == current_user_id`,
  same for logs, summary, devices, therapy, health tables).
- Cross-user access by id returns **404**, never 403 with existence leak
  (proven for logs, cycles, conditions, medications in
  `tests/test_production_hardening.py:44-89` and
  `tests/test_health_context.py:376-446`).
- Unauthenticated → 401 on all protected routes.
- `profiles.user_id` is the ownership root; all tables cascade on profile
  delete.

### 1.7 Existing cycle / log endpoints (actual behavior)

- Cycle grain is a **bleeding occurrence** (`period_start` = first bleeding
  day, nullable `period_end` = last bleeding day), **not** a full
  start-to-start cycle record. Cycle *lengths* are derived start-to-start.
- Overlap rule: no two ranges for the same user may overlap; open-ended
  ranges are bounded by user-local today for comparison
  (`app/api/v1/cycles.py:41-71`).
- Exactly one ongoing (`period_end IS NULL`) period at a time; creating while
  one is open → 400.
- Boundary-day collision (previous `period_end ==` new `period_start`) is
  auto-resolved by moving the previous end to yesterday
  (`app/api/v1/cycles.py:260-271`).
- Logs are a full-day upsert keyed on `(user_id, log_date)`; omitted
  `log_date` defaults to user-local today; supplied dates are preserved
  exactly.

### 1.8 Existing prediction endpoints (actual)

Served through `GET /api/v1/cycles/current` and
`GET /api/v1/summary/current`, computed by `app/services/summary.py:23-230`:

- Training set: `calculate_cycle_lengths(periods, today)` —
  start-to-start deltas filtered to 15–90d, **only** `period_start <= today`
  (`app/services/cycle_calculator.py:45-75`, Rule B).
- Predictor `predict_next_cycle`: up to 6 most recent valid intervals →
  median + MAD → drop `|x − median| > 2·MAD` (MAD == 0 keeps median-equal
  only) → recency-weighted mean (weights 1..m) → round → clamp 20–45
  (`app/services/cycle_calculator.py:78-174`).
- Zero-history fallback: `usual_cycle_days` (if 20–45) with
  `source="usual_cycle"`, `confidence="low"`; else `source/confidence =
  "insufficient_data"` with null prediction — **no silent 28-day fallback**
  (Rule D).
- Confidence: 1–2 intervals → `low`; 3–4 → `moderate` iff MAD ≤ 4.0 else
  `low`; 5–6 → `high` iff MAD ≤ 3.0, `moderate` iff MAD ≤ 6.0, else `low`.
- Served fields: `predicted_cycle_length`, `predicted_next_period`
  (`active_start + length`), `days_until_next_period` (clamped ≥ 0),
  `prediction_status` (`upcoming/today/awaiting_next_start`), `confidence`,
  `source` (`history/usual_cycle/insufficient_data/user_logged`).
  A future user-logged start overrides the model as display-only
  (`source="user_logged"`, `confidence="high"`).
- `estimate_phase` is an **educational** label (`menstrual/follicular/
  ovulation/luteal/unknown`), count-back `ovulation ≈ length − 14`, no silent
  28-day default; bleeding → `menstrual`; unknown length + not bleeding →
  `unknown` (`app/services/cycle_calculator.py:177-208`). The existing
  `ovulation` phase label is **not** a fertile-window estimate and must not be
  presented as one.

### 1.9 Prediction ledger (actual)

`app/models/prediction_ledger.py:11-58`, `app/services/prediction_ledger.py`:

- Identity: `BASELINE_METHOD = "robust_wma_v1"`; `MODEL_SOURCES = ("history",
  "usual_cycle")` — display-only `user_logged` and empty predictions are
  never recorded.
- `maybe_record_served_prediction`: snapshots `predicted_at` (user-local
  today), `method`, `predicted_cycle_length`, `predicted_next_period`,
  `confidence`, `source`, `basis_start`, `basis_intervals`, `basis_usual`
  (verbatim at serve time), `variability` (MAD); flushes, does not commit;
  serving route commits.
- `resolve_for_new_start`: on each newly logged start, resolves **every** open
  entry with `basis_start < new_start`, setting `resolved_actual_start` and
  signed `error_days = actual − predicted`; idempotent; flushes, does not
  commit. Never influences responses.

### 1.10 Backtest harness (actual)

`app/services/backtest.py`: evaluation-only, leakage-proof by construction.
Inputs must be strictly ascending starts; to score `starts[k]` only
`starts[:k]` + constant `usual` are visible; intervals re-derive with the
production 15–90d rule; `baseline_predict` **imports** `predict_next_cycle`
(never a copy) so the baseline *is* production behavior. `walk_forward` →
`BacktestPoint`s; `summarize` → MAE/bias/within-1/within-2 over predicted
points only. Untouched by serving paths.

### 1.11 Timezone handling (actual)

`app/services/timezone.py:1-109`, profile column
`app/models/profile.py:31-34`:

- Canonical store: `profiles.timezone`, one IANA identifier (e.g.
  `Asia/Kolkata`), validated by `ZoneInfo` lookup, ≤64 chars, never an
  offset/abbreviation.
- Canonical rule: **instant → stored IANA zone → local calendar date**
  (`user_today`, `user_today_for`). All summary/status/countdown/default/
  validation paths use it. Historical DATEs are never re-resolved.
- Legacy `NULL` timezone = transitional: falls back to UTC date (documented,
  never silent); mobile persists the device zone on next authenticated
  session (onboarding accepts `timezone`; profile PATCH accepts it).
- `DATE` vs `TIMESTAMPTZ` discipline is load-bearing (module docstring +
  `README.md` timezone section): DATEs are user calendar dates, never shifted
  through UTC; instants stay UTC.

### 1.12 Database migration structure (actual)

- Fresh databases: `supabase_initial_schema.sql` (canonical DDL, §§1–9).
- Existing databases: `migrations/` applied **in filename order**.
- Present files: `0002_add_profile_timezone.sql` (nullable `profiles.timezone`,
  no backfill), `0003_enable_rls_defense_in_depth.sql` (RLS on the 7
  pre-health tables), `0004_health_context_v1.sql` (nullable birth columns +
  3 new health tables + their RLS).
- **There is no `0001` file in the repo.** The implied `0001` is the initial
  schema itself (now represented by `supabase_initial_schema.sql`).
- Convention (per `README.md` development rules): every new column updates
  model + fresh schema + migration + tests, keeping fresh schema and
  migrations agreeing.

### 1.13 Current migration sequence (actual)

1. (Implied initial — profiles, cycles, daily_logs, symptom_logs, devices,
   therapy_sessions, prediction_ledger; no file in repo.)
2. `0002` — add `profiles.timezone`.
3. `0003` — enable RLS (default-deny) on the 7 tables existing at that time.
4. `0004` — health-context V1 (birth columns + 3 tables + their RLS).

Note: `0003` does **not** mention the health tables (they did not exist yet);
`0004` covers the health-table RLS gap. The fresh schema covers all 10
tables. Any future table must follow the same pattern (DDL + RLS in the same
migration).

### 1.14 Current production assumptions (actual)

- `AUTO_CREATE_TABLES` defaults `false` and **must stay `false` in
  production** (`app/main.py:14`, `render.yaml:26-27`); schema comes from SQL
  files, except sqlite-test `create_all`.
- Single privileged DB role (bypasses RLS); app-level `user_id` filtering is
  the primary enforcement; RLS is default-deny defense-in-depth with **no**
  permissive policies; no `auth.uid()` policies; no `FORCE RLS`
  (`supabase_initial_schema.sql:177-205`).
- Flutter app is the only client (HTTPS + Supabase JWT); browsers never talk
  to the backend directly; CORS wildcard never pairs with credentials
  (`app/main.py:32-43`).
- Care/LLM output is advisory text only; therapy is deterministic equations
  with a 44.0 °C ceiling; no LLM-to-hardware path.
- Mobile owns UI/offline storage/BLE/Daily Insight local library; server is
  authoritative for prediction/phase math.
- Tests run on in-memory sqlite via `Base.metadata.create_all`; they never
  touch real infrastructure (`tests/conftest.py`).

### 1.15 Existing Health Context implementation / migrations (actual — ACTIVE, not dormant)

- Migration `0004_health_context_v1.sql` **exists** and the fresh schema
  §§8–9 includes the same tables: `health_contexts` (singleton
  contraception/pregnancy/free-text), `health_conditions` (allowlist +
  `other` + partial unique index), `medications`, plus
  `profiles.birth_year/birth_month`.
- ORM, schemas, 9 endpoints, and ~700 lines of tests exist
  (`tests/test_health_context.py`), including: defaults-when-unset,
  PUT-full-replacement vs PATCH-partial semantics, enum rejection (422),
  free-text limits (1000/2000, reject-don't-truncate), condition label
  contract, duplicate → 409, cross-user isolation (404), client `user_id`
  ignored, cascade on profile delete, DOB lifecycle/validation, and the
  **prediction-independence proof**
  (`test_health_context_does_not_alter_predictions`).
- Health values are stored verbatim and returned to the owner only; they
  never alter predictions, never diagnose, never infer.
- Verdict: Health Context is **implemented and served**, not dormant. Nothing
  about it should be "activated" in this phase — it is already active. See
  §3 item 10 and §7 for the "do not apply dormant migrations" confirmation.

### 1.16 Tests covering the above (actual)

`pytest.ini` (`testpaths = tests`, `asyncio_mode = auto`); suite snapshot per
`README.md`: 162 collected / 159 passing / 3 known pre-existing failures, all
in duplicate-start upsert expectations (`test_api_contract_409…`,
`test_cycle_overlapping…`, `test_cycle_duplicate…`): implementation
intentionally upserts a same-user duplicate start (201); the tests expect
409/400; behavior left unchanged for backward compatibility.

Coverage map: `test_auth.py` (JWT matrix), `test_api_contract.py`,
`test_cycles/logs/onboarding/summary` (routes + validation),
`test_cycle_calculator.py` (math vectors, explicit `today`),
`test_backtest.py` (walk-forward equivalence),
`test_prediction_ledger.py`, `test_timezone.py` (frozen-clock, midnight
boundaries, fallback), `test_care.py`, `test_therapy_and_devices.py`,
`test_health_context.py` (above), `test_production_hardening.py`
(auth/IDOR/validation/config).

---

## 2. Current database state

Authoritative sources: `supabase_initial_schema.sql`, `app/models/*`,
`migrations/0002-0004`. Production database contents were **not** inspected
(no live DB access in this phase); what follows is the *schema* state the
code requires.

### 2.1 `profiles`

`user_id UUID PK → auth.users.id CASCADE`, `name`, `usual_cycle_days`
(20–45), `usual_period_days` (1–12), `theme`, `units`, `sensitivity_index`
0.5–1.5, `timezone VARCHAR(64)` nullable, `birth_year` (1900–2100) +
`birth_month` (1–12) nullable and always set/cleared together,
`created_at/updated_at TIMESTAMPTZ`.

### 2.2 `cycles` (period/cycle records)

`id SERIAL PK`, `user_id UUID → profiles CASCADE indexed`,
`period_start DATE NOT NULL`, `period_end DATE NULL`,
`CHECK (period_end IS NULL OR period_end >= period_start)`,
`UNIQUE(user_id, period_start)`, index `(user_id, period_start)`.
Semantics: bleeding occurrences; full-cycle lengths derived start-to-start.

### 2.3 `daily_logs` + `symptom_logs`

`daily_logs`: `id`, `user_id → profiles CASCADE`, `log_date DATE NOT NULL`,
`UNIQUE(user_id, log_date)`, `pain 0–10`, `mood/discharge/flow VARCHAR(32)`
nullable, `notes TEXT`, instants. `symptom_logs`: `id`, `daily_log_id →
daily_logs CASCADE`, `symptom_type VARCHAR(64)`, `severity 0–10`.
`discharge` is a volume scale (`none/light/moderate/heavy`); there is **no**
fertile-quality mucus scale. Symptom taxonomy is fixed at 11 ids; there are
**no** LH/BBT/mucus symptom types.

### 2.4 Prediction records / ledger

`prediction_ledger`: `id`, `user_id → profiles CASCADE`,
`predicted_at DATE`, `method VARCHAR(64)`, `predicted_cycle_length INT NULL`,
`predicted_next_period DATE NULL`, `confidence`, `source`, `basis_start DATE`,
`basis_intervals INT`, `basis_usual INT NULL`, `variability FLOAT NULL`,
`resolved_actual_start DATE NULL`, `error_days INT NULL`, `created_at
TIMESTAMPTZ`; indexes on `(user_id)` and `(user_id, predicted_at)`.
Observational only; never read in request paths except analysis.

### 2.5 Health Context tables

As §1.15: `health_contexts(user_id PK, contraception_method VARCHAR(32),
contraception_note TEXT, pregnancy_context VARCHAR(32), health_notes TEXT,
instants)`; `health_conditions(id, user_id, condition_code VARCHAR(64),
custom_label VARCHAR(128) NULL, note TEXT, is_active BOOL, instants)` with
partial unique index `(user_id, condition_code) WHERE custom_label IS NULL`;
`medications(id, user_id, name VARCHAR(128), note TEXT, is_active BOOL,
instants)`.

### 2.6 RLS

Enabled (no policies = default-deny) on **all 10 tables** in the fresh schema.
Migration `0003` covers the original 7; `0004` covers the 3 health tables.
Primary isolation remains app-level `user_id` filtering over a privileged
connection. No `auth.uid()` policy, no `FORCE RLS` — both explicitly
forbidden by schema comments.

### 2.7 User ownership / timezone fields / reproductive fields

- Ownership: every row carries `user_id` (except `symptom_logs`, owned
  transitively via `daily_logs`); no client-supplied ownership.
- Timezone: only `profiles.timezone`; no per-record zone/offset columns
  anywhere (by design — one canonical zone per user).
- Reproductive-health fields present today: **only**
  `health_contexts.pregnancy_context` (6-value intent selection),
  `contraception_method = fertility_awareness` (a contraception choice, not an
  observation), `profiles.birth_year/birth_month` (month precision, reusable
  for aging context), and the educational `phase = ovulation` label (not an
  estimate). There are **no** LH/BBT/mucus columns, **no** pregnancy-mode
  state machine, **no** EDD/dating-source columns, **no** fertile-window or
  ovulation-estimate columns, **no** perimenopause/aging columns, and **no**
  tables for any of the above.

---

## 3. Phase 0 reconciliation

### 3.1 Where the Phase 0 documents are

The three Phase 0 documents named in the phase brief
(`docs/reproductive-health-spec.md`, `docs/reproductive-evidence-library.md`,
`docs/reproductive-safety-boundaries.md`) are **not present in this backend
repository**. There is no `docs/` directory at HEAD (verified: `Test-Path
docs == False` before this phase; `git ls-files` lists no `docs/*`), and the
`mobile/` path is an **uninitialized git submodule** (gitlink `298fd10…`,
empty working tree, `fatal: no submodule mapping found in .gitmodules for
path 'mobile'` when queried), so the "mobile repository Phase 0
documentation" is not readable from this checkout.

Per the brief, the Phase 0 documents were therefore **not recreated or
modified**. The reconciliation below compares the *backend reality*
(verified above) against each *unresolved question called out in the brief*,
so the mobile/backend discrepancy for each question is explicit even without
the Phase 0 text in front of us. Anything below labeled "assumed Phase 0
expectation" is flagged as an assumption to be confirmed against the real
Phase 0 docs — backend facts are not assumptions.

### 3.2 Question-by-question discrepancies / resolutions required

1. **Minimum history requirements.** Backend truth: the period predictor
   needs ≥1 valid 15–90d interval for a history-based prediction, else falls
   back to `usual_cycle_days`, else `insufficient_data` (no 28-day default).
   Confidence needs 3–4 intervals for `moderate`, 5–6 + low MAD for `high`.
   If Phase 0 specifies a *fertility* minimum history (e.g. "N cycles before
   showing a fertile window"), **no such gate exists in the backend** — it
   must be designed (see §10, deferred threshold decision D1). Do not reuse
   the period-predictor thresholds silently for fertility.
2. **Cycle variability representation.** Backend truth: robust MAD (days),
   rounded to 1 decimal, stored per ledger row as `variability`; confidence
   derives from interval count + MAD thresholds (§1.8). Ordinary std-dev is
   never used (the `variability_std_dev` field name carries MAD for API
   compatibility). If Phase 0 assumes classic SD or a different variability
   window, that is a **naming/semantics conflict** to resolve: fertility
   estimates should carry their own explicitly-named variability field (see
   §4.4), not overload the period MAD.
3. **Fertile-window data requirements.** Backend truth: there is **no**
   fertile-window input or output anywhere. `discharge` is a volume scale,
   symptom taxonomy has no LH/BBT/mucus types, and `phase = ovulation` is an
   educational count-back label, not evidence. Any Phase 0 requirement naming
   LH/BBT/mucus as fertile-window inputs has **no backend counterpart yet** —
   the observation tables in §4.1 are the missing piece (REQUIRED FOR
   FERTILITY V1).
4. **Late-period behavior.** Backend truth: `days_until_next_period` clamps at
   0 and `prediction_status` becomes neutral `awaiting_next_start` (Rule F);
   no alarmist language, no automatic re-prediction, no late flag. If Phase 0
   specifies late-period messaging, escalation, or pregnancy-prompt behavior,
   that behavior is **not implemented** and must go through the
   pregnancy-mode contract (§8), not through changes to the predictor.
5. **Pregnancy-mode state.** Backend truth: there is **no pregnancy mode**.
   `pregnancy_context = pregnant` is a free user selection with zero
   behavioral effect (predictions explicitly ignore it — proven by test).
   Any Phase 0 "pregnancy mode" (prediction suppression, UI state, data
   handling) has **no backend enforcement** and must be built as the new
   explicit state in §4.2/§8. The old `pregnancy_context` string must not be
   reinterpreted as that state without a migration/coexistence decision (D5).
6. **Pregnancy dating source.** Backend truth: no EDD, no LMP, no ultrasound,
   no clinician-dating columns exist. Any Phase 0 dating-source taxonomy has
   no backend counterpart; the proposed `dating_source` enum (§4.2) is new
   and intentionally narrow (LMP / ultrasound / clinician / unknown) pending
   product/clinical sign-off (D2).
7. **Pregnancy cache / data withholding.** Backend truth: nothing is withheld
   today — summaries always compute from cycle history regardless of
   `pregnancy_context`, and all records are returned in normal queries. Any
   Phase 0 requirement to suppress/hide predictions or history during
   pregnancy is **not implemented** and is a product decision with sync
   implications (D6, §6.5). This design proposes the *state* that would allow
   withholding, not the withholding itself.
8. **Perimenopause / aging context.** Backend truth: no aging table, no
   perimenopause field, no detection logic. Only reusable raw material is
   `birth_year/birth_month` (month precision) + full cycle history. Any Phase
   0 perimenopause staging, symptom-mapping, or age-based adjustment has no
   backend counterpart and must remain **contextual only, never diagnostic**
   (§11). No `perimenopause` diagnosis column is proposed, deliberately.
9. **Notification implications.** Backend truth: local-notification scheduling
   is **planned, not built** (`README.md`); timezone work unblocks it but no
   scheduler, queue, or fertile-window/p regnancy trigger exists. Any Phase 0
   notification contract (fertile-window alerts, EDD reminders, late-period
   nudges) has no backend endpoint to attach to yet — all estimate/pregnancy
   endpoints in §5 are marked accordingly, and notification design is
   deferred (D8).
10. **Health Context status.** Backend truth: **active and served** (§1.15),
    not dormant. If Phase 0 describes Health Context as planned/dormant, that
    description is **stale** and must be updated on the mobile side. Do not
    design as if these tables need activation; they already exist and are
    covered by RLS + tests.
11. **RLS status.** Backend truth: **enabled default-deny on all 10 tables,
    no permissive policies**, privileged-connection architecture (§2.6). If
    Phase 0 assumes per-user `auth.uid()` policies enforce isolation, that is
    **architecturally incorrect** for this backend and must be corrected:
    adding such policies would be dead code at best and a PostgREST hole at
    worst. New tables must follow the same default-deny pattern (§12).
12. **Migration status.** Backend truth: sequence is implied-initial → 0002 →
    0003 → 0004 (§1.13); fresh schema and migrations agree at HEAD; Health
    Context migration `0004` is part of the canonical state, not dormant.
    "Whether `0004` is applied" cannot be determined from the repo alone —
    it is a **production-database fact** requiring human confirmation (D9).
    Nothing in this phase applies migrations.

---

## 4. Proposed additive data model (DESIGN — not implemented)

Conventions for everything below: `user_id UUID → profiles.user_id ON DELETE
CASCADE`; `DATE` = user-local calendar date (never shifted); `TIMESTAMPTZ` =
instant; every table gets default-deny RLS (no policies) in the same
migration that creates it; no client-supplied `user_id`; no change to any
existing table's columns or semantics.

### 4.1 A. Fertility observations

**Proposed new table `fertility_observations`** (name bikeshed-able; the
grain is the point): one row per user-measured fact.

| Column | Type | Notes |
|---|---|---|
| `id` | SERIAL PK | surrogate; client uses opaque id for sync |
| `user_id` | UUID NOT NULL → profiles CASCADE | ownership; indexed |
| `observation_date` | DATE NOT NULL | user-local calendar date the sample applies to (not the upload instant) |
| `observation_type` | VARCHAR(32) NOT NULL | `lh_test` \| `bbt` \| `cervical_mucus` (closed enum, extendable only by migration) |
| `lh_result` | VARCHAR(16) NULL | only for `lh_test`: `positive` \| `negative` \| `invalid`; NULL otherwise |
| `bbt_celsius` | NUMERIC(4,2) NULL | only for `bbt`: e.g. 35.00–42.00 range check; NULL otherwise |
| `mucus_category` | VARCHAR(32) NULL | only for `cervical_mucus`: closed set TBD by product/clinical (e.g. `dry/sticky/creamy/watery/egg_white` — **placeholder, requires sign-off D3**); NULL otherwise |
| `recorded_at` | TIMESTAMPTZ NOT NULL DEFAULT NOW() | instant the row was stored |
| `source` | VARCHAR(32) NOT NULL DEFAULT `manual` | `manual` \| `imported`; device-source values deferred |
| `note` | TEXT NULL (≤1000) | verbatim user note, never parsed |
| `created_at / updated_at` | TIMESTAMPTZ | standard instants |

Constraints (proposed): `CHECK` that exactly the value column matching
`observation_type` is non-null and the others are null; `CHECK` ranges for
BBT; partial unique index `UNIQUE(user_id, observation_date,
observation_type)` for LH/mucus (one result per day) but **allow multiple BBT
rows per day? No — one per day** (decide: one row per user/day/type keeps
offline upsert deterministic; intraday repeats overwrite). Index
`(user_id, observation_date)`.

**Observation vs estimate (load-bearing distinction):** an *observation* is a
user-measured fact bound to a calendar date (`fertility_observations`); an
*estimate* is a server-computed inference bound to an as-of date
(`fertility_estimates`, §4.4). Observations never carry confidence, method
version, or window dates. Estimates never masquerade as measurements: they
carry `evidence_source = estimated` and full provenance. A future
clinician-confirmed ovulation date is neither — it carries
`evidence_source = clinically_confirmed` and is stored on the estimate row
(see §4.4), not as an observation.

What is deliberately **not** in this table: fertile windows, ovulation dates,
confidence, scores, predictions, device raw waveforms, photo uploads.

### 4.2 B. Pregnancy context

**Proposed new singleton table `pregnancy_contexts`** (one row per user that
has ever entered pregnancy mode; absence = never entered / never activated):

| Column | Type | Notes |
|---|---|---|
| `user_id` | UUID PK → profiles CASCADE | singleton |
| `is_active` | BOOLEAN NOT NULL DEFAULT TRUE | explicit user-controlled mode switch; FALSE = history retained, mode off |
| `status` | VARCHAR(32) NOT NULL | `pregnant` \| `postpartum` \| `trying_to_conceive` \| `avoiding_pregnancy` — closed enum; `not_applicable/prefer_not_to_say` intentionally **excluded** (those remain `health_contexts` selections, not mode) |
| `confirmation_date` | DATE NULL | user-local date pregnancy was confirmed (test/clinician); NULL if unconfirmed/trying |
| `estimated_due_date` | DATE NULL | user-local calendar date; required when `status = pregnant` and dating is known, else NULL |
| `dating_source` | VARCHAR(32) NULL | `lmp` \| `ultrasound` \| `clinician` \| `unknown`; required when EDD set, else NULL. Narrow by design — no invented clinical fields (no CRL, no gestational-age-at-scan, no provider NPI, etc.) |
| `dating_note` | TEXT NULL (≤1000) | verbatim user/clinician note (e.g. "dating scan 12w"); never parsed into medical facts |
| `created_at / updated_at` | TIMESTAMPTZ | instants |

Validation (proposed, server-enforced): `estimated_due_date` must be a real
calendar DATE (no UTC shifting); EDD required iff `status = pregnant` AND
`dating_source IS NOT NULL`? Simpler: EDD + dating_source are jointly
nullable but **must be set-or-cleared together** when `status = pregnant`
(decision D2 to finalize); `confirmation_date <= user-local today`;
`confirmation_date <= estimated_due_date` when both set; `is_active = FALSE`
retains the row (history) but mode is off; re-activation requires explicit
PUT/PATCH (no auto-reactivation from cycle logging).

Coexistence with legacy `health_contexts.pregnancy_context`: the legacy free
selection **stays as-is** (user-provided context, never behavioral). The new
mode table is the only behavioral pregnancy state. A one-time UX copy
("you selected pregnant — enable pregnancy mode?") is a product decision,
never an automatic migration (D5). No backfill.

### 4.3 C. Reproductive-aging context

**Minimum persistent state: none beyond what exists.** The backend already
stores `profiles.birth_year/birth_month` (month precision) and complete cycle
history (lengths + MAD variability + period durations) — that is the full
evidence base a future contextual layer needs.

Proposed: **no new aging table for V1**. If a persistence anchor is later
required (e.g. to remember a user-acknowledged "patterns have changed" note),
add a minimal singleton `reproductive_aging_context(user_id PK, notes TEXT
NULL ≤2000, updated_at)` — free-text context only, mirroring the health-notes
pattern. Explicitly **no** `perimenopause_stage`, `menopause_status`, or any
diagnosis/staging column. Any age-derived display (e.g. "at 47, variability
often rises") is computed at read time from birth fields + history, never
stored as a diagnosis. See §11.

### 4.4 D. Fertility estimates

**Proposed new table `fertility_estimates`** (server-computed, client
read-only): one row per as-of date per user (latest row = current estimate;
history retained for the same evolution-analysis reasons as the prediction
ledger).

| Column | Type | Notes |
|---|---|---|
| `id` | SERIAL PK | |
| `user_id` | UUID NOT NULL → profiles CASCADE, indexed | |
| `estimate_date` | DATE NOT NULL | user-local as-of date (the "today" the estimate was calculated for) |
| `ovulation_date_estimate` | DATE NULL | user-local calendar date; NULL when insufficient evidence |
| `fertile_window_start / fertile_window_end` | DATE NULL | inclusive user-local dates; both NULL or both set; `start <= end`; span cap (e.g. ≤10d, TBD D1) |
| `confidence` | VARCHAR(32) NOT NULL | `insufficient` \| `low` \| `moderate` \| `high` (fertility-specific thresholds, TBD D1 — **not** the period-predictor thresholds) |
| `evidence_source` | VARCHAR(32) NOT NULL | **OBSERVED \| ESTIMATED \| CLINICALLY_CONFIRMED** (per-row dominant provenance; see below) |
| `evidence` | JSONB NULL | source metadata: counts of LH/BBT/mucus rows used, cycle intervals used, basis start, flags (e.g. `{"lh_positive_dates": [...], "bbt_points": n, "cycle_intervals": n}`); schema-versioned (`evidence_schema_version INT`) |
| `method` | VARCHAR(64) NOT NULL | estimator identity, e.g. `fertility_v1` (frozen label like `robust_wma_v1`) |
| `method_version` | VARCHAR(32) NOT NULL | semver of the estimator; bumped only when the estimator changes |
| `calculated_at` | TIMESTAMPTZ NOT NULL DEFAULT NOW() | instant of calculation |
| `timezone_name` | VARCHAR(64) NOT NULL | IANA zone the as-of date was resolved in (audit for DST boundaries) |
| `created_at` | TIMESTAMPTZ | |

`OBSERVED vs ESTIMATED vs CLINICALLY_CONFIRMED` (proposed semantics):
- `OBSERVED`: the row's anchor is a directly measured fact (e.g. a positive
  LH row exists for the window; the estimate row cites it). The estimate still
  carries uncertainty — OBSERVED describes the *evidence*, not certainty.
- `ESTIMATED`: model/calendar inference from cycle history without
  same-cycle biomarker confirmation (the default until biomarker gates pass).
- `CLINICALLY_CONFIRMED`: a clinician-established date the user entered
  (e.g. ultrasound-confirmed ovulation); stored only via an explicit
  clinician-source write path (deferred endpoint), never inferred.

Unique/index: `UNIQUE(user_id, estimate_date, method, method_version)` (one
estimate per method-version per day; re-serves update in place or append —
decision locked to append-only in §5.4); index `(user_id, estimate_date DESC)`.

What is deliberately **not** here: pregnancy math, period prediction (that
stays in `cycle_calculator` + ledger), scores surfaced as diagnoses,
free-text medical advice.

---

## 5. Proposed API contracts (DESIGN — not implemented)

All routes: `Authorization: Bearer <Supabase JWT>` required (401 when
missing/invalid); ownership = JWT `sub`; **no `user_id` in request bodies**
(extra keys ignored/rejected); cross-user id access → 404; validation
failures → 422 (Pydantic) or 400 (domain rules, matching existing cycle
conventions); success codes mirror existing conventions (GET 200, POST-create
201, PUT/PATCH 200, DELETE 204).

Recommended structure: a **new `reproductive` router** (`/api/v1/reproductive/*`)
rather than overloading `/cycles`, `/logs`, or `/health-context`. Rationale:
fertility observations are neither bleeding occurrences nor symptom logs
(different grain, enums, and validation); pregnancy mode is behavioral state,
not free health context; estimates are server-computed and read-only. A
dedicated router keeps the protected predictor paths untouched and gives RLS/
sync rules one place to live. (Alternative considered and rejected: stuffing
LH/BBT/mucus into `symptom_logs` — would pollute the fixed 11-id taxonomy,
break the severity 0–10 contract, and blur observation/estimate provenance.)

### 5.1 `POST /api/v1/reproductive/observations` — record an observation

- Auth: required. Ownership: row stamped with JWT `sub`.
- Request: `{ observation_date? (DATE, default user-local today), observation_type: lh_test|bbt|cervical_mucus, lh_result?|bbt_celsius?|mucus_category?, source?: manual|imported, note? ≤1000 }` with the §4.1 exactly-one-value-column rule.
- Response 201: the created row (id, all columns, instants).
- Validation: DATE preserved exactly (no UTC shift); `observation_date <=
  user-local today + 1` (same display tolerance as cycles; strictness TBD D4);
  BBT range; mucus enum; note length.
- Offline/sync: idempotent upsert key `(user_id, observation_date,
  observation_type)` — re-POST overwrites (200 on overwrite vs 201 on create,
  mirroring log upsert); last-writer-wins by `updated_at`; safe to retry.
- Errors: 400 future-date/duration-equivalent, 409 only on true races (unique
  violation → return existing), 422 enum/range.
- Needed now or deferred: **REQUIRED FOR FERTILITY V1.**

### 5.2 `GET /api/v1/reproductive/observations?start_date&end_date&type` — list own observations

- Auth: required. Response 200: array newest-first (or oldest-first with
  explicit `order=`; default newest-first to match logs).
- Range validation: `start_date <= end_date` else 422 (mirrors logs).
- Needed: **REQUIRED FOR FERTILITY V1** (powers fertile-window evidence + UX).

### 5.3 `PATCH /api/v1/reproductive/observations/{id}` and `DELETE .../{id}` — correct / retract

- PATCH: partial, explicit-null clearing for `note` only; type/value changes
  allowed only within the same `observation_type` (no morphing LH→BBT);
  date moves re-check the unique key. DELETE: 204, hard delete (observations
  are user facts; retraction is a delete, not a flag).
- Cross-user id → 404. Needed: **REQUIRED FOR FERTILITY V1** (data-correction
  + sync tombstones via delete-then-pull).

### 5.4 `GET /api/v1/reproductive/estimates?as_of?` — read current/past fertility estimate

- Auth: required. Response 200: latest estimate row for the user (`as_of`
  defaults to user-local today), including `evidence_source`,
  `confidence`, `method/method_version`, `calculated_at`, `timezone_name`.
  History access via `?start_date&end_date` (append-only table; re-serves of
  the same as-of date **append** a new row under the same
  `(user_id, estimate_date)` with a newer `calculated_at` — evolution data
  preserved, paralleling the prediction ledger's resolve-all-open-rows
  philosophy).
- No POST/PUT/PATCH: estimates are **server-computed, client read-only**.
  The compute trigger (on observation write? on summary read? scheduled?) is
  deferred to Phase 2 (D7) — this contract only fixes the read shape.
- `confidence = insufficient` with all date fields null is a valid 200
  response (mirrors `insufficient_data`), never a 404.
- Needed: **REQUIRED FOR FERTILITY V1 (read side)**; compute job deferred.

### 5.5 `GET /api/v1/reproductive/pregnancy` — read pregnancy mode

- Auth: required. Response 200: the singleton row, or
  `{ is_active: false, status: null, ...nulls }` when never entered
  (mirrors health-context defaults-when-unset).
- Needed: **REQUIRED FOR PREGNANCY MODE.**

### 5.6 `PUT /api/v1/reproductive/pregnancy` (full sync upsert) and `PATCH ...` (partial)

- PUT: every field set from payload, omitted → null (mirrors health-context
  PUT); creates on first sync. PATCH: `model_fields_set` semantics, explicit
  null clears (mirrors health-context PATCH).
- Request fields: `is_active, status, confirmation_date, estimated_due_date,
  dating_source, dating_note` with §4.2 joint validation.
- Offline/sync: PUT is the offline-restore path (last-writer-wins);
  `is_active: false` is how the client turns mode off (row retained).
- Errors: 422 enum/DATE-shape, 400 domain (EDD/confirmation ordering,
  joint-null rule).
- Needed: **REQUIRED FOR PREGNANCY MODE.** No auto-activation from cycle
  logging; only these endpoints flip the mode.

### 5.7 `DELETE /api/v1/reproductive/pregnancy` — exit + erase pregnancy state

- Auth: required. 204. Hard-deletes the singleton row (distinct from
  `PATCH {is_active:false}` which retains history). Needed: **REQUIRED FOR
  PREGNANCY MODE** (GDPR-style erasure + "not pregnant any more" path).

### 5.8 `GET/PUT /api/v1/reproductive/aging-context` — minimal aging notes (DEFERRED)

- Shape: `{ notes? ≤2000 }`, same auth/ownership/sync semantics as
  health-notes. No diagnosis fields by construction.
- Needed: **DEFERRED** — do not build until the contextual layer has an
  approved UX that needs persistence beyond birth fields + history.

### 5.9 Explicitly deferred endpoints

- `POST /api/v1/reproductive/estimates` (client-written estimates) — never;
  estimates stay server-computed.
- Clinician-confirmed ovulation write path (`POST .../estimates/confirm`) —
  deferred until a verified-clinician flow exists (prevents fake
  `CLINICALLY_CONFIRMED` rows).
- Notification-scheduling endpoints — deferred (no scheduler exists; D8).
- Bulk import/export beyond the PUT-sync paths — deferred.

---

## 6. User-scoping / privacy model

### 6.1 JWT identity source

Sole source: `get_current_user` (`app/core/security.py`) — Supabase JWT
`sub` UUID after signature/expiry/`aud`/`iss` enforcement. No API key, no
cookie session, no service-token impersonation in request paths.

### 6.2 Ownership enforcement

- All new tables carry `user_id`; all new queries filter `== current_user_id`;
  singleton reads use `WHERE user_id == sub`; id-addressed writes add `AND id
  == path_id` and return 404 on miss (no existence oracle).
- Request bodies must not contain `user_id`; servers ignore or reject it
  (follow the proven `test_client_supplied_user_id_is_ignored` pattern with a
  dedicated test per new endpoint).

### 6.3 Read/write authorization

- Authenticated user: full CRUD on own reproductive rows; read own estimates.
- Other users (including authenticated): zero access (404).
- Unauthenticated: 401 everywhere except the existing public `/`, `/health`,
  `GET /api/v1/symptoms`.
- No roles, no sharing, no clinician read path in V1 (deferred with the
  confirm endpoint).

### 6.4 Expected RLS posture

Same as existing: `ENABLE ROW LEVEL SECURITY` with **no permissive policies**
on every new table, in the creating migration. Documents the guarantee
accurately: RLS denies direct PostgREST/anon access; app-level filtering over
the privileged connection remains the enforcement point. Never add
`auth.uid()` policies or `FORCE RLS` without a connection-architecture change.

### 6.5 Privacy-sensitive fields

Highest sensitivity: `mucus_category`, `lh_result`, `bbt_celsius`,
pregnancy `status`/`edd`/`dating_source`, aging `notes`. All are
intimate-health data: never log values at INFO, never include in error
details, never emit in analytics without explicit consent architecture
(out of scope). Cascade-delete with profile (GDPR erasure via existing
`DELETE /api/v1/profile` must cover the new tables — add the relationships +
  a cascade test).

### 6.6 Sync-payload guidance

- Observations + pregnancy singleton: **include** in normal offline-sync
  payloads (small, user-authored, needed offline). PUT-full-replacement is
  the restore path.
- Estimates: **exclude** from upload sync (server-computed); cache read-only
  on device with `calculated_at` + `method_version` staleness labels; re-pull
  on `as_of` change or new observation ack.
- Withholding during pregnancy (hide fertile windows / pause period
  countdown): **not decided** — requires product decision D6 before any
  summary/estimate read path branches on `is_active`. This design enables the
  branch point but does not specify the branch.

---

## 7. Timezone / date semantics

The existing canonical model is preserved unchanged and extended to the new
tables:

- `instant → stored IANA timezone → local calendar date.` The only zone
  source remains `profiles.timezone`; the only resolvers remain
  `user_today` / `user_today_for`. No per-record zone columns, no
  offset/abbreviation storage, no new fallback.
- `observation_date`, `confirmation_date`, `estimated_due_date`,
  `estimate_date`, `ovulation_date_estimate`, `fertile_window_start/end` are
  all **DATE-only**: stored as `DATE`, compared as dates, serialized as
  `YYYY-MM-DD`, never passed through UTC conversion. A user in `Asia/Kolkata`
  logging at 00:30 IST keeps that IST calendar date even though UTC is still
  "yesterday".
- `recorded_at`, `calculated_at`, `created_at`, `updated_at` are
  **TIMESTAMPTZ instants** (UTC storage).
- Estimate rows persist the `timezone_name` used for their as-of resolution
  so DST-boundary disputes are auditable.
- Validation bounds (`observation_date <= user-local today (+1 display
  tolerance TBD)`, `confirmation_date <= today`) always use the caller's
  user-local today, never `date.today()` on the server. Schema-level coarse
  guards (server-relative) may mirror the existing cycle/log pattern, with
  routes enforcing the exact user-local bound.
- No modification to `app/services/timezone.py`, no backfill of historical
  DATEs, no reinterpretation of existing `period_start/log_date` values.

---

## 8. Pregnancy-mode contract

1. **Explicit only.** Mode is entered/exited solely through
   `PUT/PATCH/DELETE /api/v1/reproductive/pregnancy`. Cycle logging, symptom
   logging, health-context selections, and estimates never flip it.
2. **State shape** (§4.2): `is_active` switch + `status` + optional
   `confirmation_date` + jointly-nullable `estimated_due_date/dating_source`
   + verbatim `dating_note`. No gestational-age math, no auto-EDD from LMP,
   no countdownpflicht in V1 — those are Phase 2+ calculations gated on D2.
3. **Legacy coexistence.** `health_contexts.pregnancy_context` remains free
   user context with zero behavioral effect. Product must decide (D5) whether
   selecting `pregnant` there prompts (never forces) enabling the new mode.
4. **Behavioral effects in V1: none specified.** Predictions, summaries, and
   estimates do not branch on pregnancy state until D6 (withholding) is
   decided. This is intentional: shipping the state without the branch lets
   mobile build the mode UX without risking silent prediction changes.
5. **Dating provenance.** Every EDD must carry its `dating_source`
   (`lmp/ultrasound/clinician/unknown`). LMP-derived EDDs cite the LMP date
   in `dating_note`; the server does not recompute EDDs. Clinician/ultrasound
   claims are stored verbatim, never verified in V1.
6. **Reversibility.** `PATCH {is_active:false}` pauses mode (history kept);
   `DELETE` erases it; re-entry is a fresh PUT. No audit tombstone beyond
   standard `updated_at`.
7. **Safety.** Pregnancy endpoints never emit advice, never alter the period
   predictor, never write estimates. EDD is a calendar date, not a medical
   order.

---

## 9. Fertility-observation contract

1. **Grain:** one fact per user/day/type (`lh_test/bbt/cervical_mucus`).
2. **Closed enums, open notes:** type-specific value columns with CHECKs;
   free text only in `note` (≤1000, verbatim, never parsed).
3. **Mucus scale is TBD (D3).** The existing `discharge` volume scale must
   not be reused or reinterpreted as a fertility scale. If clinical prefers a
   different taxonomy than the placeholder, only the enum + CHECK change —
   the table shape does not.
4. **BBT discipline:** `NUMERIC(4,2)` Celsius, range-checked; no Fahrenheit
   storage (convert at the edge); one row per day (first-morning convention
   is UX guidance, not a server rule in V1).
5. **LH discipline:** `positive/negative/invalid` only; no line-intensity
   scores, no photo storage in V1.
6. **Observation ≠ estimate:** observations carry no confidence/method/window;
   they are the evidence estimates cite. Deleting an observation does not
   rewrite past estimate rows (append-only history); it only affects future
   computations.
7. **Sync:** upsert-keyed, last-writer-wins, retry-safe; deletes sync as
   tombstones (client protocol detail, server just hard-deletes + 404s after).

---

## 10. Fertility-estimate contract

1. **Server-computed, client read-only.** No client write path in V1. The
   compute trigger/schedule is Phase 2 (D7); this contract fixes only the
   stored shape and read API.
2. **Nullability is normal:** `insufficient` confidence with null dates is a
   valid estimate (mirrors period `insufficient_data`), surfaced as 200, not
   404/error. Minimum-evidence gates (how many cycles? how many biomarker
   points? over what window?) are product/clinical decisions (D1) — the
   columns already accommodate any gate.
3. **Provenance on every row:** `evidence_source`
   (OBSERVED/ESTIMATED/CLINICALLY_CONFIRMED) + `evidence` JSONB (what went
   in) + `method/method_version` (what computed it) + `calculated_at` +
   `timezone_name` (when/where). An estimate without provenance is a contract
   violation.
4. **Versioning:** estimator identity frozen per method label (à la
   `robust_wma_v1`); any logic change bumps `method_version` and appends new
   rows rather than rewriting history, enabling the same evolution analysis
   the prediction ledger provides for periods.
5. **Isolation from period prediction:** the estimator may **read**
   `calculate_cycle_lengths` output and observation rows; it must never
   write to `cycles`, `prediction_ledger`, or any summary field. Period
   responses keep their exact current shapes; fertility dates appear only in
   the new estimate endpoints.
6. **No silent fallbacks:** no hard-coded 28-day cycle, no assumed luteal
   length, no assumed fertile-window span in the contract — every such number
   is a named, versioned estimator parameter decided in Phase 2, not here.

---

## Amendment A1 — Fertility estimates are compute-on-read (Phase 2 implementation decision)

> Status: **contract amendment, added 2026-09-18 during Phase 2
> implementation.** This section intentionally deviates from the original
> Phase 1 design in §4.4 (`fertility_estimates` table), §5.4 (append-on-
> re-serve), §10 item 4 (append-only history), and §12 (proposed
> `0006_fertility_estimates_v1.sql`). All other contract wording and scope
> are unchanged.

1. Fertility estimates are intentionally **compute-on-read**. No
   `fertility_estimates` persistence table is required for Phase 2, and the
   proposed `0006_fertility_estimates_v1.sql` migration was not built.
2. Each `GET /api/v1/reproductive/estimates` derives the estimate at request
   time from the authoritative sources: completed cycle history (via the
   frozen `calculate_cycle_lengths` / `predict_next_cycle` interfaces),
   in-scope fertility observations (`observation_date <= as_of`), and
   applicable pregnancy-mode suppression state. There is no stale cache:
   every observed-data change is reflected immediately.
3. The remainder of the §10 contract still holds: server-computed and client
   read-only, null dates on insufficient evidence (200, not 404), provenance
   on every response (`evidence_source` + `evidence` metadata +
   `method/method_version` + `calculated_at` + `timezone_name`), frozen
   estimator identity (`fertility_v1`), and strict isolation from period
   prediction (reads history only, never writes it).
4. This is an intentional implementation decision, not an accidental
   omission: deriving on read removes cache-invalidation and history-rewrite
   semantics entirely. A persistent estimate-history table, if ever wanted
   for evolution analysis, requires a separate contract amendment — it must
   not be added speculatively.

---

## 11. Reproductive-aging contract

1. **No diagnosis, no staging, no detection.** There is no `perimenopause`
   column, no menopause-status column, no age-based reclassification of
   cycles in this design — deliberately.
2. **Reuse before store:** age math uses `profiles.birth_year/birth_month`
   (month precision; server never infers from partial data) and variability
   uses existing MAD-based history. Nothing new is persisted for V1.
3. **If persistence becomes necessary:** a single free-text
   `reproductive_aging_context.notes` singleton (≤2000, verbatim, never
   parsed), mirroring `health_notes`. Any structured aging signal beyond that
   requires a new product/clinical review, not a schema shortcut.
4. **Prediction independence holds:** aging context, like health context,
   must never alter period predictions (extend the
   `test_health_context_does_not_alter_predictions` pattern to any future
   aging table).

---

## 12. Migration plan (DESIGNED — DO NOT APPLY)

All migrations additive, idempotent (`IF NOT EXISTS`), no backfill, no data
rewrite, no change to existing columns/semantics/indexes. Each creates its
tables, indexes, and default-deny RLS together. Down-migrations (rollback)
are `DROP TABLE IF EXISTS <new tables>` in reverse order — safe because no
existing data is touched. Fresh-schema file and migrations must be kept
agreeing (existing convention).

- **Proposed `0005_fertility_observations_v1.sql` — REQUIRED FOR FERTILITY V1.**
  Creates `fertility_observations` + value CHECKs + partial unique
  `(user_id, observation_date, observation_type)` + index
  `(user_id, observation_date)` + RLS. Depends on: `profiles` (exists).
  Rollback: drop table. Risk: mucus enum placeholder — changing enum values
  later needs a follow-up `ALTER ... CHECK` migration, not an edit.
- **Proposed `0006_fertility_estimates_v1.sql` — REQUIRED FOR FERTILITY V1
  (read side).** Creates `fertility_estimates` + window CHECKs
  (`start <= end`, span cap) + unique
  `(user_id, estimate_date, method, method_version)` + index
  `(user_id, estimate_date DESC)` + RLS. Depends on: `profiles`; logically on
  `0005` (evidence) but not a DB-level FK dependency. Rollback: drop table.
  The compute job itself is Phase 2 and needs no migration.
- **Proposed `0007_pregnancy_context_v1.sql` — REQUIRED FOR PREGNANCY MODE.**
  Creates `pregnancy_contexts` singleton + joint-null/date-ordering CHECKs +
  RLS. Depends on: `profiles` only. Independent of 0005/0006 — can land
  before or after. Rollback: drop table. No migration of legacy
  `pregnancy_context` values (D5).
- **Aging persistence — REQUIRED FOR REPRODUCTIVE-AGING CONTEXT: nothing.**
  No migration in V1 (reuse birth fields + history). If the deferred notes
  singleton is later approved, it becomes `0008_aging_notes_v1.sql` (new
  table + RLS only).
- **DEFERRED:** clinician-confirm write path columns/endpoints, notification
  scheduler tables, bulk-import helpers, any change to `cycles/daily_logs/
  prediction_ledger` shapes, any `auth.uid()` policy, any `FORCE RLS`, any
  backfill of `profiles.timezone`, any alteration of `0002–0004`.

Pre-apply checklist (human): confirm production is already at `0004`
(including health-table RLS); snapshot/backup; apply in filename order on a
staging clone first; verify fresh-schema file updated in the same change as
each migration (convention).

---

## 13. Test plan (DESIGNED — NOT IMPLEMENTED)

No tests were added in this phase. Before any Phase 2 implementation is
considered complete, the following are required (all on the existing
sqlite in-memory harness + frozen-clock patterns; no live infrastructure):

1. **Schema validation:** model-metadata-matches-migration test per new table
   (columns, CHECKs, unique/indexes, FK `→ profiles CASCADE`), mirroring
   `test_health_model_metadata_matches_migration`.
2. **Authorization / user isolation:** 401 unauthenticated per new route;
   cross-user CRUD → 404; client-supplied `user_id` ignored (per-endpoint
   copy of `test_client_supplied_user_id_is_ignored`); cascade on
   `DELETE /api/v1/profile` covers new tables.
3. **Observation CRUD:** create/get/list-range/patch/delete per type;
   exactly-one-value-column enforcement; BBT range; mucus/LH enum rejection
   (422); future-date bound against frozen user-local today; duplicate
   (user,date,type) upsert determinism; explicit-null note clearing.
4. **Pregnancy context validation:** singleton defaults-when-unset; PUT
   full-replacement clears omitted; PATCH partial preserves unmentioned;
   joint EDD/dating-source rule; date-ordering rules; `is_active:false` vs
   DELETE semantics; no auto-activation from cycle logging (regression).
5. **Estimate contract validation:** read returns `insufficient` with null
   dates (200, not 404); provenance fields present on every row;
   append-only history (re-serve appends); method/version labeling; estimates
   never appear in period/summary responses.
6. **Timezone / date semantics:** frozen-clock ahead/behind-UTC proofs for
   observation/estimate dates; midnight-boundary cases; NULL-timezone UTC
   fallback; DATEs never shifted through UTC (mirroring `test_timezone.py`).
7. **Offline / sync behavior:** PUT-restore idempotency; last-writer-wins;
   delete-then-pull 404; retry-safe double-POST converges.
8. **Migration compatibility:** fresh-schema ↔ migrations agreement check;
   idempotent re-run (`IF NOT EXISTS`); rollback drop leaves existing tables
   untouched; pre-`0005` database still passes the full existing suite.
9. **Existing regression suite:** full `pytest -q` green except the 3 known
   pre-existing duplicate-start failures (which must not change character);
   plus a `health-context-does-not-alter-predictions`-style test proving
   observations/pregnancy/aging state never moves period predictions.

---

## 14. Deferred decisions

- **D1 — Fertility evidence gates:** minimum cycles / biomarker counts /
  window span / confidence thresholds. (No numbers are set in this design.)
- **D2 — Pregnancy dating rules:** joint EDD+source requirement strictness;
  whether LMP auto-suggests an EDD or the server stays a verbatim store.
- **D3 — Cervical-mucus taxonomy:** final closed category set (clinical
  sign-off required; placeholder in §4.1 must not ship as-is without review).
- **D4 — Observation future tolerance:** strict `<= today` vs cycles-style
  `+1 day` display tolerance.
- **D5 — Legacy `pregnancy_context` coexistence:** prompt-to-enable vs
  independent; no automatic migration either way.
- **D6 — Pregnancy data withholding:** whether/how summaries and estimates
  suppress or reframe output while `is_active`; sync/notification knock-ons.
- **D7 — Estimate compute trigger:** on-write vs on-read vs scheduled job;
  caching/staleness policy.
- **D8 — Notifications:** scheduler architecture and which reproductive
  events may trigger (none exists today).
- **D9 — Production migration baseline:** confirm live DB is at `0004`
  (human check; cannot be derived from the repo).

---

## 15. Risks / conflicts requiring human / product decision

1. **Phase 0 docs are not in this checkout** (§3.1) — a human with access to
   the mobile repo must confirm the §3.2 discrepancy list against the real
   Phase 0 text before Phase 2 scoping. Do not proceed on assumed Phase 0
   content.
2. **Pregnancy withholding (D6) is the highest-risk product call.** Hiding
   period predictions or history has clinical-safety and trust implications;
   the wrong default erodes confidence in the protected predictor. Decide
   explicitly; default to no withholding until decided.
3. **Fertility estimates will be read as medical claims.** Confidence labels,
   window spans, and `CLINICALLY_CONFIRMED` handling need clinical review;
   the estimator must ship with the same "educational estimate, not
   clinical" framing the period phase label carries — stronger, given
   conception decisions may rest on it.
4. **Mucus/BBT/LH validation is a medical-UX surface.** Over-strict CHECKs
   block legitimate logging; over-loose enums produce garbage evidence.
   Clinical + UX must co-sign D1/D3/D4.
5. **Legacy `pregnant` selection vs new mode confusion.** Two pregnancy-ish
   fields will coexist; without careful UX copy users will set one and expect
   the other's behavior. Product must own the copy and the prompt logic (D5).
6. **Production baseline uncertainty (D9).** If live Supabase is behind
   `0004`, health endpoints are already broken there and reproductive
   migrations will stack on a bad base. Verify before scheduling anything.
7. **Scope creep into the protected predictor.** Any proposal to "just use
   the fertile window to adjust the period date" (or vice versa) must be
   rejected at review: the period predictor, ledger, and backtest stay
   frozen; fertility reads history but never writes it.
8. **Notification pressure.** Fertility windows create immediate demand for
   alerts; the backend has no scheduler and mobile timing depends on
   timezone-correct dates. Do not promise notification behavior in V1.

---

## Appendix — verification notes for this phase

- Inspected: `app/*` (all routers, models, schemas, services listed in §1),
  `supabase_initial_schema.sql`, `migrations/0002–0004`, `tests/*`
  (incl. full read of `test_health_context.py`), `README.md`, `render.yaml`,
  `pytest.ini`, `requirements` posture via README; `mobile/` confirmed as
  empty uninitialized submodule; `docs/` confirmed absent before this file.
- Protected files read but unchanged: `app/services/cycle_calculator.py`,
  `app/services/prediction_ledger.py`, `app/services/backtest.py`,
  `app/services/timezone.py`, all of `migrations/`, all existing models.
- No source, migration, test, config, database, Render, or Flutter change was
  made. `git status` after this phase must show only `docs/reproductive-backend-contract.md`
  (plus the new `docs/` directory entry) as untracked.
- Test suite was not re-run in this phase (design-only; no code to verify).
  The 162/159/3 snapshot cited is the repo's own documented status
  (`README.md` testing section), not a fresh run.
- Next step is human review of §§3/14/15. **Do not proceed to Phase 2**
  (implementation) until D1–D9 have owners.
