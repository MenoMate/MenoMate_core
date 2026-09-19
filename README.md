# MenoMate Core

FastAPI backend for MenoMate: authenticated, user-scoped business logic over Supabase PostgreSQL. It owns cycle math, predictions, daily logs, Care context, therapy policy, and device records. The Flutter app ([menomate-mobile](../menomate-mobile/README.md)) is its only client; browsers never talk to it directly.

> Status labels used below: **implemented** (in production paths), **planned** (agreed, not built), **experimental** (evaluated offline, not served).

## Overview

MenoMate is a menstrual wellness system: a Flutter app, this backend, Supabase (PostgreSQL + Auth), and a planned ESP32 wearable. This repository contains only the backend.

## Architecture

```text
Flutter app (menomate-mobile)
        |  HTTPS, Supabase JWT Bearer
        v
FastAPI (this repo) ── user-scoped queries only
        +-- Supabase Auth (JWT verify: signature, expiry, issuer, audience)
        +-- Supabase PostgreSQL (DATE dates, TIMESTAMPTZ instants)
        +-- Care (intent context + optional Groq LLM, mock fallback)
        +-- Deterministic therapy policy (44.0 °C ceiling)

Flutter handset <--BLE--> ESP32 wearable (planned hardware, not integrated)
```

Boundaries that must stay intact:

- FastAPI is the only database access layer. Flutter never touches protected database infrastructure.
- Supabase Auth issues tokens; every protected query is filtered by the authenticated `sub` UUID.
- Care/LLM output is advisory text only. It cannot command hardware or override therapy limits.
- Therapy recommendations are deterministic equations, not model output.
- The mobile app performs no prediction or phase math; the server is authoritative.
- Daily Insight is served from a deterministic local library inside the mobile app (optional future AI enrichment only). The backend does not generate insights.

## Repository structure

```text
MenoMate_core/
├── app/
│   ├── api/v1/            # Route handlers: auth, profile, onboarding,
│   │                      # cycles, logs, summary, devices, therapy, care
│   ├── core/              # config.py (env), security.py (JWT verification)
│   ├── db/                # base.py (Base), session.py (async engine)
│   ├── models/            # SQLAlchemy ORM tables (source of truth for columns)
│   ├── schemas/           # Pydantic request/response contracts + validators
│   ├── services/          # cycle_calculator, summary, timezone, profile,
│   │                      # prediction_ledger, backtest, care, ai_context,
│   │                      # ai_provider, therapy_policy
│   └── main.py            # App entrypoint, router wiring, / and /health
├── tests/                 # pytest suite (sqlite in-memory, deterministic)
├── migrations/            # Ordered SQL migrations for existing databases
├── supabase_initial_schema.sql  # Canonical DDL for a FRESH database
├── scratch/               # Throwaway manual probes, not production code
├── requirements.txt
├── pytest.ini
└── .env.example           # Variable NAMES with placeholder values only
```

## Current capabilities

**Implemented:**

- Supabase JWT verification (HS256 secret or JWKS asymmetric; expiry, issuer, audience `authenticated`, UUID `sub`).
- Profiles + atomic onboarding (profile and first period in one transaction, idempotent re-onboarding).
- Cycle tracking: `period_start` / nullable `period_end`, overlap + duration + future-date validation, retrospective "ended today", reopen semantics.
- Daily logs/symptoms: full-day upsert keyed on `(user, log_date)`, PATCH with explicit-null clearing, controlled symptom taxonomy.
- Daily-log discharge descriptors (`sticky`, `creamy`, `watery`, `slippery`) are qualitative user self-report descriptors. They describe the user's selected observation only. They are NOT an amount scale, NOT themselves a diagnosis, NOT the fertility/mucus taxonomy, and must not be interpreted as clinically validated physiological conclusions.
- Summaries: current-cycle status (day, phase, bleeding, prediction, confidence, status) and history (lengths, variability, symptom frequencies).
- Prediction: robust recency-weighted predictor over completed intervals (MAD-trimmed, clamped 20–45d), explicit `insufficient_data` instead of guesses, `prediction_status` (`upcoming` / `today` / `awaiting_next_start`), confidence labels.
- Prediction ledger: observational per-serving snapshots, resolved by later starts (see below).
- Care: intent-routed context builder + deterministic red-flag triage, Groq LLM optional with mock fallback.
- Therapy: deterministic recommendation policy (44.0 °C ceiling), session telemetry logging, device ownership checks, single-use feedback.
- Devices: register / list / unpair BLE hardware identifiers.
- User-local calendar semantics via stored IANA timezone (see below).

