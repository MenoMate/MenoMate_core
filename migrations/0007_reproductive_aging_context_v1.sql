-- 0007: Phase 4 explicit reproductive-aging context (user-owned notes only).
-- Additive and safe on existing databases: one new singleton table only, no
-- backfill, no data rewrite, no change to any existing column, semantic, or
-- index. Keeps existing databases agreeing with the reproductive-aging table
-- in supabase_initial_schema.sql.
--
-- Grain: zero or one row per user that has ever recorded reproductive-aging
-- context (user_id PK); absence (or NULL notes) = no recorded context.
-- Clearing is via PUT with notes omitted/null (full-replacement semantics);
-- there is no PATCH/DELETE surface for this singleton.
--
-- Per the Phase 1 design contract (§4.3, §11) this table carries NO staging
-- enum, NO diagnosis column, NO date fields, and NO detection state: the
-- contract defines no state vocabulary, so none is invented. Notes are
-- verbatim user input (mirroring the health-notes pattern), never parsed
-- into medical facts, never altering period predictions, fertility
-- estimates, or pregnancy mode.
--
-- All DATE discipline is vacuous here (no DATE columns by design);
-- created_at/updated_at are TIMESTAMPTZ instants.

CREATE TABLE IF NOT EXISTS public.reproductive_aging_contexts (
    user_id UUID PRIMARY KEY REFERENCES public.profiles(user_id) ON DELETE CASCADE,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- RLS defense-in-depth (default-deny, consistent with §§9/§12 posture):
-- no permissive policies; the privileged backend connection bypasses RLS
-- while direct anon/authenticated access stays denied. Do NOT add
-- USING (auth.uid() = user_id) policies and do NOT use FORCE ROW LEVEL
-- SECURITY (it would block the backend itself).
ALTER TABLE public.reproductive_aging_contexts ENABLE ROW LEVEL SECURITY;
