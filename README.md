# ZENTRA Automated IDX Equity Signal Engine

ZENTRA is an automated signal engine for the Indonesia Stock Exchange (IDX). It scans a fixed universe of 20 IDX tickers each trading day, computes technical indicators, generates BUY/WATCH/EXIT signals with scored rationale, persists state to Supabase, and delivers structured reports via Telegram.

ZENTRA is a decision-support system. It does not execute trades, manage portfolios, or interface with any brokerage.

## Features

- **Scheduled daily scans.** Morning scan (08:45 WIB) and closing scan (16:45 WIB) cover the full ticker universe.
- **Multi-indicator scoring.** RSI 14 crossover is the primary BUY trigger, confirmed by MACD 12/26/9 alignment and EMA 9/21 trend slope. Signals are scored from 0-100 with confluence counting.
- **Risk management.** Stop-loss distance capped at 5% using ATR-based placement. Minimum risk-reward ratio of 1.5:1. Take-profit set at 2.5x ATR.
- **Volume confirmation.** Five-day average volume comparison to filter low-liquidity signals.
- **IDX calendar awareness.** Skips weekends, official IDX holidays, and supports emergency override dates. No phantom scans on nontrading days.
- **Supabase persistence.** Signals, run logs, run locks, and cached OHLCV data are stored in Supabase for audit trail and continuity.
- **Telegram delivery.** Formatted signal summaries delivered to a target chat. Admin alerts sent on failures, partial runs, or anomalies.
- **Weekly performance reports.** Aggregates open and closed signals with P&L summaries.
- **Preflight checks.** Validate environment variables, calendar data, Supabase connectivity, and Telegram API before production runs.

## Quick Start

### Prerequisites

- Python 3.11+
- A Supabase project (see Supabase Migration section)
- A Telegram bot token and chat IDs

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Run a Scan Locally

```bash
# Morning scan with dry-run (no DB writes, no Telegram)
python main.py --mode morning --dry-run

# Closing scan
python main.py --mode closing --dry-run

# Single ticker (useful for testing)
python main.py --mode morning --dry-run --ticker BBCA

# Full run (requires Supabase and Telegram credentials in .env)
python main.py --mode morning
```

### Run Tests

```bash
pytest tests -q
```

### Run Preflight Checks

```bash
python scripts/preflight.py --skip-network
python scripts/preflight.py
```

The full preflight requires valid Supabase and Telegram environment variables.

## Production Scheduling

