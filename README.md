# MenoMate Core

FastAPI backend for MenoMate: authenticated, user-scoped business logic over Supabase PostgreSQL. It owns cycle math, predictions, daily logs, Care context, therapy policy, device records, health context, and reproductive-health state (fertility observations/estimates, pregnancy mode, reproductive-aging context). The Flutter app (sibling `menomate-mobile` repository, separate checkout) is its only client; browsers never talk to it directly.

> Current state: this documents the production backend on `main` (merged via `0baa5e7`, manually deployed to the Render production service). Phases 2–4 (fertility, pregnancy, reproductive-aging) are **implemented, committed, and deployed** — not pending or experimental.
> Status labels used below: **implemented** (in production paths), **planned** (agreed, not built), **experimental** (evaluated offline, not served).
> Historical design notes live in `docs/reproductive-backend-contract.md` (Phase 1, design-only) and `docs/reproductive-aging-phase4.md` (Phase 4 record); each carries a current-state header. Do not read them as the current contract — Swagger at `/docs` plus `docs/api-contract.md` are current.

## 1. What MenoMate_core is

A single FastAPI service (`app/main.py`) that:

- Verifies Supabase Auth JWTs and scopes every query to the authenticated user.
- Stores menstrual, symptom, health-context, fertility, pregnancy, aging, device, and therapy data in Supabase PostgreSQL.
- Serves the authoritative cycle predictor (`robust_wma_v1`), summaries, and evidence-gated fertility estimates.
- Serves the Care guided-assistance endpoint with deterministic safety behavior and an optional LLM provider.
- Serves a deterministic therapy recommendation policy with a hard temperature ceiling.

This repository contains only the backend. No Flutter code, no firmware, no production secrets.

## 2. What the backend owns

- Authentication verification (`app/core/security.py`, `get_current_user`).
- Profiles and atomic onboarding (`POST /api/v1/onboarding/complete`).
- Cycle records, daily logs/symptoms, summaries, prediction ledger.
- Health context singleton + conditions + medications (user-provided context only; never alters predictions).
- Fertility observations (user-measured facts) + server-computed estimates (compute-on-read, client read-only).
- Explicit pregnancy mode + dating (user-controlled singleton; EDD stored verbatim; estimates suppressed while active).
- Reproductive-aging context (user-recorded notes only; no diagnosis/staging/detection; alters nothing).
- Devices, therapy sessions, deterministic therapy policy.
- Care context builder, deterministic triage, optional Groq LLM with mock fallback.
- Timezone-correct user-local date semantics; DATE vs TIMESTAMPTZ discipline.
- SQL schema (`supabase_initial_schema.sql`) + ordered migrations (`migrations/`).

## 3. What the Flutter client owns

The sibling Flutter repository (`menomate-mobile`, Flutter 3.x, separate checkout — not `mobile/` in this repo; `mobile` here is an empty uninitialized gitlink) owns:

- All UI, navigation, and onboarding screens.
- Offline-first local storage and sync orchestration (PUT-full-replacement restore paths).
- BLE to the ESP32 wearable (planned hardware, not integrated with this backend).
- The Daily Insight deterministic local library (backend does not generate insights).
- Display of server-served predictions/estimates; it performs no prediction or phase math.

## 4. Architecture

```text
Flutter app (menomate-mobile, separate repo)
        |  HTTPS, Supabase JWT Bearer
        v
FastAPI (this repo) ── user-scoped queries only
        +-- Supabase Auth (JWT verify: signature, expiry, issuer, audience)
        +-- Supabase PostgreSQL (DATE dates, TIMESTAMPTZ instants)
        +-- Care (intent context + deterministic triage + optional Groq LLM, mock fallback)
        +-- Deterministic therapy policy (44.0 °C ceiling)

Flutter handset <--BLE--> ESP32 wearable (planned hardware, not integrated)
```

Boundaries that must stay intact:

