-- ZENTRA P1/P2 schema guards
-- Idempotent migration for Supabase/Postgres.
-- P2-18: Explicit schema constraints for data integrity.

-- Enforce valid signal status values
DO $$ BEGIN
    ALTER TABLE public.signals
        ADD CONSTRAINT chk_signals_status
        CHECK (status IN ('ACTIVE', 'CLOSED_TP', 'CLOSED_SL', 'CLOSED_EXIT_SIGNAL', 'EXPIRED'));
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

-- Enforce valid signal type values
DO $$ BEGIN
    ALTER TABLE public.signals
        ADD CONSTRAINT chk_signals_signal_type
        CHECK (signal_type IN ('BUY', 'EXIT', 'WATCH', 'NO_SIGNAL'));
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

-- Enforce valid signal strength values
DO $$ BEGIN
    ALTER TABLE public.signals
        ADD CONSTRAINT chk_signals_signal_strength
        CHECK (signal_strength IN ('STRONG', 'NORMAL', 'BORDERLINE'));
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

-- Enforce valid run_logs status values
DO $$ BEGIN
    ALTER TABLE public.run_logs
        ADD CONSTRAINT chk_run_logs_status
        CHECK (status IN ('RUNNING', 'SUCCESS', 'PARTIAL', 'FAILED'));
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

-- Enforce valid run_logs mode values
DO $$ BEGIN
    ALTER TABLE public.run_logs
        ADD CONSTRAINT chk_run_logs_run_mode
        CHECK (run_mode IN ('morning', 'midday', 'closing', 'manual'));
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

-- Ensure score is bounded
DO $$ BEGIN
    ALTER TABLE public.signals
        ADD CONSTRAINT chk_signals_score_range
        CHECK (score >= -100 AND score <= 200);
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

-- Ensure confluence count is reasonable
DO $$ BEGIN
    ALTER TABLE public.signals
        ADD CONSTRAINT chk_signals_confluence_range
        CHECK (confluence_count >= 0 AND confluence_count <= 10);
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;
