-- 0004: daily_logs.mood becomes TEXT for multi-select storage.
--
-- Mood is now a JSON array string (e.g. '["happy", "calm"]'); NULL means
-- no mood logged. Existing short values fit TEXT unchanged, so no data
-- migration is needed — only the length constraint is lifted.

ALTER TABLE public.daily_logs ALTER COLUMN mood TYPE TEXT;