**Planned / not built:** local-notification scheduling (blocked on nothing — needs product decision), deeper daily-log personalization, hardware integration and validation, multi-year variability modeling. Managed cloud deployment has a minimal Render blueprint (`render.yaml`, manual launch only — nothing is auto-deployed from this repo).

**Experimental (evaluated offline, NOT served):** hierarchical/Bayesian and skip-aware candidate predictors were backtested against the production predictor; result was insufficient evidence to change anything, so production still serves the robust WMA only. Experiment code lives outside serving paths.

## Prediction system

High level, no trivia: recent completed start-to-start intervals → median/MAD outlier trim → recency-weighted mean → clamp 20–45 days. Only observed starts (`period_start <= today`) train; future display-only dates never do. Confidence (`low`/`moderate`/`high`) reflects usable history depth and MAD spread. `prediction_status` and `days_until_next_period` are computed against the **user-local today** (below), never negative (clamped to `awaiting_next_start`). Phase (`menstrual`/`follicular`/`ovulation`/`luteal`/`unknown`) is an educational estimate from served values.

## Prediction ledger

Evaluation infrastructure, not a feature: each served model prediction snapshots method, lengths, confidence, source, and baseline into `prediction_ledger`; when the actual next start is logged, the open entry resolves with signed `error_days`. It never influences responses. Reads only happen in analysis, never in request paths.

## Timezone/date semantics

This is load-bearing for all future date-dependent work:

- **DATE fields are user calendar dates**, never shifted: `period_start`, `period_end`, `log_date`, `predicted_next_period`, ledger dates. Stored as `DATE`, compared as dates.
- **Instants stay UTC**: `created_at`, `updated_at`, `last_connected_at`, therapy `started_at`/`ended_at`. Stored as `TIMESTAMPTZ`.
- **User-local "today"** = now → `profiles.timezone` (IANA, e.g. `Asia/Kolkata`) → local date (`app/services/timezone.py`). All summary/status/countdown/default/validation paths use it. NULL timezone (legacy users) explicitly falls back to the UTC date until the device syncs; never hard-code a zone.
- Do not pass DATE-only values through UTC conversion anywhere.

## Authentication

Flutter signs in via Supabase Auth → sends the access token as `Authorization: Bearer` → `get_current_user` verifies signature/expiry/issuer/audience → routes filter every query by that UUID. Secret handling: `SUPABASE_JWT_SECRET` (HS256 legacy) or JWKS discovery from `SUPABASE_URL` (asymmetric, preferred). Secrets live in server `.env` only — never in the mobile repo, logs, or docs.

## Environment variables

Names only (see `.env.example` for placeholders). All server-only; never commit real values.

| Variable | Required | Notes |
|---|---|---|
| `PROJECT_NAME` | No | Service label |
| `API_V1_STR` | No | Route prefix, default `/api/v1` |
| `DATABASE_URL` | Yes | `postgresql+asyncpg://…`; tests override with in-memory sqlite |
| `SUPABASE_URL` | Yes | Also feeds JWKS discovery + issuer check; rejects placeholders at startup |
| `SUPABASE_JWT_SECRET` | Optional | Only for legacy HS256; omit with asymmetric signing |
| `SUPABASE_JWKS_URL` | No | Override JWKS endpoint; derived from `SUPABASE_URL` by default |
| `ALLOWED_ORIGINS` | No | CORS list or `*` (default `*` for local dev). A wildcard origin never enables credentials; production should use an explicit list (or empty — the Flutter app needs no browser CORS) |
| `AUTO_CREATE_TABLES` | No | DDL on startup; default `false`. Production must keep `false` and use the SQL files instead |
| `GROQ_API_KEY` | No | Care LLM; unset → deterministic mock provider |
| `GROQ_MODEL` | No | Default `openai/gpt-oss-120b` |

## Running locally

Verified commands (Windows PowerShell shown; macOS/Linux equivalents in parentheses):

```bash
python -m venv .venv
.venv\Scripts\activate          # (source .venv/bin/activate)
pip install -r requirements.txt # Python 3.11+, developed on 3.12; adds tzdata for zoneinfo on Windows
copy .env.example .env          # (cp .env.example .env) then fill Supabase values
```