- FastAPI is the only database access layer. Flutter never touches protected database infrastructure.
- Supabase Auth issues tokens; every protected query is filtered by the authenticated `sub` UUID.
- Care/LLM output is advisory text only. It cannot command hardware or override therapy limits.
- Therapy recommendations are deterministic equations, not model output.
- The mobile app performs no prediction or phase math; the server is authoritative.
- Daily Insight is served from a deterministic local library inside the mobile app. The backend does not generate insights.

## 5. Authentication

Flutter signs in via Supabase Auth → sends the access token as `Authorization: Bearer` → `get_current_user` verifies signature/expiry/issuer/audience → routes filter every query by that UUID.

- Header `alg` allowlist: `HS256`, `RS256`, `ES256`; anything else → 401.
- `HS256` verifies with `SUPABASE_JWT_SECRET` (legacy); missing secret → 401.
- `RS256`/`ES256` verify via cached JWKS from `SUPABASE_URL` (preferred), overridable by `SUPABASE_JWKS_URL`.
- Requires `exp`, `aud == "authenticated"`, `iss == "{SUPABASE_URL}/auth/v1"`, UUID `sub`.
- Every protected route depends on it; no route accepts a client-provided `user_id` for ownership (extra keys ignored).
- Cross-user id access → 404 (never 403 with existence leak); unauthenticated → 401.
- Secrets live in server `.env` / Render dashboard only — never in the mobile repo, logs, or docs.

## 6. Current implemented capabilities

**Implemented:**

- Supabase JWT verification (HS256 secret or JWKS asymmetric; expiry, issuer, audience `authenticated`, UUID `sub`).
- Profiles + atomic onboarding (profile and first period in one transaction, idempotent re-onboarding, per-user asyncio lock).
- Cycle tracking: `period_start` / nullable `period_end`, overlap + duration + future-date validation, retrospective "ended today", reopen semantics, duplicate-start deterministic upsert (201, same row).
- Daily logs/symptoms: full-day upsert keyed on `(user, log_date)`, PATCH with explicit-null clearing, controlled symptom taxonomy.
- Daily-log discharge descriptors are qualitative user self-report descriptors only — NOT an amount scale, NOT a diagnosis, NOT the fertility/mucus taxonomy.
- Summaries: current-cycle status (day, phase, bleeding, prediction, confidence, status) and history (lengths, variability, symptom frequencies).
- Prediction: robust recency-weighted predictor over completed intervals (MAD-trimmed, clamped 20–45d), explicit `insufficient_data` instead of guesses, `prediction_status` (`upcoming` / `today` / `awaiting_next_start`), confidence labels.
- Prediction ledger: observational per-serving snapshots, resolved by later starts.
- Health context: singleton + conditions + medications (9 routes); stored verbatim, never alters predictions.
- Fertility: observations CRUD + server-computed evidence-gated estimates (compute-on-read; `AVAILABLE` / `LOW_CONFIDENCE` / `INSUFFICIENT_DATA` / `SUPPRESSED`).
- Pregnancy: explicit singleton mode + dating (GET/PUT/PATCH/DELETE); EDD stored verbatim with provenance precedence; estimates `SUPPRESSED` while active; history retained.
- Reproductive-aging: singleton notes context (GET/PUT); verbatim, no staging/diagnosis/detection, alters nothing.
- Care: intent-routed context builder + deterministic red-flag triage + semantic actions, Groq LLM optional with mock fallback.
- Therapy: deterministic recommendation policy (44.0 °C ceiling), session telemetry logging, device ownership checks, single-use feedback.
- Devices: register / list / unpair BLE hardware identifiers.
- User-local calendar semantics via stored IANA timezone.

**Planned / not built:** local-notification scheduling (needs product decision), deeper daily-log personalization, hardware integration and validation, multi-year variability modeling.

