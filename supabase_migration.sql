-- =============================================================================
-- MenoMate Core - Supabase PostgreSQL Safe Non-Destructive Schema Migration
-- Purpose: Safely migrates an existing Supabase database from the legacy schema
--          (e.g., profiles.id, cycles.start_date, cycles.end_date)
--          to the canonical menomate-core schema without data loss.
-- Note: For brand-new Supabase projects, execute supabase_initial_schema.sql instead.
-- =============================================================================

-- Enable UUID extension if not present
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- -----------------------------------------------------------------------------
-- 1. Profiles Table Migration
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.profiles (
    user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    name VARCHAR(128),
    usual_cycle_days INTEGER,
    usual_period_days INTEGER,
    theme VARCHAR(32) NOT NULL DEFAULT 'system',
    units VARCHAR(32) NOT NULL DEFAULT 'metric',
    sensitivity_index DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- If table was created under legacy schema with column 'id' instead of 'user_id'
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = 'profiles' AND column_name = 'id'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = 'profiles' AND column_name = 'user_id'
    ) THEN
        ALTER TABLE public.profiles RENAME COLUMN id TO user_id;
    END IF;
END $$;

-- Add any missing columns safely
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS name VARCHAR(128);
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS usual_cycle_days INTEGER;
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS usual_period_days INTEGER;
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS theme VARCHAR(32) DEFAULT 'system';
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS units VARCHAR(32) DEFAULT 'metric';
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS sensitivity_index DOUBLE PRECISION DEFAULT 1.0;
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

-- -----------------------------------------------------------------------------
-- 2. Cycles Table Migration
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.cycles (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES public.profiles(user_id) ON DELETE CASCADE,
    period_start DATE NOT NULL,
    period_end DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Rename legacy column start_date -> period_start if present
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = 'cycles' AND column_name = 'start_date'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = 'cycles' AND column_name = 'period_start'
    ) THEN
        ALTER TABLE public.cycles RENAME COLUMN start_date TO period_start;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = 'cycles' AND column_name = 'end_date'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = 'cycles' AND column_name = 'period_end'
    ) THEN
        ALTER TABLE public.cycles RENAME COLUMN end_date TO period_end;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_cycles_user_start ON public.cycles(user_id, period_start);

-- -----------------------------------------------------------------------------
-- 3. Daily Logs Table
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.daily_logs (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES public.profiles(user_id) ON DELETE CASCADE,
    log_date DATE NOT NULL,
    pain INTEGER NOT NULL DEFAULT 0,
    mood VARCHAR(32),
    discharge VARCHAR(32),
    flow VARCHAR(32),
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_user_log_date UNIQUE (user_id, log_date)
);

CREATE INDEX IF NOT EXISTS idx_daily_logs_user_date ON public.daily_logs(user_id, log_date);

-- -----------------------------------------------------------------------------
-- 4. Symptom Logs Table (Child records of daily logs)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.symptom_logs (
    id SERIAL PRIMARY KEY,
    daily_log_id INTEGER NOT NULL REFERENCES public.daily_logs(id) ON DELETE CASCADE,
    symptom_type VARCHAR(64) NOT NULL,
    severity INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_symptom_logs_daily_log ON public.symptom_logs(daily_log_id);

-- -----------------------------------------------------------------------------
-- 5. Devices Table (Wearable BLE hardware association)
-- -----------------------------------------------------------------------------
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

-- -----------------------------------------------------------------------------
-- 6. Therapy Sessions Table
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.therapy_sessions (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES public.profiles(user_id) ON DELETE CASCADE,
    device_id UUID REFERENCES public.devices(id) ON DELETE SET NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    mode VARCHAR(32) NOT NULL DEFAULT 'standard',
    target_temperature_c DOUBLE PRECISION,
    vibration_intensity INTEGER,
    vibration_mode VARCHAR(32),
    pain_before INTEGER,
    pain_after INTEGER,
    feedback VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_therapy_sessions_user ON public.therapy_sessions(user_id);

-- -----------------------------------------------------------------------------
-- 7. Chat Conversations Table
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.chat_conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles(user_id) ON DELETE CASCADE,
    title VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_conversations_user ON public.chat_conversations(user_id);

-- -----------------------------------------------------------------------------
-- 8. Chat Messages Table
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.chat_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES public.chat_conversations(id) ON DELETE CASCADE,
    role VARCHAR(32) NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_conv ON public.chat_messages(conversation_id);
