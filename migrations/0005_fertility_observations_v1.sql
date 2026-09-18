-- 0005: Phase 2 fertility observations (OBSERVED user-measured facts).
-- Additive and safe on existing databases: one new table only, no backfill,
-- no data rewrite, no change to any existing column, semantic, or index.
-- Keeps existing databases agreeing with supabase_initial_schema.sql §10.
--
-- Grain: one row per (user, local calendar date, observation type).
-- observation_date is a USER-LOCAL calendar DATE (never shifted through UTC).
-- This table is deliberately separate from daily_logs.discharge (a generic
-- volume scale) and from symptom_logs (fixed taxonomy); it carries no
-- confidence, method version, or window dates (those belong to estimates).
-- An LH row records the test result only and never claims ovulation occurred.

CREATE TABLE IF NOT EXISTS public.fertility_observations (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES public.profiles(user_id) ON DELETE CASCADE,
    observation_date DATE NOT NULL,
    observation_type VARCHAR(32) NOT NULL,
    lh_result VARCHAR(16),
    bbt_celsius NUMERIC(4, 2),
    mucus_category VARCHAR(32),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source VARCHAR(32) NOT NULL DEFAULT 'manual',
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_fertility_obs_type
        CHECK (observation_type IN ('lh_test', 'bbt', 'cervical_mucus')),
    CONSTRAINT ck_fertility_obs_value_matches_type
        CHECK (
            (observation_type = 'lh_test' AND lh_result IS NOT NULL
                AND bbt_celsius IS NULL AND mucus_category IS NULL)
            OR (observation_type = 'bbt' AND bbt_celsius IS NOT NULL
                AND lh_result IS NULL AND mucus_category IS NULL)
            OR (observation_type = 'cervical_mucus' AND mucus_category IS NOT NULL
                AND lh_result IS NULL AND bbt_celsius IS NULL)
        ),
    CONSTRAINT ck_fertility_obs_lh
        CHECK (lh_result IS NULL OR lh_result IN ('positive', 'negative', 'invalid')),
    CONSTRAINT ck_fertility_obs_bbt_range
        CHECK (bbt_celsius IS NULL OR (bbt_celsius >= 35.00 AND bbt_celsius <= 42.00)),
    CONSTRAINT ck_fertility_obs_mucus
        CHECK (mucus_category IS NULL OR mucus_category IN
            ('dry', 'sticky', 'creamy', 'watery', 'egg_white')),
    CONSTRAINT ck_fertility_obs_source
        CHECK (source IN ('manual', 'imported')),
    CONSTRAINT uq_fertility_obs_user_date_type
        UNIQUE (user_id, observation_date, observation_type)
);

CREATE INDEX IF NOT EXISTS idx_fertility_obs_user
    ON public.fertility_observations(user_id);
CREATE INDEX IF NOT EXISTS idx_fertility_obs_user_date
    ON public.fertility_observations(user_id, observation_date);

-- RLS defense-in-depth (default-deny, consistent with §§9/§12 posture):
-- no permissive policies; the privileged backend connection bypasses RLS
-- while direct anon/authenticated access stays denied. Do NOT add
-- USING (auth.uid() = user_id) policies and do NOT use FORCE ROW LEVEL
-- SECURITY (it would block the backend itself).
ALTER TABLE public.fertility_observations ENABLE ROW LEVEL SECURITY;