**Experimental (evaluated offline, NOT served):** hierarchical/Bayesian and skip-aware candidate predictors were backtested against the production predictor; result was insufficient evidence to change anything, so production still serves the robust WMA only. Experiment code lives outside serving paths.

## 7. API domains

By domain (request/response shapes in `app/schemas/`; exact machine-readable contract in Swagger at `/docs`; practical reference in `docs/api-contract.md`):

- Auth: `GET /api/v1/auth/me`
- Profile: `GET` / `PATCH` / `DELETE /api/v1/profile` (IANA `timezone`, optional paired `birth_year` + `birth_month`)
- Onboarding: `POST /api/v1/onboarding/complete` (atomic profile + first period; `name` required non-blank)
- Cycles: `GET /api/v1/cycles`, `POST /api/v1/cycles` (duplicate-start upserts 201), `GET /api/v1/cycles/current`, `POST /api/v1/cycles/current/end`, `PATCH /api/v1/cycles/{cycle_id}`
- Logs: `GET /api/v1/symptoms` (public catalogue), `GET /api/v1/logs`, `POST /api/v1/logs` (full-day upsert), `GET /api/v1/logs/{log_date}`, `PATCH /api/v1/logs/{log_id}`
- Summaries: `GET /api/v1/summary/current`, `GET /api/v1/summary/history`
- Health context: `GET` / `PUT` / `PATCH /api/v1/health-context`, `GET` / `POST /api/v1/health-context/conditions`, `PATCH` / `DELETE /api/v1/health-context/conditions/{condition_id}`, `GET` / `POST /api/v1/health-context/medications`, `PATCH` / `DELETE /api/v1/health-context/medications/{medication_id}`
- Reproductive: `POST` / `GET /api/v1/reproductive/observations`, `PATCH` / `DELETE /api/v1/reproductive/observations/{observation_id}`, `GET /api/v1/reproductive/estimates` (compute-on-read, client read-only), `GET` / `PUT` / `PATCH` / `DELETE /api/v1/reproductive/pregnancy`, `GET` / `PUT /api/v1/reproductive/aging-context`
- Devices: `GET` / `POST /api/v1/devices`, `DELETE /api/v1/devices/{device_id}`
- Therapy: `POST /api/v1/therapy/recommend`, `GET` / `POST /api/v1/therapy/sessions`, `PATCH /api/v1/therapy/sessions/{session_id}`
- Care: `POST /api/v1/care/interactions` (only Care endpoint; there is no `/api/v1/care/interact` alias)
- Root: `GET /`, `GET /health` (no auth)

Actual surface: 29 API v1 paths / 47 API v1 operations (+ `/`, `/health`). `tests/test_api_contract.py` pins the main contract (its hardcoded 28-path/46-op count predates `POST /cycles/current/end`; the live OpenAPI above is authoritative).

## 8. Database model

Supabase PostgreSQL. Access model: FastAPI opens one async engine over a single privileged role (which bypasses RLS); **row-level security is enabled on all app tables as default-deny defense-in-depth with no permissive policies** — primary isolation comes from every query filtering on the authenticated user id, with `ON DELETE CASCADE` from `profiles`. Do not add `auth.uid()` policies or `FORCE ROW LEVEL SECURITY` without changing the connection architecture (see `supabase_initial_schema.sql` §11).

Tables (13): `profiles` (incl. IANA `timezone`, optional paired `birth_year`/`birth_month`), `cycles` (`DATE` ranges, `UNIQUE(user_id, period_start)`), `daily_logs` (`UNIQUE(user_id, log_date)`, nullable `pain`, TEXT multi-select `mood`) + `symptom_logs`, `devices`, `therapy_sessions` (`TIMESTAMPTZ`), `prediction_ledger`, `health_contexts` + `health_conditions` + `medications`, `fertility_observations` (Phase 2 facts; estimates computed on read, not stored), `pregnancy_contexts` (Phase 3 singleton), `reproductive_aging_contexts` (Phase 4 notes singleton).

