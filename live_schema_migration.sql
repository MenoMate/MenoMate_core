-- =============================================================================
-- MenoMate Core - Explicit Idempotent Migration for Live PostgreSQL Database
-- Target: Live Supabase Database (lnuhglauxlqtqzetvshz)
-- Purpose: Safely migrate existing prototype tables (profiles, cycles,
--          daily_logs, therapy_sessions) and create missing tables/constraints
--          to achieve exact 100% parity with supabase_initial_schema.sql.
-- =============================================================================

-- 0. Enable pgcrypto
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

-- Rename legacy column 'id' to 'user_id' if present
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

-- Add missing columns safely
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS name VARCHAR(128);
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS usual_cycle_days INTEGER;
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS usual_period_days INTEGER;
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS theme VARCHAR(32) NOT NULL DEFAULT 'system';
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS units VARCHAR(32) NOT NULL DEFAULT 'metric';
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS sensitivity_index DOUBLE PRECISION NOT NULL DEFAULT 1.0;
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- Migrate old column values if present
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = 'profiles' AND column_name = 'cycle_length_avg'
    ) THEN
        UPDATE public.profiles SET usual_cycle_days = cycle_length_avg WHERE usual_cycle_days IS NULL AND cycle_length_avg IS NOT NULL;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = 'profiles' AND column_name = 'period_length_avg'
    ) THEN
        UPDATE public.profiles SET usual_period_days = period_length_avg WHERE usual_period_days IS NULL AND period_length_avg IS NOT NULL;
    END IF;
END $$;

-- Add check constraints to profiles
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_profiles_cycle_days') THEN
        ALTER TABLE public.profiles ADD CONSTRAINT chk_profiles_cycle_days 
            CHECK (usual_cycle_days IS NULL OR (usual_cycle_days >= 20 AND usual_cycle_days <= 45));
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_profiles_period_days') THEN
        ALTER TABLE public.profiles ADD CONSTRAINT chk_profiles_period_days 
            CHECK (usual_period_days IS NULL OR (usual_period_days >= 1 AND usual_period_days <= 12));
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_profiles_sensitivity') THEN
        ALTER TABLE public.profiles ADD CONSTRAINT chk_profiles_sensitivity 
            CHECK (sensitivity_index >= 0.5 AND sensitivity_index <= 1.5);
    END IF;
END $$;

-- Ensure foreign key to auth.users exists
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint c
        JOIN pg_class t ON c.conrelid = t.oid
        JOIN pg_namespace n ON t.relnamespace = n.oid
        WHERE n.nspname = 'public' AND t.relname = 'profiles' AND c.contype = 'f'
    ) THEN
        ALTER TABLE public.profiles 
            ADD CONSTRAINT fk_profiles_auth_users 
            FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;
    END IF;
END $$;

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

-- Rename legacy start_date -> period_start and end_date -> period_end
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

ALTER TABLE public.cycles ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE public.cycles ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- Add constraints to cycles
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_period_dates') THEN
        ALTER TABLE public.cycles ADD CONSTRAINT chk_period_dates 
            CHECK (period_end IS NULL OR period_end >= period_start);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_cycle_user_period_start') THEN
        ALTER TABLE public.cycles ADD CONSTRAINT uq_cycle_user_period_start 
            UNIQUE (user_id, period_start);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_cycles_user_start ON public.cycles(user_id, period_start);

-- -----------------------------------------------------------------------------
-- 3. Daily Logs Table Migration
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
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Rename legacy columns: cramp_severity -> pain, flow_intensity -> flow
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = 'daily_logs' AND column_name = 'cramp_severity'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = 'daily_logs' AND column_name = 'pain'
    ) THEN
        ALTER TABLE public.daily_logs RENAME COLUMN cramp_severity TO pain;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = 'daily_logs' AND column_name = 'flow_intensity'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = 'daily_logs' AND column_name = 'flow'
    ) THEN
        ALTER TABLE public.daily_logs RENAME COLUMN flow_intensity TO flow;
    END IF;
END $$;

