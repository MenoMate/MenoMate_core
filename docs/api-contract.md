# MenoMate API Contract (Developer Reference)

Practical reference for the production backend on `main`. The exact machine-readable contract is Swagger/OpenAPI at `/docs` (`/openapi.json`); this file does not duplicate every schema verbatim. All paths below are prefixed by `API_V1_STR` (default `/api/v1`).

Conventions (apply to every domain unless stated):

- Auth: `Authorization: Bearer <Supabase access token>` required → 401 when missing/invalid. Ownership is the JWT `sub` UUID; request bodies must not contain `user_id` (extra keys ignored).
- Cross-user id access → 404 (no existence leak). Validation: Pydantic shape → 422; domain rules (overlap, future-date, joint-null) → 400; true conflicts (device claim, pregnancy provenance downgrade, observation date clash on PATCH) → 409.
- DATE fields are user-local calendar dates (`YYYY-MM-DD`, never UTC-shifted); instants are UTC `TIMESTAMPTZ`.
- Actual surface: 29 API v1 paths / 47 API v1 operations (+ `GET /`, `GET /health`).

## Health / root (no auth)

| Method | Path | Purpose | Notes |
|---|---|---|---|
| GET | `/health` | Render health check + smoke test | Returns `{"status": "healthy", ...}`; no auth |
| GET | `/` | Welcome pointer | Returns `docs`/`health` links; no auth |

## Auth

| Method | Path | Auth | Purpose / fields |
|---|---|---|---|
| GET | `/api/v1/auth/me` | Required | Identity + auto-provision profile. Response: user id, profile presence. |

## Profile

| Method | Path | Key request fields | Key response fields | Rules |
|---|---|---|---|---|
| GET | `/api/v1/profile` | — | `user_id`, `name`, usuals, `timezone`, paired `birth_year`/`birth_month` | Owner only |
| PATCH | `/api/v1/profile` | `name`, `usual_cycle_days` 20–45, `usual_period_days` 1–12, IANA `timezone` ≤64, paired birth fields | Updated profile | Birth fields set/cleared together; timezone validated by `ZoneInfo` |
| DELETE | `/api/v1/profile` | — | 204 (PostgreSQL rows only, not the Supabase Auth user) | Cascades all user rows (GDPR erasure path) |

## Onboarding

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/v1/onboarding/complete` | Required | Atomic profile + first period in one transaction. Request: `name` (required non-blank), `last_period_start`, nullable `last_period_end`, usuals, `timezone`. Response 201: `message`, `profile`, `period_id`, `period_start`, `period_end`. Idempotent re-onboarding; per-user asyncio lock + unique-constraint guard. |

Onboarding completion = profile carries a non-blank `name` AND at least one cycle exists. Selecting a pregnancy interest here does NOT activate pregnancy mode (see Pregnancy).

## Cycles

Grain is a bleeding occurrence (`period_start` = first bleeding day, nullable `period_end`), not a full start-to-start record. Lengths derive start-to-start.

| Method | Path | Purpose / behavior |
|---|---|---|
| GET | `/api/v1/cycles` | List own periods (ordered). |
| POST | `/api/v1/cycles` | Create period. Overlap validation; exactly one ongoing (`period_end IS NULL`) at a time; `period_start` keeps an intentional +1-day display-only tolerance anchored to user-local today; `period_end` strict (`<= today`, duration ≤30d). Duplicate same-user start deterministically **upserts** (201, same row) — not 409. |
| GET | `/api/v1/cycles/current` | Active-cycle status + prediction (commits a prediction-ledger snapshot). Response: `has_data`, `current_cycle_day`, `phase`, `is_bleeding`, `predicted_next_period`, `days_until_next_period` (≥0), `prediction_status` (`upcoming`/`today`/`awaiting_next_start`), confidence/source. |
| POST | `/api/v1/cycles/current/end` | Retrospective "ended today" on user-local today (or explicit `period_end` ≤ today, ≤30d duration). 404 when no active period. |
| PATCH | `/api/v1/cycles/{cycle_id}` | Partial update; explicit-null `period_end` reopens; boundary-day collision auto-resolves previous end to yesterday; cross-user id → 404. |

## Daily logs / symptoms

Full-day upsert keyed on `(user_id, log_date)`; omitted `log_date` defaults to user-local today; supplied dates preserved exactly.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/v1/symptoms` | None (public catalogue) | Static `SUPPORTED_SYMPTOMS` metadata (11 ids; no LH/BBT/mucus types). |
| GET | `/api/v1/logs` | Required | List own logs (range filters). |
| POST | `/api/v1/logs` | Required | Full-day upsert (200): `log_date`, `pain` (nullable; NULL = not provided, 0 = explicit no pain), multi-select `mood` (JSON-array TEXT), `discharge` volume scale, `flow`, `notes`, symptoms. |
| GET | `/api/v1/logs/{log_date}` | Required | Fetch one day (null when absent). |
| PATCH | `/api/v1/logs/{log_id}` | Required | Partial with explicit-null clearing. Cross-user id → 404. |

