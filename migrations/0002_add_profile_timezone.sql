-- Batch 2D-1: canonical IANA timezone for user-local calendar semantics.
-- Safe on existing databases: nullable column, no backfill (legacy NULL
-- means "not yet synced"; the mobile client persists the device timezone
-- on the next authenticated session). No data rewrite: historical DATE
-- values are user calendar dates and stay exactly as recorded.
ALTER TABLE public.profiles
    ADD COLUMN IF NOT EXISTS timezone VARCHAR(64);
