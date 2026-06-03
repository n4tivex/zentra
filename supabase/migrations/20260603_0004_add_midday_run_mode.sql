-- Allow the new midday scan mode in existing Supabase projects.
-- Safe to run after 20260512_0002_zentra_p1_p2.sql has already been applied.

ALTER TABLE public.run_logs
    DROP CONSTRAINT IF EXISTS chk_run_logs_run_mode;

ALTER TABLE public.run_logs
    ADD CONSTRAINT chk_run_logs_run_mode
    CHECK (run_mode IN ('morning', 'midday', 'closing', 'manual'));