Fresh DBs use `supabase_initial_schema.sql`; live DBs apply `migrations/` in filename order (`0002`–`0009`; there is no `0001` file — the implied `0001` is the initial schema). Tests run on in-memory sqlite via `Base.metadata.create_all`, never touching real infrastructure. Full reference: `docs/database-and-migrations.md`.

## 9. Prediction system

Authoritative predictor is `robust_wma_v1` in `app/services/cycle_calculator.py` — the only served predictor; there is no client-side duplicate.

High level: recent completed start-to-start intervals → median/MAD outlier trim → recency-weighted mean → clamp 20–45 days. Only observed starts (`period_start <= user-local today`) train; future display-only dates never do. Zero-history fallback uses `usual_cycle_days` (`source="usual_cycle"`, `confidence="low"`), else `insufficient_data` with null prediction — no silent 28-day fallback. Confidence (`low`/`moderate`/`high`) reflects history depth and MAD spread. `prediction_status` and `days_until_next_period` are computed against the **user-local today**, never negative (clamped to `awaiting_next_start`). Phase (`menstrual`/`follicular`/`ovulation`/`luteal`/`unknown`) is an educational estimate from served values; the `ovulation` phase label is not a fertile-window estimate.

Prediction ledger (`prediction_ledger`): observational per-serving snapshots (method, lengths, confidence, source, basis, MAD); resolved by later starts with signed `error_days`. Never influences responses; reads only in analysis.

## 10. Fertility/reproductive-health system

Load-bearing distinction:

- **Observations** (`fertility_observations`): user-recorded facts — `lh_test` (`positive`/`negative`/`invalid`), `bbt` (35.00–42.00 °C, NUMERIC(4,2)), `cervical_mucus` (`dry`/`sticky`/`creamy`/`watery`/`egg_white`). Grain: one row per (user, date, type); re-POST upserts (200 on overwrite, 201 on create). `observation_date` is a user-local DATE, never future. An LH `positive` records a test outcome only — never proof of ovulation.
- **Estimates** (`GET /api/v1/reproductive/estimates`): server-computed, compute-on-read, client read-only. No `fertility_estimates` table (intentional Amendment A1 in the contract doc). Statuses: `AVAILABLE` (history-anchored `moderate`/`high` + same-cycle LH-positive → dated window), `LOW_CONFIDENCE` / `INSUFFICIENT_DATA` (null dates, HTTP 200), `SUPPRESSED` (pregnancy mode active → null dates). Estimator `fertility_v1` 1.0.0; luteal 14d and window −5/+1d are named product parameters, not clinical facts. Never contraception, never diagnosis, never proof of fertility/infertility. Estimated ovulation/fertility language must never be presented as clinically confirmed.

## 11. Pregnancy mode

Explicit user-controlled singleton (`pregnancy_contexts`), separate from the legacy `health_contexts.pregnancy_context` free selection (which keeps zero behavioral effect and is never reinterpreted).

- Selecting pregnancy as an onboarding/health-context interest does NOT activate pregnancy mode; only `PUT`/`PATCH /api/v1/reproductive/pregnancy` does. Cycle logging never flips it.
- Dating: `dating_source` (`lmp`/`ultrasound`/`clinician`/`unknown`), verbatim `estimated_due_date`, optional `lmp_date` (only with `lmp` source), `confirmation_date`, `dating_note`. The server never auto-computes an EDD. Provenance precedence clinician > ultrasound > lmp > unknown; a lower-provenance differing EDD over a higher-provenance stored EDD → 409.
- Derived read-only fields: `edd_status`, `edd_label`, `dating_confidence` (`CLINICALLY_CONFIRMED` only for clinician source), gestational age (LMP subtraction preferred, else 280-day EDD reference), `days_until_due`, `as_of_date`, `timezone_name`.
- While `is_active`: fertility estimates return `SUPPRESSED` (null dates). Period predictions, summaries, cycles, logs, and history are unaffected and remain available. `PATCH {is_active:false}` pauses (history retained); `DELETE` erases.
- Responses carry the pregnancy safety note; EDDs are educational estimates, not clinical confirmation.

