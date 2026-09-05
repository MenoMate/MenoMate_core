-- =============================================================================
-- MenoMate Core - Initial Supabase PostgreSQL Schema (Fresh Database)
-- Target: Fresh Supabase Project
-- =============================================================================

-- 1. Profiles Table (1-to-1 with Supabase Auth users)
CREATE TABLE IF NOT EXISTS public.profiles (
    user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    name VARCHAR(128),
    usual_cycle_days INTEGER CHECK (usual_cycle_days IS NULL OR (usual_cycle_days >= 20 AND usual_cycle_days <= 45)),
    usual_period_days INTEGER CHECK (usual_period_days IS NULL OR (usual_period_days >= 1 AND usual_period_days <= 12)),
    theme VARCHAR(32) NOT NULL DEFAULT 'system',
    units VARCHAR(32) NOT NULL DEFAULT 'metric',
    sensitivity_index DOUBLE PRECISION NOT NULL DEFAULT 1.0 CHECK (sensitivity_index >= 0.5 AND sensitivity_index <= 1.5),
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
    CONSTRAINT chk_period_dates CHECK (period_end IS NULL OR period_end >= period_start)
);

CREATE INDEX IF NOT EXISTS idx_cycles_user_start ON public.cycles(user_id, period_start);

-- 3. Daily Logs Table (One record per user per calendar day)
CREATE TABLE IF NOT EXISTS public.daily_logs (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES public.profiles(user_id) ON DELETE CASCADE,
    log_date DATE NOT NULL,
    pain INTEGER NOT NULL DEFAULT 0 CHECK (pain >= 0 AND pain <= 10),
    mood VARCHAR(32),
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
    target_temperature_c DOUBLE PRECISION CHECK (target_temperature_c IS NULL OR target_temperature_c <= 44.0),
    vibration_intensity INTEGER CHECK (vibration_intensity IS NULL OR (vibration_intensity >= 0 AND vibration_intensity <= 100)),
    vibration_mode VARCHAR(32),
    pain_before INTEGER CHECK (pain_before IS NULL OR (pain_before >= 0 AND pain_before <= 10)),
    pain_after INTEGER CHECK (pain_after IS NULL OR (pain_after >= 0 AND pain_after <= 10)),
    feedback VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_therapy_sessions_user ON public.therapy_sessions(user_id);

-- 7. Chat Conversations Table (Care interaction threads)
CREATE TABLE IF NOT EXISTS public.chat_conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles(user_id) ON DELETE CASCADE,
    title VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_conversations_user ON public.chat_conversations(user_id);

-- 8. Chat Messages Table (Messages within Care conversations)
CREATE TABLE IF NOT EXISTS public.chat_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES public.chat_conversations(id) ON DELETE CASCADE,
    role VARCHAR(32) NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_conv ON public.chat_messages(conversation_id);
