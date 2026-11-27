-- Migration 0010: MenoMate Care personalization, device session status, and structured memory

ALTER TABLE therapy_sessions
    ADD COLUMN IF NOT EXISTS requested_heat_level INTEGER,
    ADD COLUMN IF NOT EXISTS requested_duration_minutes INTEGER,
    ADD COLUMN IF NOT EXISTS firmware_version VARCHAR(32),
    ADD COLUMN IF NOT EXISTS command_status VARCHAR(32),
    ADD COLUMN IF NOT EXISTS ack_status VARCHAR(32),
    ADD COLUMN IF NOT EXISTS session_status VARCHAR(32),
    ADD COLUMN IF NOT EXISTS comfort_rating VARCHAR(32),
    ADD COLUMN IF NOT EXISTS noticed_improvement BOOLEAN,
    ADD COLUMN IF NOT EXISTS feedback_notes VARCHAR(256);

CREATE TABLE IF NOT EXISTS care_memories (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES profiles(user_id) ON DELETE CASCADE,
    category VARCHAR(48) NOT NULL,
    key VARCHAR(64) NOT NULL,
    value VARCHAR(256) NOT NULL,
    source VARCHAR(32) NOT NULL DEFAULT 'user_explicit',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_care_memories_user_cat_key UNIQUE (user_id, category, key)
);

CREATE INDEX IF NOT EXISTS ix_care_memories_user_id ON care_memories (user_id);

ALTER TABLE care_memories ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'care_memories' AND policyname = 'care_memories_user_isolation'
    ) THEN
        CREATE POLICY care_memories_user_isolation ON care_memories
            USING (auth.uid() = user_id)
            WITH CHECK (auth.uid() = user_id);
    END IF;
END $$;
