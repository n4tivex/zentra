-- ZENTRA production hardening schema guards.
-- Idempotent migration for run locks, external calendar records, and telemetry.

create table if not exists public.market_calendar_closures (
    id uuid primary key default gen_random_uuid(),
    market text not null default 'IDX',
    trade_date date not null,
    closure_type text not null,
    description text,
    source_reference text not null,
    effective_year integer not null,
    updated_at timestamptz not null default now(),
    created_at timestamptz not null default now()
);

create unique index if not exists uq_market_calendar_closure_market_date
    on public.market_calendar_closures (market, trade_date);

create index if not exists idx_market_calendar_closures_year
    on public.market_calendar_closures (market, effective_year, trade_date);

create table if not exists public.run_locks (
    id uuid primary key default gen_random_uuid(),
    lock_key text not null,
    run_mode text not null,
    run_date date not null,
    run_slot text not null,
    owner_run_id uuid references public.run_logs(id) on delete set null,
    acquired_at timestamptz not null default now(),
    released_at timestamptz,
    created_at timestamptz not null default now()
);

create unique index if not exists uq_run_locks_active_key
    on public.run_locks (lock_key)
    where released_at is null;

create index if not exists idx_run_locks_date_slot
    on public.run_locks (run_date, run_mode, run_slot);

alter table public.run_logs
    add column if not exists run_slot text,
    add column if not exists fetched_count integer,
    add column if not exists cached_count integer,
    add column if not exists missing_count integer,
    add column if not exists failure_count integer,
    add column if not exists missing_tickers text[],
    add column if not exists failed_fetch_tickers text[],
    add column if not exists calendar_reason text,
    add column if not exists data_readiness_status text,
    add column if not exists failure_category text,
    add column if not exists admin_alert_sent boolean;

DO $$ BEGIN
    ALTER TABLE public.run_logs
        ADD CONSTRAINT chk_run_logs_calendar_reason
        CHECK (
            calendar_reason IS NULL
            OR calendar_reason IN (
                'weekend',
                'official_holiday',
                'market_data_pending',
                'provider_stale',
                'calendar_override'
            )
        );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE public.run_logs
        ADD CONSTRAINT chk_run_logs_data_readiness_status
        CHECK (
            data_readiness_status IS NULL
            OR data_readiness_status IN (
                'ready',
                'market_closed',
                'market_data_pending',
                'provider_stale'
            )
        );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;