Database: execute `supabase_initial_schema.sql` in the Supabase SQL editor for a fresh project. For an existing database, apply `migrations/` in filename order (e.g. `0002_add_profile_timezone.sql`). Keep both files agreeing when models change.

```bash
pytest -q
```

Docs + health: `http://localhost:8000/docs` (Swagger UI), `.../redoc`, `.../health`. Mobile-on-USB: `adb reverse tcp:8000 tcp:8000`.

## Render deployment (manual)

Production startup (Render runs this; the app itself never assumes port 8000):

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

- Binds `0.0.0.0` and respects Render's `$PORT`.
- Health check path: `/health` (no authentication, returns `{"status": "healthy", ...}`).
- `render.yaml` holds this configuration as a blueprint with `autoDeploy: false`. Launch it manually in the Render dashboard and set the secret env vars there (`DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_JWT_SECRET` for legacy HS256 or `SUPABASE_JWKS_URL` override, `GROQ_API_KEY`). Non-secret defaults shipped in the blueprint: `ALLOWED_ORIGINS=""` (restrictive — mobile needs no browser CORS), `AUTO_CREATE_TABLES="false"`, `GROQ_MODEL=openai/gpt-oss-120b`.
- Database: Supabase PostgreSQL. For a fresh project execute `supabase_initial_schema.sql` in the Supabase SQL editor; for an existing database apply `migrations/` in filename order. Never enable `AUTO_CREATE_TABLES` in production.

## API

By domain (request/response shapes live in `app/schemas/`; exact contracts in Swagger at `/docs`):

- Auth: `GET /api/v1/auth/me`
- Profile: `GET` / `PATCH` / `DELETE /api/v1/profile` (PATCH accepts IANA `timezone`, optional `birth_year` + `birth_month` month/year precision)
- Health context (V1, user-provided context only — never alters predictions): `GET` / `PUT` / `PATCH /api/v1/health-context` (contraception, pregnancy/fertility selections, free-text notes), `GET` / `POST /api/v1/health-context/conditions`, `PATCH` / `DELETE /api/v1/health-context/conditions/{id}`, `GET` / `POST /api/v1/health-context/medications`, `PATCH` / `DELETE /api/v1/health-context/medications/{id}`
- Reproductive Phase 2 (fertility observations + estimated fertility, never contraception/diagnosis): `POST` / `GET /api/v1/reproductive/observations`, `PATCH` / `DELETE /api/v1/reproductive/observations/{id}`, `GET /api/v1/reproductive/estimates` (server-computed, client read-only)
- Reproductive Phase 3 (explicit user-controlled pregnancy mode + dating, never inferred, EDD stored verbatim): `GET` / `PUT` / `PATCH` / `DELETE /api/v1/reproductive/pregnancy` (singleton; active mode returns SUPPRESSED estimates only — period predictions, summaries, cycles, and logs are unaffected)
- Reproductive Phase 4 (explicit user-controlled reproductive-aging context only — verbatim notes, never a diagnosis/staging/detection, never alters predictions, estimates, or pregnancy mode): `GET` / `PUT /api/v1/reproductive/aging-context` (see `docs/reproductive-aging-phase4.md`)
- Onboarding: `POST /api/v1/onboarding/complete` (atomic profile + first period)
- Cycles: `GET /api/v1/cycles/current`, `POST /api/v1/cycles/current/end`, `GET` / `POST /api/v1/cycles`, `PATCH /api/v1/cycles/{id}`
- Logs: `GET /api/v1/symptoms` (public), `GET /api/v1/logs/{date}`, `GET /api/v1/logs`, `POST /api/v1/logs` (upsert), `PATCH /api/v1/logs/{id}`
- Summaries: `GET /api/v1/summary/current`, `GET /api/v1/summary/history`
- Devices: `GET` / `POST /api/v1/devices`, `DELETE /api/v1/devices/{id}`
- Therapy: `POST /api/v1/therapy/recommend`, `GET` / `POST /api/v1/therapy/sessions`, `PATCH /api/v1/therapy/sessions/{id}`
- Care: `POST /api/v1/care/interactions`
- Root: `GET /`, `GET /health`

## Database

