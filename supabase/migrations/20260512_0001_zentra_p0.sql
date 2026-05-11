-- ZENTRA P0 schema guards
-- Idempotent migration for Supabase/Postgres.

create extension if not exists pgcrypto;

create table if not exists public.run_logs (
    id uuid primary key default gen_random_uuid(),
    run_mode text not null,
    status text not null,
    github_run_id text not null default 'local',
    duration_seconds numeric,
    tickers_scanned integer,
    tickers_failed text[],
    signals_generated integer,
    buy_signals integer,
    exit_signals integer,
    watch_signals integer,
    telegram_sent integer,
    telegram_failed integer,
    error_message text,
    created_at timestamptz not null default now(),
    completed_at timestamptz
);

create index if not exists idx_run_logs_status_created_at
    on public.run_logs (status, created_at desc);

create table if not exists public.ohlcv_cache (
    id uuid primary key default gen_random_uuid(),
    ticker text not null,
    trade_date date not null,
    open numeric not null,
    high numeric not null,
    low numeric not null,
    close numeric not null,
    volume bigint not null default 0,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create unique index if not exists uq_ohlcv_cache_ticker_trade_date
    on public.ohlcv_cache (ticker, trade_date);

create index if not exists idx_ohlcv_cache_ticker_trade_date_desc
    on public.ohlcv_cache (ticker, trade_date desc);

create table if not exists public.signals (
    id uuid primary key default gen_random_uuid(),
    ticker text not null,
    signal_type text not null,
    signal_strength text not null,
    score integer not null,
    confluence_count integer not null,
    entry_price numeric,
    stop_loss numeric,
    take_profit numeric,
    risk_pct numeric,
    reward_pct numeric,
    rr_ratio numeric,
    narrative_text text,
    indicator_snapshot jsonb not null default '{}'::jsonb,
    status text not null,
    run_id uuid references public.run_logs(id) on delete set null,
    exit_price numeric,
    exit_pct numeric,
    created_at timestamptz not null default now(),
    closed_at timestamptz
);

create unique index if not exists uq_signals_one_active_per_ticker
    on public.signals (ticker)
    where status = 'ACTIVE';

create index if not exists idx_signals_ticker_status_created_at
    on public.signals (ticker, status, created_at desc);

create index if not exists idx_signals_status_created_at
    on public.signals (status, created_at desc);

-- Optional safety trigger: keep updated_at current on cache rows.
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists trg_ohlcv_cache_updated_at on public.ohlcv_cache;
create trigger trg_ohlcv_cache_updated_at
before update on public.ohlcv_cache
for each row execute function public.set_updated_at();
