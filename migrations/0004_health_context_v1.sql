-- 0004: V1 Health Context foundation (user-provided context only).
-- Safe on existing databases: nullable profile columns, new tables only,
-- no backfill, no data rewrite. All health values are explicitly
-- user-provided context: stored and returned to the owning client, never
-- interpreted (no diagnosis, no inference, no effect on predictions).
--
-- Keeps existing databases agreeing with supabase_initial_schema.sql §§8-9.

-- 1. Optional date of birth at month/year precision on profiles.
-- Both columns are always set or cleared together (enforced by the API).
ALTER TABLE public.profiles
    ADD COLUMN IF NOT EXISTS birth_year INTEGER
        CHECK (birth_year IS NULL OR (birth_year >= 1900 AND birth_year <= 2100));
ALTER TABLE public.profiles
    ADD COLUMN IF NOT EXISTS birth_month INTEGER
        CHECK (birth_month IS NULL OR (birth_month >= 1 AND birth_month <= 12));

-- 2. Singleton per-user health context (contraception, pregnancy/fertility
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

-- 3. User-reported health conditions (context, NOT a MenoMate diagnosis).
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

-- 4. User-provided medications / treatments (context only).
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

-- 5. RLS defense-in-depth (default-deny, consistent with §9 posture):
-- no permissive policies; the privileged backend connection bypasses RLS
-- while direct anon/authenticated access stays denied.
ALTER TABLE public.health_contexts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.health_conditions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.medications ENABLE ROW LEVEL SECURITY;