Supabase PostgreSQL. Access model: FastAPI opens one async engine over a single privileged role (which bypasses RLS); **row-level security is enabled on all app tables as default-deny defense-in-depth with no permissive policies** — primary isolation comes from every query filtering on the authenticated user id, with `ON DELETE CASCADE` from `profiles`. Do not add `auth.uid()` policies or `FORCE ROW LEVEL SECURITY` without changing the connection architecture (see `supabase_initial_schema.sql` §9). Tables: `profiles` (incl. IANA `timezone`, optional `birth_year`/`birth_month`), `cycles` (`DATE` ranges), `daily_logs` + `symptom_logs`, `devices`, `therapy_sessions` (`TIMESTAMPTZ`), `prediction_ledger`, `health_contexts` (singleton contraception/pregnancy/free-text context), `health_conditions`, `medications`, `fertility_observations` (Phase 2 user-measured LH/BBT/mucus facts; estimates are computed on read, not stored), `pregnancy_contexts` (Phase 3 explicit pregnancy-mode singleton), `reproductive_aging_contexts` (Phase 4 user-recorded context notes only; no staging, no diagnosis, no dates). Fresh DBs use `supabase_initial_schema.sql`; live DBs use `migrations/`. Tests run on in-memory sqlite via `Base.metadata.create_all`, so they never touch real infrastructure.

## Safety architecture

Intended hierarchy (implemented vs planned stated explicitly):

1. API software ceiling — **implemented**: deterministic policy caps recommendations at 44.0 °C.
2. Deterministic therapy policy — **implemented** (`therapy_policy.py`, no model output).
3. ESP32 firmware bounds + temperature sensing + heartbeat loss cutoff — **planned**: no firmware in this repo, nothing validated.
4. Independent hardware thermal protection (45.0 °C fail-safe) — **planned**, not physically validated.
5. Care/LLM → hardware air gap — **implemented by construction**: Care returns text; no code path from LLM output to actuation.

Never present hardware safety as validated: there is no hardware test evidence in this repository.

## Testing

```bash
pytest -q
```

Suite status (final validation, verified by full run on this worktree): 373 collected, 373 passed, 0 failed, 0 skipped/errors. The previous three failures were stale expectations around the intentional deterministic duplicate-period 201 upsert behavior (`test_api_contract_409…`, `test_cycle_overlapping…`, `test_cycle_duplicate…`); the tests were corrected without changing the implementation. Organization: `test_auth.py` (JWT matrix), `test_api_contract.py`, `test_cycles/logs/onboarding/summary` (routes + validation), `test_cycle_calculator.py` (math vectors, explicit `today`), `test_backtest.py` (walk-forward harness equivalence), `test_prediction_ledger.py`, `test_timezone.py` (frozen-clock ahead/behind UTC proofs, midnight boundaries, fallback), `test_care.py`, `test_therapy_and_devices.py`, `test_fertility_phase2.py` (36: observations + evidence-gated estimates), `test_pregnancy_phase3.py` (35: explicit mode + dating + suppression), `test_reproductive_aging_phase4.py` (24: notes singleton + independence proofs). Phase 2–4 implementation, migrations, and suites are worktree state pending human review and explicit commit — not yet committed, not applied to any database. New date logic must add frozen-clock tests, never depend on the machine timezone. (On locked-down Windows checkouts where `.pytest_cache` is read-only, add `-p no:cacheprovider`.)

## Development rules

- No secrets in code, logs, docs, or the mobile repo.
- No LLM output reaches hardware paths; therapy stays deterministic equations.
- No second predictor: mobile displays server values; `calculate_cycle_lengths(today=…)` always takes an explicit user-local date in production paths.
- DATE stays DATE: never convert calendar fields through UTC; timestamps stay `TIMESTAMPTZ`.
- Every new query filters by authenticated user; every new column updates model + schema + migration + tests.
- Keep `supabase_initial_schema.sql` and `migrations/` agreeing.

## Known limitations / future work

- Hardware integration and on-device validation (planned, no firmware here).
- Push-notification scheduling (planned; timezone work in this repo unblocks it).
- Deeper daily-log personalization (planned).
- More resolved predictions needed before any model comparison (ledger collects them; bar is thousands, see checkpoint docs).
- Managed cloud deployment (planned).

## Mobile client

Separate repository: [menomate-mobile](../menomate-mobile/README.md) (Flutter 3.x). It owns UI, offline-first storage, BLE, and the Daily Insight local library.

## License

MIT — see `LICENSE`. Third-party inspirations (Mensinator, Metra, YIMA) are attributed in `THIRD_PARTY_NOTICES.md`.