ALTER TABLE public.daily_logs ADD COLUMN IF NOT EXISTS pain INTEGER NOT NULL DEFAULT 0;
ALTER TABLE public.daily_logs ADD COLUMN IF NOT EXISTS mood VARCHAR(32);
ALTER TABLE public.daily_logs ADD COLUMN IF NOT EXISTS discharge VARCHAR(32);
ALTER TABLE public.daily_logs ADD COLUMN IF NOT EXISTS flow VARCHAR(32);
ALTER TABLE public.daily_logs ADD COLUMN IF NOT EXISTS notes TEXT;
ALTER TABLE public.daily_logs ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE public.daily_logs ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- Add constraints to daily_logs
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_daily_logs_pain') THEN
        ALTER TABLE public.daily_logs ADD CONSTRAINT chk_daily_logs_pain 
            CHECK (pain >= 0 AND pain <= 10);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_user_log_date') THEN
        ALTER TABLE public.daily_logs ADD CONSTRAINT uq_user_log_date 
            UNIQUE (user_id, log_date);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_daily_logs_user_date ON public.daily_logs(user_id, log_date);

-- -----------------------------------------------------------------------------
-- 4. Symptom Logs Table (Child records of daily logs)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.symptom_logs (
    id SERIAL PRIMARY KEY,
    daily_log_id INTEGER NOT NULL REFERENCES public.daily_logs(id) ON DELETE CASCADE,
    symptom_type VARCHAR(64) NOT NULL,
    severity INTEGER NOT NULL DEFAULT 0 CHECK (severity >= 0 AND severity <= 10)
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
-- 6. Therapy Sessions Table Migration
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

-- Rename legacy columns: timestamp -> started_at, target_temp_celsius -> target_temperature_c, pre_cramp_score -> pain_before, post_relief_score -> pain_after, feedback_tag -> feedback
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = 'therapy_sessions' AND column_name = 'timestamp'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = 'therapy_sessions' AND column_name = 'started_at'
    ) THEN
        ALTER TABLE public.therapy_sessions RENAME COLUMN timestamp TO started_at;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = 'therapy_sessions' AND column_name = 'target_temp_celsius'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = 'therapy_sessions' AND column_name = 'target_temperature_c'
    ) THEN
        ALTER TABLE public.therapy_sessions RENAME COLUMN target_temp_celsius TO target_temperature_c;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = 'therapy_sessions' AND column_name = 'pre_cramp_score'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = 'therapy_sessions' AND column_name = 'pain_before'
    ) THEN
        ALTER TABLE public.therapy_sessions RENAME COLUMN pre_cramp_score TO pain_before;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = 'therapy_sessions' AND column_name = 'post_relief_score'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = 'therapy_sessions' AND column_name = 'pain_after'
    ) THEN
        ALTER TABLE public.therapy_sessions RENAME COLUMN post_relief_score TO pain_after;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = 'therapy_sessions' AND column_name = 'feedback_tag'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = 'therapy_sessions' AND column_name = 'feedback'
    ) THEN
        ALTER TABLE public.therapy_sessions RENAME COLUMN feedback_tag TO feedback;
    END IF;
END $$;