`discharge` is a generic volume scale, distinct from the fertility `mucus_category` taxonomy. Symptom taxonomy is fixed; free text only in `notes`.

## Summaries

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/summary/current` | Current-cycle status: day, phase (educational), bleeding, prediction + confidence/status, averages. Uses user-local today. |
| GET | `/api/v1/summary/history` | Per-period lengths, variability, symptom frequencies. |

Phase `ovulation` here is a count-back educational label, not a fertile-window estimate.

## Health context (user-provided context only)

Stored verbatim, returned to owner only; never diagnoses, never infers, never alters predictions. PUT = full replacement (omitted → null); PATCH = partial with explicit-null clearing.

| Method | Path | Purpose |
|---|---|---|
| GET/PUT/PATCH | `/api/v1/health-context` | Singleton: `contraception_method` (14 values incl. `fertility_awareness` — a contraception choice, not an observation), `pregnancy_context` (`trying_to_conceive`/`avoiding_pregnancy`/`pregnant`/`postpartum`/`not_applicable`/`prefer_not_to_say` — free selection, zero behavioral effect), free-text notes (1000/2000 limits, reject-don't-truncate). |
| GET/POST | `/api/v1/health-context/conditions` | List/create condition (`condition_code` from 12-value allowlist incl. `other` + `custom_label` contract). Duplicate curated code → 409. |
| PATCH/DELETE | `/api/v1/health-context/conditions/{condition_id}` | Update/deactivate or hard-delete. Cross-user id → 404. |
| GET/POST | `/api/v1/health-context/medications` | List/create medication (`name` contract). |
| PATCH/DELETE | `/api/v1/health-context/medications/{medication_id}` | Update/deactivate or hard-delete. |

## Reproductive — fertility observations (OBSERVED facts)

| Method | Path | Key fields | Behavior |
|---|---|---|---|
| POST | `/api/v1/reproductive/observations` | `observation_date?` (default user-local today), `observation_type` (`lh_test`/`bbt`/`cervical_mucus`), exactly-one value column: `lh_result` (`positive`/`negative`/`invalid`) \| `bbt_celsius` 35.00–42.00 \| `mucus_category` (`dry`/`sticky`/`creamy`/`watery`/`egg_white`), `source` (`manual`/`imported`), `note` ≤1000 | Upsert per (user, date, type): 201 create, 200 overwrite; race converges last-writer-wins. Future dates → 400 (`observation_date <= today`). LH positive records a test outcome only, never ovulation proof. |
| GET | `/api/v1/reproductive/observations` | `?start_date&end_date&type` | Owner list newest-first. `start_date > end_date` → 422. |
| PATCH | `/api/v1/reproductive/observations/{observation_id}` | Same-type value edits only (no LH→BBT morphing); explicit-null clears `note`; date moves re-check unique key (clash → 409) | Cross-user id → 404. |
| DELETE | `/api/v1/reproductive/observations/{observation_id}` | — | 204 hard delete (retraction). |

## Reproductive — fertility estimates (server-computed, read-only)

| Method | Path | Behavior |
|---|---|---|
| GET | `/api/v1/reproductive/estimates` | Compute-on-read from completed history + in-scope observations + pregnancy suppression. `?as_of?` defaults to user-local today; future → 400. Response: `status` (`AVAILABLE`/`LOW_CONFIDENCE`/`INSUFFICIENT_DATA`/`SUPPRESSED`), dated window (`ovulation_date_estimate`, `fertile_window_start/end`) only when `AVAILABLE`, `confidence`, `evidence_source` (`OBSERVED`/`ESTIMATED`/`CLINICALLY_CONFIRMED` vocabulary; anchor LH-positive rows surface as `ESTIMATED`), `evidence` metadata, `method` (`fertility_v1`) / `method_version` (`1.0.0`), `calculated_at`, `timezone_name`, disclaimer. Null dates on insufficient/suppressed/low-confidence are HTTP 200, never 404. No POST/PUT/PATCH exists by design. |

Rules: never contraception, never diagnosis, never proof of ovulation or (in)fertility. `usual_cycle_days` is deliberately NOT a fertility fallback. Estimator parameters (luteal 14d, window −5/+1d) are named product parameters pending clinical sign-off.

## Reproductive — pregnancy (explicit mode)

Singleton `pregnancy_contexts`; absence = never entered. Legacy `health_contexts.pregnancy_context` is never read/written here. PUT = full replacement (omitted → null, `is_active` defaults true); PATCH = partial with explicit-null clearing.

| Method | Path | Behavior |
|---|---|---|
| GET | `/api/v1/reproductive/pregnancy` | Singleton or inactive unset default (read-only; creates nothing). Derived fields: `edd_status` (`available`/`unavailable`), `edd_label`, `dating_confidence` (`CLINICALLY_CONFIRMED` only for clinician source), gestational age (LMP subtraction preferred, else 280-day EDD reference), `days_until_due`, `as_of_date`, `timezone_name`. |
| PUT | `/api/v1/reproductive/pregnancy` | Activate/replace. Fields: `is_active`, `dating_source` (`lmp`/`ultrasound`/`clinician`/`unknown`; required when EDD set), verbatim `estimated_due_date`, `lmp_date` (only with `lmp` source), `confirmation_date` (≤ today), `dating_note` ≤1000. Lower-provenance differing EDD over higher-provenance stored EDD → 409. |
| PATCH | `/api/v1/reproductive/pregnancy` | Partial update; same 409 protection. `{is_active:false}` pauses (history retained), never automatic. |
| DELETE | `/api/v1/reproductive/pregnancy` | 204 hard delete (erasure), distinct from pause. |

Effects: fertility estimates return `SUPPRESSED` while `is_active`; period predictions, summaries, cycles, logs, and history are unaffected and remain available. EDDs stored verbatim (server never auto-computes); gestational age is a derived estimate, not clinical confirmation.

## Reproductive — aging context (notes only)

| Method | Path | Behavior |
|---|---|---|
| GET | `/api/v1/reproductive/aging-context` | Singleton or unset default (`has_context: false`, nulls). Read-only; creates nothing. Fixed `provenance: "user_declared"` + safety disclaimer. |
| PUT | `/api/v1/reproductive/aging-context` | Full-replacement upsert: `notes` (≤2000, verbatim; omitted/null clears). Creates on first sync. Over-long → 422. No PATCH/DELETE surface (return 404/405). |

Guarantees: no staging/diagnosis/detection vocabulary; no dates; alters no predictions, estimates, pregnancy mode, health context, or history; coexists independently with pregnancy mode.

## Devices

| Method | Path | Behavior |
|---|---|---|
| GET | `/api/v1/devices` | List own BLE identifiers. |
| POST | `/api/v1/devices` | Register `device_identifier` (unique globally); cross-user claim → 409. |
| DELETE | `/api/v1/devices/{device_id}` | Unpair (SET NULL on therapy sessions). Cross-user id → 404. |

## Therapy

Deterministic policy only (`therapy_policy.py`); 44.0 °C ceiling enforced at API and schema layers.

| Method | Path | Behavior |
|---|---|---|
| POST | `/api/v1/therapy/recommend` | Input: `pain_score` 0–10 (+ optional sensitivity context). Output: banded `target_temperature_c` (pain 0 → 0.0 idle; 1–4 → 35–38; 5–7 → 38–41; 8–10 → 40–44), `vibration_mode`/`intensity`, `duration_minutes`, reasoning. Never exceeds 44.0. |
| GET | `/api/v1/therapy/sessions` | List own session telemetry. |
| POST | `/api/v1/therapy/sessions` | Log session (`device_id` ownership-checked, `started_at`/`ended_at` UTC instants, mode/vibration within bounds). |
| PATCH | `/api/v1/therapy/sessions/{session_id}` | Single-use feedback (`insufficient_relief` +0.05 / `too_hot` −0.08 / `just_right` 0; sensitivity clamped 0.80–1.20); double-apply guarded. Cross-user id → 404. |

## Care (guided assistance)

**Only `POST /api/v1/care/interactions` exists. There is no `/api/v1/care/interact` alias.** (The Phase 1 design doc mentions an alias; it was never implemented — the OpenAPI list above is authoritative.)

| Method | Path | Request | Response | Behavior |
|---|---|---|---|---|
| POST | `/api/v1/care/interactions` | `intent` (10-value enum incl. `cycle_insight`, `therapy_recommendation`, `other`; default `wellness_help`), `user_message?` ≤500, `recent_turns[]` transient (`role: user\|care`, `text` ≤500, `topic?`) | `intent`, `response_text`, `is_ai_generated`, `tier` (`info`/`advisory`/`urgent`), `actions[]` (`{id, label}` deterministic), `disclaimer`, `therapy_profile?` (`GENTLE`/`MODERATE`/`STRONG` or null) | JWT required. Pipeline: context builder → deterministic triage (out-of-scope / diagnosis / medication frames; red-flag escalation) → Groq LLM optional (unset key → mock) → composer guards (explained-text/followup validation, therapy-profile cross-check, hardware-field block) → advisory text. Model never chooses actions; `recent_turns` never persisted. |

Safety: deterministic decisions are never contradicted by the model; temperature/PWM/GPIO/BLE/motor fields are forbidden in model output; only backend-defined profile names may pass. Output never diagnoses and never controls hardware.
