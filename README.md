# ZENTRA - Automated IDX Equity Signal Engine

ZENTRA is an automated IDX equity signal engine. It analyzes 20 fixed IDX tickers, generates BUY/WATCH/EXIT signals, persists run state to Supabase, and sends structured Telegram notifications.

ZENTRA is not a trading bot. It is a decision-support system and does not execute orders.

## Features

- Daily automated scans at 08:45 and 16:45 WIB.
- RSI crossing is the primary BUY trigger, with MACD as confirmation.
- EMA 9/21 trend scoring and 5-day volume confirmation.
- Stop-loss distance is capped at 5%.
- IDX calendar awareness for weekends, official holidays, and emergency overrides.
- Supabase persistence for signals, run logs, run locks, and cached OHLCV data.
- Telegram delivery with admin failure alerts.
- Production preflight checks for env, calendar, Supabase, and Telegram.

## Run Locally

```bash
pip install -r requirements.txt

python main.py --mode morning --dry-run
python main.py --mode closing --dry-run
python main.py --mode morning --dry-run --ticker BBCA
```

Run verification:

```bash
python -m pytest tests -q
python scripts/preflight.py --skip-network
python scripts/preflight.py
```

The full preflight requires valid Supabase and Telegram environment variables.

## Production Scheduling

Production scan workflows are triggered by cronjob.org through GitHub `repository_dispatch` events. Keep both daily scan triggers active:

| Scan | WIB time | GitHub dispatch event | CLI mode |
|------|----------|-----------------------|----------|
| Morning | 08:45 | `trigger-morning-scan` | `morning` |
| Closing | 16:45 | `trigger-closing-scan` | `closing` |

## Required Secrets

Set these in GitHub Actions secrets:

| Secret | Description |
|--------|-------------|
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_SERVICE_KEY` | Supabase service role key |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token |
| `TELEGRAM_CHAT_ID` | Signal target chat ID |
| `TELEGRAM_ADMIN_CHAT_ID` | Admin alert chat ID |

## Tickers

The fixed ticker universe:

```text
BBCA  BMRI  BBRI  NCKL  RMKE  BREN  CBDK  PTRO  BRPT  BUMI
DEWA  BRMS  ENRG  AMMN  OASA  ADMR  RAJA  SIMP  GZCO  PGEO
```

## Project Structure

```text
main.py                         CLI entrypoint
zentra/
  analysis/                     Indicators, risk, and scoring
  backtest/                     Backtest runner and report
  data/                         Market data fetch/validation/schema
  db/                           Supabase repositories
  narrative/                    Signal narrative generation
  telegram/                     Telegram formatting and delivery
  config.py                     Runtime config and ticker names
  market_calendar.py            IDX trading-day logic
  market_calendar.json          Versioned IDX holiday calendar
scripts/
  preflight.py                  Production preflight checks
  check_market_calendar.py      Calendar validation
supabase/migrations/
  20260512_0001_zentra_p0.sql
  20260512_0002_zentra_p1_p2.sql
  20260518_0003_production_hardening.sql
  20260609_0005_remove_midday_run_mode.sql
.github/workflows/
  morning_scan.yml
  morning_scan.yml
  closing_scan.yml
  weekly_report.yml
  monthly_cleanup.yml
  calendar_maintenance.yml
docs/runbook.md                 Operational runbook
```

## Supabase Migration

Apply migrations in order before deploying to production.

## Operations

Read [docs/runbook.md](docs/runbook.md) for market holiday handling, market data pending behavior, DB recovery, duplicate trigger handling, Telegram failures, and cronjob.org setup notes.