Production scans are triggered by [cronjob.org](https://cronjob.org) via GitHub `repository_dispatch` events. Both triggers must remain active.

| Scan     | WIB Time | GitHub Dispatch Event     | CLI Mode |
|----------|----------|---------------------------|----------|
| Morning  | 08:45    | `trigger-morning-scan`    | `morning`|
| Closing  | 16:45    | `trigger-closing-scan`    | `closing` |

The corresponding GitHub Actions workflows are:

- `.github/workflows/morning_scan.yml`
- `.github/workflows/closing_scan.yml`
- `.github/workflows/weekly_report.yml`
- `.github/workflows/monthly_cleanup.yml`
- `.github/workflows/calendar_maintenance.yml`

## Required Secrets

Set these as GitHub Actions secrets or in your `.env` file:

| Secret                    | Description                            |
|---------------------------|----------------------------------------|
| `SUPABASE_URL`            | Supabase project URL                   |
| `SUPABASE_SERVICE_KEY`    | Supabase service role key (not anon)   |
| `TELEGRAM_BOT_TOKEN`      | Telegram bot token                     |
| `TELEGRAM_CHAT_ID`        | Target chat ID for signal delivery     |
| `TELEGRAM_ADMIN_CHAT_ID`  | Admin chat ID for failure alerts       |

## Tickers

ZENTRA scans a fixed universe of 20 IDX tickers:

| Ticker | Company Name                        |
|--------|-------------------------------------|
| BBCA   | Bank Central Asia                   |
| BMRI   | Bank Mandiri (Persero)              |
| BBRI   | Bank Rakyat Indonesia (Persero)     |
| NCKL   | Trimegah Bangun Persada             |
| RMKE   | RMK Energy                          |
| BREN   | Barito Renewables Energy            |
| CBDK   | Bangun Kosambi Sukses               |
| PTRO   | Petrosea                            |
| BRPT   | Barito Pacific                      |
| BUMI   | Bumi Resources                      |
| DEWA   | Darma Henwa                         |
| BRMS   | Bumi Resources Minerals             |
| ENRG   | Energi Mega Persada                 |
| AMMN   | Amman Mineral Internasional         |
| OASA   | Maharaksa Biru Energi               |
| ADMR   | Alamtri Minerals Indonesia          |
| RAJA   | Rukun Raharja                       |
| SIMP   | Salim Ivomas Pratama                |
| GZCO   | Gozco Plantations                   |
| PGEO   | Pertamina Geothermal Energy         |

The ticker list and name mappings are defined in `zentra/config.py`.

## Project Structure

```
main.py                          CLI entrypoint
pyproject.toml                   Project metadata and tool config
requirements.txt                 Pinned Python dependencies
zentra/
  __init__.py
  config.py                      Ticker list, thresholds, data structures
  exceptions.py                  Custom exception types
  market_calendar.py             IDX trading-day logic
  market_calendar.json           Versioned IDX holiday calendar
  orchestrator.py                Top-level scan orchestrator
  runtime.py                     Runtime context and helpers
  analysis/
    indicators.py                RSI, MACD, EMA, Bollinger Bands, ATR
    risk.py                      Stop-loss, take-profit, risk-reward calc
    scorer.py                    Multi-factor signal scoring engine
  backtest/
    engine.py                    Backtesting engine
    report.py                    Backtest report generation
  data/
    fetcher.py                   yfinance OHLCV data fetching with retries
    schema.py                    DataFrame schema contracts
    validator.py                 Input data validation
  db/
    client.py                    Supabase client factory
    ohlcv_repo.py                OHLCV cache repository
    run_locks_repo.py            Run lock management
    run_logs_repo.py             Run log persistence
    signals_repo.py              Signal CRUD operations
    utils.py                     Supabase query helpers
  narrative/
    blocks.py                    Narrative template blocks
    generator.py                 Signal narrative generation
  telegram/
    formatter.py                 Message formatting for Telegram
    sender.py                    Telegram API delivery
scripts/
  preflight.py                   Production preflight checks
  check_market_calendar.py       Calendar validation utility
  backtest.py                    Backtest runner script
  cleanup.py                     Data cleanup utility
  tune.py                        Parameter tuning
  verify.py                      Verification script
tests/
  conftest.py                    Shared test fixtures
  fixtures/                      Test data files
  test_integration.py            End-to-end integration tests
  test_market_calendar.py        Calendar logic tests
  test_narrative.py              Narrative generation tests
  test_p0_regressions.py         P0 regression test suite
  test_production_hardening.py   Production hardening tests
  test_risk.py                   Risk calculation tests
  test_scorer.py                 Scoring logic tests
  test_strategy_changes.py       Strategy change tests
  test_telegram_formatter.py     Telegram formatting tests
  test_validator.py              Data validation tests
  test_weekly_report.py          Weekly report tests
supabase/migrations/
  20260512_0001_zentra_p0.sql
  20260512_0002_zentra_p1_p2.sql
  20260518_0003_production_hardening.sql
  20260609_0005_remove_midday_run_mode.sql
.github/workflows/
  morning_scan.yml               Morning scan workflow
  closing_scan.yml               Closing scan workflow
  weekly_report.yml              Weekly performance report
  monthly_cleanup.yml            Monthly data cleanup
  calendar_maintenance.yml       Calendar update workflow
docs/
  runbook.md                     Operational runbook
```

## Supabase Migrations

Apply migrations to your Supabase project in order. Each migration builds on the previous one.

1. `20260512_0001_zentra_p0.sql` - Core schema: signals, run_logs, run_locks tables
2. `20260512_0002_zentra_p1_p2.sql` - OHLCV cache, narrative columns, index additions
3. `20260518_0003_production_hardening.sql` - RLS policies, constraints, production hardening
4. `20260609_0005_remove_midday_run_mode.sql` - Schema cleanup after run mode removal

## Operations

Refer to [docs/runbook.md](docs/runbook.md) for:

- IDX holiday handling and emergency overrides
- Market data pending or stale behavior
- Database recovery procedures
- Duplicate trigger prevention and handling
- Telegram delivery failures and retries
- cronjob.org setup and maintenance notes