## 12. Reproductive-aging context

Explicit user-recorded singleton (`reproductive_aging_contexts`): `{ notes? ≤2000 }` verbatim via `GET`/`PUT /api/v1/reproductive/aging-context` (omitted/null clears). Provenance is a fixed `user_declared` label.

- Notes/context only. No diagnosis, no staging, no detection, no state vocabulary, no dates.
- No automatic 12-month inference; no perimenopause/menopause/postmenopause values anywhere.
- Does not alter period predictions, fertility estimates, pregnancy mode, health context, or history. Fully independent singleton (all active/inactive combinations with pregnancy mode verified).
- Record: `docs/reproductive-aging-phase4.md` (carries a current-state header; original verification text is historical).

## 13. Care/AI boundaries

`POST /api/v1/care/interactions` only (no `/interact` alias):

Flutter → backend Care endpoint → context builder (`app/services/ai_context.py`: cycle/symptom/therapy context) → deterministic safety/triage (`app/services/care.py`, `care_topics.py`: out-of-scope, diagnosis/medication frames, red-flag `urgent`/`advisory` tiers, semantic actions) → optional LLM provider (`app/services/ai_provider.py`: Groq, default `openai/gpt-oss-120b`; unset key → deterministic mock) → composer guards (`care_composer.py`: explained-text/followup validation, therapy-profile cross-check) → advisory text (`response_text`, `tier`, `actions`, `disclaimer`, `therapy_profile`).

- The model never chooses UI actions; actions are deterministic semantic ids (`open_logger`, `view_therapy`, `seek_emergency_care`, …).
- `recent_turns` are transient session context, never persisted.
- Care/LLM output must not control hardware: forbidden hardware fields are blocked; only `GENTLE`/`MODERATE`/`STRONG` profile names (or null) may pass; the backend remains authoritative for therapy configuration.
- Never describe Care as diagnosing users; diagnosis/medication requests get safe-completion frames plus disclaimer.

## 14. Safety boundaries

Intended hierarchy (implemented vs planned stated explicitly):

1. API software ceiling — **implemented**: deterministic policy caps recommendations at 44.0 °C (`app/services/therapy_policy.py`, `MAX_POLICY_TEMP_CELSIUS`).
2. Deterministic therapy policy — **implemented** (pain-banded temp/vibration/duration equations + sensitivity 0.80–1.20; no model output).
3. ESP32 firmware bounds + temperature sensing + heartbeat loss cutoff — **planned**: no firmware in this repo, nothing validated.
4. Independent hardware thermal protection (45.0 °C fail-safe) — **planned**, not physically validated.
5. Care/LLM → hardware air gap — **implemented by construction**: Care returns text; no code path from LLM output to actuation.

Never present hardware safety as validated: there is no hardware test evidence in this repository.

## 15. Timezone/date semantics

Load-bearing for all date-dependent work:

- **DATE fields are user calendar dates**, never shifted: `period_start`, `period_end`, `log_date`, `predicted_next_period`, `observation_date`, `estimated_due_date`, `lmp_date`, `confirmation_date`, ledger dates. Stored as `DATE`, compared as dates.
- **Instants stay UTC**: `created_at`, `updated_at`, `last_connected_at`, therapy `started_at`/`ended_at`, `recorded_at`, `calculated_at`. Stored as `TIMESTAMPTZ`.
- **User-local "today"** = now → `profiles.timezone` (IANA, e.g. `Asia/Kolkata`) → local date (`app/services/timezone.py`). All summary/status/countdown/default/validation paths use it. NULL timezone (legacy users) explicitly falls back to the UTC date until the device syncs; never hard-code a zone.
- Do not pass DATE-only values through UTC conversion anywhere.

