-- Remove midday scan mode from run_logs constraint.
-- Midday scan has been removed; only morning and closing remain.

ALTER TABLE public.run_logs
    DROP CONSTRAINT IF EXISTS chk_run_logs_run_mode;

ALTER TABLE public.run_logs
    ADD CONSTRAINT chk_run_logs_run_mode
    CHECK (run_mode IN ('morning', 'closing', 'manual'));
