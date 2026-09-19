# MenoMate Database and Migrations

Current-state reference for the production PostgreSQL/Supabase schema on `main`. Sources of truth: `app/models/*` (columns), `supabase_initial_schema.sql` (fresh DDL), `migrations/` (existing-DB deltas). Keep all three agreeing.

## 1. Architecture

- **Supabase PostgreSQL** is the only production database. The backend opens one async engine (`app/db/session.py`, `postgresql+asyncpg`) over a single privileged role (postgres/service_role, which bypasses RLS).
- **Primary isolation is application-level:** every query filters on the JWT `sub` (`WHERE user_id == current_user_id`; singleton reads by `user_id == sub`; id-addressed writes add `AND id == path_id` and return 404 on miss). No route trusts a client-supplied `user_id`.
- **RLS is defense-in-depth (default-deny):** `ENABLE ROW LEVEL SECURITY` with **no permissive policies** on all 13 app tables. Direct PostgREST/anon access is denied; the privileged backend connection is unaffected. Do NOT add `USING (auth.uid() = user_id)` policies (dead code at best, a PostgREST hole at worst — `auth.uid()` is NULL for backend traffic) and do NOT use `FORCE ROW LEVEL SECURITY` (blocks the backend itself). Rationale is documented in `supabase_initial_schema.sql` §11 and each migration header.
- **Ownership root:** `profiles.user_id` (= `auth.users.id`). All user tables FK to it `ON DELETE CASCADE`, so `DELETE /api/v1/profile` erases all user rows (GDPR path). `symptom_logs` is owned transitively via `daily_logs`.
- **Tests** run on in-memory sqlite via `Base.metadata.create_all` (`tests/conftest.py`); they never touch Supabase.

## 2. Tables

| Table | Grain / key | Important columns |
|---|---|---|
| `profiles` | 1 row per Supabase user; PK `user_id` UUID | `name`, `usual_cycle_days` 20–45, `usual_period_days` 1–12, `theme`, `units`, `sensitivity_index` 0.5–1.5, `timezone` VARCHAR(64) nullable IANA, `birth_year` 1900–2100 + `birth_month` 1–12 (always set/cleared together), instants |
| `cycles` | One row per bleeding occurrence; `UNIQUE(user_id, period_start)`, index `(user_id, period_start)` | `period_start DATE NOT NULL`, `period_end DATE NULL`, `CHECK (period_end IS NULL OR period_end >= period_start)`. Lengths derive start-to-start; exactly one open (`period_end IS NULL`) period at a time (app rule). |
| `daily_logs` | One row per user per calendar day; `UNIQUE(user_id, log_date)`, index `(user_id, log_date)` | `log_date DATE NOT NULL`, `pain` nullable (NULL = not provided, 0 = explicit no pain; CHECK passes on NULL), `mood` TEXT (multi-select JSON-array string; NULL = none logged), `discharge`/`flow` VARCHAR(32), `notes` TEXT, instants |
| `symptom_logs` | Child rows of `daily_logs.id` (`ON DELETE CASCADE`), index `(daily_log_id)` | `symptom_type` VARCHAR(64) (fixed 11-id taxonomy; no LH/BBT/mucus types), `severity` 0–10 |
| `devices` | User-owned BLE identifiers; `device_identifier` globally UNIQUE, index `(user_id)` | `id` UUID PK, `name`, `firmware_version`, `last_connected_at` TIMESTAMPTZ, instants |
| `therapy_sessions` | User-owned telemetry, index `(user_id)` | `device_id` → devices `ON DELETE SET NULL`, `started_at`/`ended_at` TIMESTAMPTZ, `mode`, `target_temperature_c` ≤44.0, vibration fields, `pain_before`/`pain_after`, `feedback` |
| `prediction_ledger` | One row per served model prediction; indexes `(user_id)`, `(user_id, predicted_at)` | `predicted_at DATE`, `method` (`robust_wma_v1`), lengths/dates/confidence/source/basis/MAD, `resolved_actual_start`, signed `error_days`. Observational only; never read in request paths except analysis. |
| `health_contexts` | Singleton per user (`user_id` PK) | `contraception_method`, `contraception_note`, `pregnancy_context` (free selection, zero behavioral effect), `health_notes`, instants |
| `health_conditions` | One row per user-reported condition; partial unique `(user_id, condition_code) WHERE custom_label IS NULL` | `condition_code` (12-value allowlist incl. `other`), `custom_label` (required with `other`), `note`, `is_active` |
| `medications` | One row per user-provided medication | `name`, `note`, `is_active` |
| `fertility_observations` | One row per (user, date, type); `UNIQUE(user_id, observation_date, observation_type)`, indexes `(user_id)`, `(user_id, observation_date)` | `observation_date DATE` (user-local, ≤ today), `observation_type` (`lh_test`/`bbt`/`cervical_mucus`), exactly-one value column (`lh_result` / `bbt_celsius` NUMERIC(4,2) 35.00–42.00 / `mucus_category`), `recorded_at` TIMESTAMPTZ, `source` (`manual`/`imported`), `note`. No confidence/method/window (those belong to estimates). |
| `pregnancy_contexts` | Singleton per user that ever entered mode (`user_id` PK); absence = never entered | `is_active` (false = history retained, mode off), `dating_source` (`lmp`/`ultrasound`/`clinician`/`unknown`), verbatim `estimated_due_date`, `lmp_date` (only with `lmp` source), `confirmation_date`, `dating_note`. CHECKs enforce source vocabulary, EDD-requires-known-source, LMP-source pairing, and date ordering. |
| `reproductive_aging_contexts` | Singleton per user that ever recorded context (`user_id` PK); absence/NULL = no context | `notes` TEXT (verbatim ≤2000 at API layer). No enums, no dates, no staging/diagnosis columns by design. |