## 16. Local development

Prerequisites: Python 3.11+ (developed on 3.12; `tzdata` covers Windows zoneinfo), a Supabase project, PowerShell/terminal. Full workflow: `docs/backend-development.md`.

```bash
python -m venv .venv
.venv\Scripts\activate          # (source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env          # (cp .env.example .env) then fill Supabase values
```

Database: execute `supabase_initial_schema.sql` in the Supabase SQL editor for a fresh project. For an existing database, apply `migrations/` in filename order. Keep both agreeing when models change.

```bash
pytest -q
```

Docs + health: `http://localhost:8000/docs` (Swagger UI), `.../redoc`, `.../health`. Mobile-on-USB: `adb reverse tcp:8000 tcp:8000`.

## 17. Testing

```bash
pytest -q
# (On locked-down Windows checkouts where .pytest_cache is read-only, add -p no:cacheprovider)
```

Current validation (full run on the production commit): **373 collected, 373 passed, 0 failed, 0 skipped/errors.**

Organization: `test_auth.py` (JWT matrix), `test_api_contract.py` (route/auth/enum/404/409 contract), `test_cycles/logs/onboarding/summary` (routes + validation), `test_cycle_calculator.py` (math vectors, explicit `today`), `test_backtest.py` (walk-forward equivalence), `test_prediction_ledger.py`, `test_timezone.py` (frozen-clock ahead/behind UTC, midnight boundaries, fallback), Care suites (`test_care*.py`: routing, composer, topics, therapy, session, soft-risk, actions, mock), `test_therapy_and_devices.py`, `test_health_context.py`, `test_fertility_phase2.py` (observations + evidence-gated estimates), `test_pregnancy_phase3.py` (explicit mode + dating + suppression), `test_reproductive_aging_phase4.py` (notes singleton + independence proofs), `test_production_hardening.py` (auth/IDOR/validation/config).

Historical note: an earlier run had 3 failures from stale duplicate-period expectations (implementation intentionally upserts same-start 201); the tests were corrected without changing the implementation. New date logic must add frozen-clock tests, never depend on machine timezone.

## 18. Render deployment

Production is **manually deployed** to the Render web service (no auto-deploy). Full reference: `docs/deployment.md`.

Startup (Render runs this; the app never assumes port 8000):

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

- Binds `0.0.0.0` and respects Render's `$PORT`.
- Health check path: `/health` (no auth, returns `{"status": "healthy", ...}`).
- `render.yaml` is a manual-launch blueprint with `autoDeploy: false`. Set secret env vars in the Render dashboard (`DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_JWT_SECRET` for legacy HS256 or `SUPABASE_JWKS_URL` override, `GROQ_API_KEY`). Non-secret defaults: `ALLOWED_ORIGINS=""`, `AUTO_CREATE_TABLES="false"`, `GROQ_MODEL=openai/gpt-oss-120b`.
- Database: Supabase PostgreSQL. Fresh: execute `supabase_initial_schema.sql`; existing: apply `migrations/` in order. Never enable `AUTO_CREATE_TABLES` in production.
- Verify after any manual deploy: `/health`, `/docs`, authenticated smoke calls; migrations are a human responsibility, never automatic.

## 19. Environment variables

Names only (see `.env.example` for placeholders). All server-only; never commit real values.

| Variable | Required | Notes |
|---|---|---|
| `PROJECT_NAME` | No | Service label |
| `API_V1_STR` | No | Route prefix, default `/api/v1` |
| `DATABASE_URL` | Yes | `postgresql+asyncpg://…`; tests override with in-memory sqlite |
| `SUPABASE_URL` | Yes | Also feeds JWKS discovery + issuer check; rejects placeholders at startup |
| `SUPABASE_JWT_SECRET` | Optional | Only for legacy HS256; omit with asymmetric signing |
| `SUPABASE_JWKS_URL` | No | Override JWKS endpoint; derived from `SUPABASE_URL` by default |
| `ALLOWED_ORIGINS` | No | CORS list or `*` (default `*` for local dev). A wildcard origin never enables credentials; production uses `""` (Flutter needs no browser CORS) |
| `AUTO_CREATE_TABLES` | No | DDL on startup; default `false`. Production must keep `false` and use the SQL files instead |
| `GROQ_API_KEY` | No | Care LLM; unset → deterministic mock provider |
| `GROQ_MODEL` | No | Default `openai/gpt-oss-120b` |

