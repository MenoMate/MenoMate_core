-- 0008: daily_logs.pain becomes nullable.
--
-- Numbered after the already-applied 0005-0007 reproductive sequence to
-- preserve deterministic filename ordering without rewriting production
-- migration history.
--
-- Semantics: NULL = user did not provide a pain value; 0 = user
-- intentionally logged no pain. Existing rows keep their stored values
-- (historical 0s are NOT reinterpreted as missing).
-- The existing CHECK (pain >= 0 AND pain <= 10) passes on NULL by SQL
-- three-valued-logic semantics, so it needs no change. DEFAULT 0 is
-- dropped so omitted inserts no longer masquerade as observations.

ALTER TABLE public.daily_logs ALTER COLUMN pain DROP NOT NULL;
ALTER TABLE public.daily_logs ALTER COLUMN pain DROP DEFAULT;