## 3. Important relationships

```text
auth.users.id ── profiles.user_id (PK)
                      ├── cycles / daily_logs / devices / therapy_sessions
                      ├── prediction_ledger
                      ├── health_contexts (singleton) / health_conditions / medications
                      ├── fertility_observations
                      ├── pregnancy_contexts (singleton)
                      └── reproductive_aging_contexts (singleton)
daily_logs.id ── symptom_logs.daily_log_id
devices.id ── therapy_sessions.device_id (SET NULL on unpair)
```

All FKs `ON DELETE CASCADE` from `profiles` except the device link above. Singleton tables use `user_id` as PK (zero-or-one row per user).

## 4. User ownership

- Every row carries `user_id` except `symptom_logs` (via parent). Servers stamp ownership from the JWT `sub`; bodies must not include `user_id`.
- Singleton reads use `WHERE user_id == sub` with defaults-when-unset (never create on GET). Id-addressed writes add the id predicate and return 404 on miss — including cross-user ids.
- Unauthenticated → 401 everywhere except `/`, `/health`, `GET /api/v1/symptoms`.

## 5. DATE vs TIMESTAMPTZ semantics

- **DATE (user calendar dates, never shifted):** `period_start`, `period_end`, `log_date`, `predicted_next_period`, ledger `predicted_at`/`basis_start`/`resolved_actual_start`, `observation_date`, `estimated_due_date`, `lmp_date`, `confirmation_date`, estimate `as_of`/window dates. Stored as `DATE`, compared as dates, serialized `YYYY-MM-DD`.
- **TIMESTAMPTZ (UTC instants):** `created_at`, `updated_at`, `last_connected_at`, `started_at`/`ended_at`, `recorded_at`, `calculated_at`.
- **Resolver:** `profiles.timezone` (one IANA identifier per user) via `user_today` / `user_today_for`. NULL (legacy) falls back to the UTC date explicitly. Historical DATEs are never re-resolved; DATEs never pass through UTC conversion.

## 6. Migration ordering (actual)

There is **no `0001` file** — the implied `0001` is the initial schema itself (now represented by `supabase_initial_schema.sql`). Apply in filename order:

| File | Change |
|---|---|
| `0002_add_profile_timezone.sql` | Nullable `profiles.timezone` (no backfill; NULL = not yet synced) |
| `0003_enable_rls_defense_in_depth.sql` | Default-deny RLS on the 7 pre-health tables (no policies) |
| `0004_health_context_v1.sql` | Nullable `birth_year`/`birth_month` + `health_contexts`/`health_conditions`/`medications` + their RLS |
| `0005_fertility_observations_v1.sql` | `fertility_observations` + CHECKs + unique/indexes + RLS |
| `0006_pregnancy_context_v1.sql` | `pregnancy_contexts` singleton + CHECKs + RLS |
| `0007_reproductive_aging_context_v1.sql` | `reproductive_aging_contexts` singleton + RLS |
| `0008_nullable_daily_log_pain.sql` | `daily_logs.pain` nullable (NULL = missing; 0 = explicit no pain); drops NOT NULL/DEFAULT 0; historical 0s untouched |
| `0009_mood_text_multiselect.sql` | `daily_logs.mood` → TEXT (JSON-array multi-select; NULL = none logged) |

`0008`/`0009` are numbered after the reproductive sequence to preserve deterministic ordering without rewriting production history. Do not invent migration numbers. Each reproductive/health migration creates its tables, indexes, and default-deny RLS together; all are additive, idempotent (`IF NOT EXISTS`), with no backfill and no data rewrite. Rollback of an additive migration is `DROP TABLE IF EXISTS <new tables>` in reverse order.

Note: `0003` does not mention the health tables (they did not exist yet); `0004` covers that gap. Future tables must follow the same pattern (DDL + RLS in the same migration).

## 7. Fresh database setup

1. Create a fresh Supabase project.
2. Execute the entire `supabase_initial_schema.sql` in the Supabase SQL editor (it is the canonical DDL covering all 13 tables + RLS; §§1–11).
3. Keep `AUTO_CREATE_TABLES=false`; the app must not DDL a fresh production database.
4. Verify tables + RLS (no policies) and smoke-test `/health` + an authenticated call.

## 8. Existing database migration procedure

1. Confirm the current baseline (which `000x` files are already applied) — the repo cannot tell you this; it is a live-database fact.
2. Snapshot/backup first; rehearse on a staging clone.
3. Apply missing `migrations/` files **in filename order** in the Supabase SQL editor (or psql), exactly as written.
4. Verify fresh-schema ↔ migrations agreement (same tables/columns/CHECKs/indexes/RLS) and re-run the test suite.
5. Never edit an applied migration in place; add a new numbered file instead.

## 9. AUTO_CREATE_TABLES behavior

`app/main.py:lifespan` runs `Base.metadata.create_all` only when `settings.AUTO_CREATE_TABLES` is true **or** the engine dialect is sqlite (tests). Defaults and requirements:

- Default `false` (`.env.example`, `render.yaml`).
- Production must keep `false` — schema comes from the SQL files, never from ORM DDL.
- Local dev against Postgres should also keep `false` and use the SQL files; sqlite tests rely on the automatic path and never touch real infrastructure.