## 20. Contribution/development rules

- DO NOT work directly on `main` for normal feature development. Workflow: feature branch → implementation → tests → review → merge.
- No secrets in code, logs, docs, or the mobile repo.
- No LLM output reaches hardware paths; therapy stays deterministic equations.
- No second predictor: mobile displays server values; `calculate_cycle_lengths(today=…)` always takes an explicit user-local date in production paths.
- DATE stays DATE: never convert calendar fields through UTC; timestamps stay `TIMESTAMPTZ`.
- Every new query filters by authenticated user; every new column updates model + schema + migration + tests.
- Keep `supabase_initial_schema.sql` and `migrations/` agreeing.
- How to add endpoints/fields/migrations/tests: see `docs/backend-development.md`.

## 21. Current limitations / future work

- Hardware integration and on-device validation (planned, no firmware here).
- Push-notification scheduling (planned; timezone work in this repo unblocks it).
- Deeper daily-log personalization (planned).
- More resolved predictions needed before any model comparison (ledger collects them; bar is thousands).
- Render deployment is manual (`autoDeploy: false`); no CI auto-deploy from this repo.

## Repository structure

Actual tree on `main` (do not invent files):

```text
MenoMate_core/
├── app/
│   ├── api/v1/            # auth, profile, onboarding, cycles, logs,
│   │                      # summary, devices, therapy, care,
│   │                      # health_context, reproductive
│   ├── core/              # config.py (env), security.py (JWT verification)
│   ├── db/                # base.py (Base), session.py (async engine)
│   ├── models/            # profile, cycle, daily_log, symptom_log, device,
│   │                      # therapy_session, prediction_ledger, health_context,
│   │                      # fertility_observation, pregnancy_context,
│   │                      # reproductive_aging
│   ├── schemas/           # care, cycle, daily_log, device, fertility,
│   │                      # health_context, onboarding, pregnancy, profile,
│   │                      # reproductive_aging, summary, therapy
│   ├── services/          # cycle_calculator, summary, timezone, profile,
│   │                      # prediction_ledger, backtest, care, care_composer,
│   │                      # care_topics, ai_context, ai_provider, therapy_policy,
│   │                      # fertility_estimator, pregnancy, pregnancy_dating,
│   │                      # reproductive_aging
│   └── main.py            # App entrypoint, router wiring, / and /health
├── tests/                 # pytest suite (sqlite in-memory, deterministic)
├── migrations/            # 0002_add_profile_timezone … 0009_mood_text_multiselect
├── supabase_initial_schema.sql  # Canonical DDL for a FRESH database
├── docs/                  # api-contract, database-and-migrations,
│                          # backend-development, deployment,
│                          # reproductive-backend-contract (Phase 1 design, historical),
│                          # reproductive-aging-phase4 (Phase 4 record, historical header)
├── scratch/               # Throwaway manual probes, not production code
├── requirements.txt
├── pytest.ini
├── render.yaml            # Manual-launch blueprint (autoDeploy: false)
└── .env.example           # Variable NAMES with placeholder values only
```

`mobile` is an empty uninitialized gitlink, not a checked-out submodule; the real Flutter client is the sibling `menomate-mobile` repository.

## License

MIT — see `LICENSE`. Third-party inspirations (Mensinator, Metra, YIMA) are attributed in `THIRD_PARTY_NOTICES.md`.