ALTER TABLE public.therapy_sessions ADD COLUMN IF NOT EXISTS device_id UUID REFERENCES public.devices(id) ON DELETE SET NULL;
ALTER TABLE public.therapy_sessions ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE public.therapy_sessions ADD COLUMN IF NOT EXISTS ended_at TIMESTAMPTZ;
ALTER TABLE public.therapy_sessions ADD COLUMN IF NOT EXISTS mode VARCHAR(32) NOT NULL DEFAULT 'standard';
ALTER TABLE public.therapy_sessions ADD COLUMN IF NOT EXISTS target_temperature_c DOUBLE PRECISION;
ALTER TABLE public.therapy_sessions ADD COLUMN IF NOT EXISTS vibration_intensity INTEGER;
ALTER TABLE public.therapy_sessions ADD COLUMN IF NOT EXISTS vibration_mode VARCHAR(32);
ALTER TABLE public.therapy_sessions ADD COLUMN IF NOT EXISTS pain_before INTEGER;
ALTER TABLE public.therapy_sessions ADD COLUMN IF NOT EXISTS pain_after INTEGER;
ALTER TABLE public.therapy_sessions ADD COLUMN IF NOT EXISTS feedback VARCHAR(64);
ALTER TABLE public.therapy_sessions ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- Alter columns that were NOT NULL in prototype to be nullable to match canonical schema
ALTER TABLE public.therapy_sessions ALTER COLUMN target_temperature_c DROP NOT NULL;
ALTER TABLE public.therapy_sessions ALTER COLUMN vibration_mode DROP NOT NULL;
ALTER TABLE public.therapy_sessions ALTER COLUMN vibration_intensity DROP NOT NULL;
ALTER TABLE public.therapy_sessions ALTER COLUMN pain_before DROP NOT NULL;
ALTER TABLE public.therapy_sessions ALTER COLUMN pain_after DROP NOT NULL;
ALTER TABLE public.therapy_sessions ALTER COLUMN feedback DROP NOT NULL;

-- If duration_minutes or other prototype columns were NOT NULL, allow them to be nullable
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'therapy_sessions' AND column_name = 'duration_minutes') THEN
        ALTER TABLE public.therapy_sessions ALTER COLUMN duration_minutes DROP NOT NULL;
    END IF;
END $$;

-- Add check constraints to therapy_sessions
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_therapy_temperature') THEN
        ALTER TABLE public.therapy_sessions ADD CONSTRAINT chk_therapy_temperature 
            CHECK (target_temperature_c IS NULL OR (target_temperature_c >= 0.0 AND target_temperature_c <= 44.0));
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_therapy_vibration') THEN
        ALTER TABLE public.therapy_sessions ADD CONSTRAINT chk_therapy_vibration 
            CHECK (vibration_intensity IS NULL OR (vibration_intensity >= 0 AND vibration_intensity <= 100));
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_therapy_pain_before') THEN
        ALTER TABLE public.therapy_sessions ADD CONSTRAINT chk_therapy_pain_before 
            CHECK (pain_before IS NULL OR (pain_before >= 0 AND pain_before <= 10));
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_therapy_pain_after') THEN
        ALTER TABLE public.therapy_sessions ADD CONSTRAINT chk_therapy_pain_after 
            CHECK (pain_after IS NULL OR (pain_after >= 0 AND pain_after <= 10));
    END IF;
END $$;

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

-- -----------------------------------------------------------------------------
-- 9. Column Defaults and Nullability Parity Alignment
-- -----------------------------------------------------------------------------
ALTER TABLE public.profiles ALTER COLUMN created_at SET DEFAULT NOW();
ALTER TABLE public.profiles ALTER COLUMN sensitivity_index SET DEFAULT 1.0;
ALTER TABLE public.profiles ALTER COLUMN cycle_length_avg DROP NOT NULL;
ALTER TABLE public.profiles ALTER COLUMN period_length_avg DROP NOT NULL;

ALTER TABLE public.therapy_sessions ALTER COLUMN started_at SET DEFAULT NOW();

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'cycles' AND column_name = 'is_active') THEN
        ALTER TABLE public.cycles ALTER COLUMN is_active DROP NOT NULL;
        ALTER TABLE public.cycles ALTER COLUMN is_active SET DEFAULT true;
    END IF;
END $$;

ALTER TABLE public.daily_logs ALTER COLUMN pain SET DEFAULT 0;
ALTER TABLE public.daily_logs ALTER COLUMN flow DROP NOT NULL;
ALTER TABLE public.daily_logs ALTER COLUMN mood DROP NOT NULL;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'daily_logs' AND column_name = 'symptoms') THEN
        ALTER TABLE public.daily_logs ALTER COLUMN symptoms DROP NOT NULL;
        ALTER TABLE public.daily_logs ALTER COLUMN symptoms SET DEFAULT '[]'::json;
    END IF;
END $$;
