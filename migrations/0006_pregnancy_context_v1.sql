-- 0006: Phase 3 explicit pregnancy mode + pregnancy dating (NEW behavioral state).
-- Additive and safe on existing databases: one new singleton table only, no
-- backfill, no data rewrite, no change to any existing column, semantic, or
-- index. Keeps existing databases agreeing with the pregnancy-contexts table
-- in supabase_initial_schema.sql.
--
-- Grain: one row per user that has ever entered pregnancy mode
-- (user_id PK); absence = never entered. is_active = FALSE retains history
-- with mode off; DELETE erases the row.
--
-- Distinct from the legacy health_contexts.pregnancy_context free selection,
-- which keeps its existing zero-behavioral-effect semantics and is never
-- reinterpreted or migrated here (no backfill by design).
--
-- dating_source uses the Phase 1 contract vocabulary
-- (lmp | ultrasound | clinician | unknown) with precedence
-- clinician > ultrasound > lmp > unknown (enforced at the service layer with
-- HTTP 409 on silent lower-over-higher EDD replacement; see
-- app/services/pregnancy.py). The server never auto-computes an EDD from an
-- LMP date (Phase 1 §8.5); EDDs are stored verbatim.
--
-- All DATEs are USER-LOCAL calendar dates (never shifted through UTC);
-- created_at/updated_at are TIMESTAMPTZ instants.

CREATE TABLE IF NOT EXISTS public.pregnancy_contexts (
    user_id UUID PRIMARY KEY REFERENCES public.profiles(user_id) ON DELETE CASCADE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    dating_source VARCHAR(32),
    estimated_due_date DATE,
    lmp_date DATE,
    confirmation_date DATE,
    dating_note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_pregnancy_dating_source
        CHECK (dating_source IS NULL OR dating_source IN
            ('lmp', 'ultrasound', 'clinician', 'unknown')),
    CONSTRAINT ck_pregnancy_edd_requires_known_source
        CHECK ((estimated_due_date IS NULL) OR
            (dating_source IN ('lmp', 'ultrasound', 'clinician'))),
    CONSTRAINT ck_pregnancy_lmp_only_for_lmp_source
        CHECK ((lmp_date IS NULL) OR (dating_source = 'lmp')),
    CONSTRAINT ck_pregnancy_lmp_before_edd
        CHECK ((lmp_date IS NULL OR estimated_due_date IS NULL
            OR lmp_date <= estimated_due_date)),
    CONSTRAINT ck_pregnancy_confirmation_before_edd
        CHECK ((confirmation_date IS NULL OR estimated_due_date IS NULL
            OR confirmation_date <= estimated_due_date))
);

-- RLS defense-in-depth (default-deny, consistent with §§9/§12 posture):
-- no permissive policies; the privileged backend connection bypasses RLS
-- while direct anon/authenticated access stays denied. Do NOT add
-- USING (auth.uid() = user_id) policies and do NOT use FORCE ROW LEVEL
-- SECURITY (it would block the backend itself).
ALTER TABLE public.pregnancy_contexts ENABLE ROW LEVEL SECURITY;
