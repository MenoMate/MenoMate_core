-- =============================================================================
-- MenoMate Core - Initial Supabase PostgreSQL Schema (Fresh Database)
-- Target: Fresh Supabase Project
-- =============================================================================

-- Enable UUID extension for gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 1. Profiles Table (1-to-1 with Supabase Auth users)
CREATE TABLE IF NOT EXISTS public.profiles (
    user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    name VARCHAR(128),
    usual_cycle_days INTEGER CHECK (usual_cycle_days IS NULL OR (usual_cycle_days >= 20 AND usual_cycle_days <= 45)),
    usual_period_days INTEGER CHECK (usual_period_days IS NULL OR (usual_period_days >= 1 AND usual_period_days <= 12)),
    theme VARCHAR(32) NOT NULL DEFAULT 'system',
    units VARCHAR(32) NOT NULL DEFAULT 'metric',
    sensitivity_index DOUBLE PRECISION NOT NULL DEFAULT 1.0 CHECK (sensitivity_index >= 0.5 AND sensitivity_index <= 1.5),
    timezone VARCHAR(64),
    birth_year INTEGER CHECK (birth_year IS NULL OR (birth_year >= 1900 AND birth_year <= 2100)),
    birth_month INTEGER CHECK (birth_month IS NULL OR (birth_month >= 1 AND birth_month <= 12)),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2. Cycles Table (Menstrual period occurrences)
CREATE TABLE IF NOT EXISTS public.cycles (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES public.profiles(user_id) ON DELETE CASCADE,
    period_start DATE NOT NULL,
    period_end DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_period_dates CHECK (period_end IS NULL OR period_end >= period_start),
    CONSTRAINT uq_cycle_user_period_start UNIQUE (user_id, period_start)
);

CREATE INDEX IF NOT EXISTS idx_cycles_user_start ON public.cycles(user_id, period_start);

-- 3. Daily Logs Table (One record per user per calendar day)
CREATE TABLE IF NOT EXISTS public.daily_logs (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES public.profiles(user_id) ON DELETE CASCADE,
    log_date DATE NOT NULL,
    -- Nullable pain: NULL = not provided; 0 = explicitly logged no pain.
    -- The CHECK passes on NULL (unknown) by SQL semantics.
    pain INTEGER CHECK (pain >= 0 AND pain <= 10),
    -- Multi-select moods as a JSON array string; NULL = none logged.
    mood TEXT,
    discharge VARCHAR(32),
    flow VARCHAR(32),
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_user_log_date UNIQUE (user_id, log_date)
);

CREATE INDEX IF NOT EXISTS idx_daily_logs_user_date ON public.daily_logs(user_id, log_date);

-- 4. Symptom Logs Table (Child records of daily logs)
CREATE TABLE IF NOT EXISTS public.symptom_logs (
    id SERIAL PRIMARY KEY,
    daily_log_id INTEGER NOT NULL REFERENCES public.daily_logs(id) ON DELETE CASCADE,
    symptom_type VARCHAR(64) NOT NULL,
    severity INTEGER NOT NULL DEFAULT 0 CHECK (severity >= 0 AND severity <= 10)
);

CREATE INDEX IF NOT EXISTS idx_symptom_logs_daily_log ON public.symptom_logs(daily_log_id);

-- 5. Devices Table (Wearable BLE hardware association)
CREATE TABLE IF NOT EXISTS public.devices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles(user_id) ON DELETE CASCADE,
    device_identifier VARCHAR(128) UNIQUE NOT NULL,
    name VARCHAR(128),
    firmware_version VARCHAR(64),
    last_connected_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_devices_user ON public.devices(user_id);

-- 6. Therapy Sessions Table (Wearable session telemetry & patient relief scores)
CREATE TABLE IF NOT EXISTS public.therapy_sessions (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES public.profiles(user_id) ON DELETE CASCADE,
    device_id UUID REFERENCES public.devices(id) ON DELETE SET NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    mode VARCHAR(32) NOT NULL DEFAULT 'standard',
    target_temperature_c DOUBLE PRECISION CHECK (target_temperature_c IS NULL OR (target_temperature_c >= 0.0 AND target_temperature_c <= 44.0)),
    vibration_intensity INTEGER CHECK (vibration_intensity IS NULL OR (vibration_intensity >= 0 AND vibration_intensity <= 100)),
    vibration_mode VARCHAR(32),
    pain_before INTEGER CHECK (pain_before IS NULL OR (pain_before >= 0 AND pain_before <= 10)),
    pain_after INTEGER CHECK (pain_after IS NULL OR (pain_after >= 0 AND pain_after <= 10)),
    feedback VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_therapy_sessions_user ON public.therapy_sessions(user_id);

-- 7. Prediction Ledger Table (Phase 3 instrumentation, observational only)
-- One row per served model prediction; resolved when the actual next period
-- start is observed. Never read by prediction or response code paths.
CREATE TABLE IF NOT EXISTS public.prediction_ledger (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES public.profiles(user_id) ON DELETE CASCADE,
    predicted_at DATE NOT NULL,
    method VARCHAR(64) NOT NULL,
    predicted_cycle_length INTEGER,
    predicted_next_period DATE,
    confidence VARCHAR(32) NOT NULL,
    source VARCHAR(32) NOT NULL,
    basis_start DATE NOT NULL,
    basis_intervals INTEGER NOT NULL,
    basis_usual INTEGER,
    variability DOUBLE PRECISION,
    resolved_actual_start DATE,
    error_days INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_prediction_ledger_user ON public.prediction_ledger(user_id);
CREATE INDEX IF NOT EXISTS idx_prediction_ledger_user_predicted_at ON public.prediction_ledger(user_id, predicted_at);

-- =============================================================================
-- 8. V1 Health Context foundation (user-provided context only)
-- All health values are explicitly user-provided context: stored and
-- returned to the owning client, never interpreted (no diagnosis, no
-- inference, no effect on prediction calculations).
-- =============================================================================

-- Singleton per-user health context (contraception, pregnancy/fertility
-- selections, free-text "anything else MenoMate should know").
CREATE TABLE IF NOT EXISTS public.health_contexts (
    user_id UUID PRIMARY KEY REFERENCES public.profiles(user_id) ON DELETE CASCADE,
    contraception_method VARCHAR(32),
    contraception_note TEXT,
    pregnancy_context VARCHAR(32),
    health_notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- User-reported health conditions (context, NOT a MenoMate diagnosis).
-- condition_code is a structured key from a small curated allowlist;
-- code 'other' carries the user's own label in custom_label.
CREATE TABLE IF NOT EXISTS public.health_conditions (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES public.profiles(user_id) ON DELETE CASCADE,
    condition_code VARCHAR(64) NOT NULL,
    custom_label VARCHAR(128),
    note TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_health_conditions_user ON public.health_conditions(user_id);

-- Backstop for the application-level duplicate check: one row per
-- (user, curated code). 'other' rows carry custom_label and are excluded.
CREATE UNIQUE INDEX IF NOT EXISTS uq_health_condition_user_code
    ON public.health_conditions(user_id, condition_code)
    WHERE custom_label IS NULL;

-- User-provided medications / treatments (context only).
CREATE TABLE IF NOT EXISTS public.medications (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES public.profiles(user_id) ON DELETE CASCADE,
    name VARCHAR(128) NOT NULL,
    note TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_medications_user ON public.medications(user_id);

-- =============================================================================
-- 9. Row Level Security (defense-in-depth, default-deny)
-- =============================================================================
-- The FastAPI backend connects with a single privileged database role
-- (postgres/service_role, which bypasses RLS) and enforces per-user
-- isolation in application code: every query filters on the JWT `sub`.
-- The backend never sets a per-request Postgres user context, so
-- auth.uid() is NULL for backend traffic and per-user RLS policies CANNOT
-- enforce isolation for API requests. Therefore:
-- - Do NOT add USING (auth.uid() = user_id) policies: they would be dead
--   code suggesting a guarantee that does not exist, and any permissive
--   policy would open direct PostgREST access the architecture forbids
--   (Flutter never touches the database; FastAPI is the only access layer).
-- - Do NOT use FORCE ROW LEVEL SECURITY: it applies RLS even to table
--   owners and would block the backend itself.
-- Enabling RLS with NO permissive policies is intentional default-deny:
-- direct access via the anon/authenticated roles (e.g. leaked anon key +
-- PostgREST) is denied, while the backend's privileged connection is
-- unaffected. Application-level checks remain the primary enforcement.
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.cycles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.daily_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.symptom_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.devices ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.therapy_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.prediction_ledger ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.health_contexts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.health_conditions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.medications ENABLE ROW LEVEL SECURITY;
