-- 0003: enable Row Level Security as defense-in-depth (default-deny).
-- Safe on existing databases: non-destructive, idempotent (re-running
-- ENABLE ROW LEVEL SECURITY is a no-op), no backfill, no data rewrite.
--
-- The FastAPI backend connects with a single privileged database role
-- (postgres/service_role, which bypasses RLS) and enforces per-user
-- isolation in application code (every query filters on the JWT `sub`).
-- It never sets a per-request Postgres user context, so auth.uid() is NULL
-- for backend traffic and per-user RLS policies CANNOT enforce isolation
-- for API requests. This migration therefore enables RLS with NO
-- permissive policies: direct access via anon/authenticated roles is
-- denied by default, while the backend's privileged connection is
-- unaffected. Do NOT add USING (auth.uid() = user_id) policies and do NOT
-- use FORCE ROW LEVEL SECURITY (it would block the backend itself).
-- Keeps existing databases agreeing with supabase_initial_schema.sql §8.
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.cycles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.daily_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.symptom_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.devices ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.therapy_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.prediction_ledger ENABLE ROW LEVEL SECURITY;
