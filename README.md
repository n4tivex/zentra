# ZENTRA — Automated IDX Equity Signal Engine

ZENTRA is an automated equity signal engine for the Indonesian stock market (IDX). It analyzes 20 fixed IDX tickers daily using multi-indicator technical analysis, generates BUY/EXIT/WATCH signals, and delivers them to Telegram with contextual narratives.

**ZENTRA is NOT a trading bot.** It does not execute orders. It is a **decision-support system**.

---

## Features

- **Daily automated scans** — Morning (08:45 WIB) and closing (16:45 WIB) scans via GitHub Actions
- **Multi-indicator scoring** — Combines momentum, trend, volume, and volatility indicators with configurable weights
- **Market calendar awareness** — Versioned IDX holiday calendar with weekend + official holiday detection
- **Run idempotency** — Lock-based duplicate run prevention
- **Telegram delivery** — Structured BUY/EXIT/WATCH notifications with narrative explanations
- **Weekly performance reports** — Automated recap every Friday
- **Operational runbook** — Documented procedures for market holidays, partial data, DB failures
- **Preflight verification** — Validates environment, calendar, Supabase, and Telegram before production runs
- **Telemetry** — Detailed run logs with data coverage, fetch statistics, and failure classification

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   GitHub Actions                         │
│  (scheduled: 08:45 / 16:45 WIB, Mon-Fri)                │
└───────────────┬─────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────┐
│                    main.py                               │
│         CLI entrypoint (mode, ticker, dry-run)           │
└───────────────┬─────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────┐
│              ZENTRAOrchestrator                          │
│  ┌─────────┐  ┌──────────┐  ┌────────┐  ┌───────────┐  │
│  │ Market  │→│  Data   │→│  Val-  │→│  Scorer  │  │
│  │Calendar │  │ Fetcher │  │ idator │  │(indicators)│  │
│  └─────────┘  └──────────┘  └────────┘  └───────────┘  │
│                              │                          │
│                              ▼                          │
│  ┌──────────┐  ┌────────┐  ┌────────────┐              │
│  │ Telegram │←│ Narra- │←│  Supabase  │              │
│  │  Sender  │  │  tive  │  │  (persist) │              │
│  └──────────┘  └────────┘  └────────────┘              │
└─────────────────────────────────────────────────────────┘
```

- Each ticker is processed independently — one failure does not affect others
- Market calendar (weekend + official holidays) gates all scans
- Run locks prevent duplicate execution from overlapping cron triggers
- Coverage telemetry tracks fetched, cached, missing, and failed tickers

---

## Quick Start

### Prerequisites

- Python 3.11+
- Supabase project (free tier) with PostgreSQL
- Telegram bot token (via [@BotFather](https://t.me/botfather))

### Setup

```bash
# Clone and install
git clone <repo>
cd zentra
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your Supabase and Telegram credentials
```

### Run Locally

```bash
# Dry run (no Telegram, no DB writes)
python main.py --mode morning --dry-run

# Single ticker test
python main.py --mode morning --dry-run --ticker BBCA

# Closing scan test
python main.py --mode closing --dry-run

# Run tests
pytest tests/ -v
```

### Preflight Check

Before first production run, verify everything is configured:

```bash
# Quick offline check (env vars, calendar format, module loading)
python scripts/preflight.py --skip-network

# Full check (includes Supabase reachability + Telegram token validation)
python scripts/preflight.py
```

Expected output:
```
OK env: required variables present
OK calendar_json: valid
OK calendar_load: calendar loaded
OK supabase: reachable
OK telegram: reachable
```

---

## Project Structure

```
zentra/
├── main.py                          # CLI entrypoint
├── pyproject.toml                   # Project configuration
├── requirements.txt                 # Python dependencies
├── .env.example                     # Environment variable template
│
├── zentra/                          # Core application package
│   ├── orchestrator.py              # Scan orchestration & pipeline
│   ├── config.py                    # Environment configuration
│   ├── runtime.py                   # Runtime helpers (timezone)
│   ├── exceptions.py                # Domain exceptions
│   ├── market_calendar.py           # Trading calendar (weekend + holidays)
│   ├── market_calendar.json         # Versioned IDX holiday calendar source
│   │
│   ├── analysis/                    # Signal generation
│   │   ├── scorer.py                # Multi-indicator scoring matrix
│   │   ├── indicators.py            # Technical indicator calculations
│   │   └── risk.py                  # Risk metric computations
│   │
│   ├── data/                        # Market data layer
│   │   ├── fetcher.py               # yfinance data fetching + caching
│   │   ├── validator.py             # OHLCV data validation
│   │   └── schema.py                # Data schema contracts
│   │
│   ├── db/                          # Supabase database layer
│   │   ├── client.py                # Supabase client factory
│   │   ├── run_logs_repo.py         # Run log persistence
│   │   ├── run_locks_repo.py        # Execution lock management
│   │   ├── signals_repo.py          # Signal CRUD operations
│   │   ├── ohlcv_repo.py            # Cached OHLCV data
│   │   └── utils.py                 # DB helpers
│   │
│   ├── narrative/                   # Human-readable signal narrative
│   │   ├── generator.py             # Narrative generation
│   │   └── blocks.py                # Message template blocks
│   │
│   ├── telegram/                    # Notification layer
│   │   ├── sender.py                # Telegram message dispatch
│   │   └── formatter.py             # Message formatting (MarkdownV2)
│   │
│   └── backtest/                    # Historical backtesting
│       ├── engine.py                # Backtest execution engine
│       └── report.py                # Backtest report generation
│
├── scripts/                         # Utility scripts
│   ├── preflight.py                 # Production preflight verifier
│   ├── check_market_calendar.py     # Calendar source validator
│   ├── veriy.py                     # Data verification
│   ├── tune.py                      # Parameter tuning
│   ├── cleanup.py                   # Data cleanup
│   └── backtest.py                  # Backtest runner
│
├── tests/                           # Test suite
│   ├── conftest.py                  # Test fixtures & configuration
│   ├── test_integration.py          # End-to-end integration tests
│   ├── test_scorer.py               # Scoring logic tests
│   ├── test_narrative.py            # Narrative generation tests
│   ├── test_telegram_formatter.py   # Message formatting tests
│   ├── test_validator.py            # Data validation tests
│   ├── test_market_calendar.py      # Calendar logic tests
│   ├── test_production_hardening.py # Production hardening tests
│   ├── test_risk.py                 # Risk metric tests
│   ├── test_p0_regressions.py       # Regression tests
│   └── fixtures/                    # Test data (CSV)
│
├── supabase/
│   └── migrations/                  # Database migrations
│       ├── 20260512_0001_zentra_p0.sql
│       ├── 20260512_0002_zentra_p1_p2.sql
│       └── 20260518_0003_production_hardening.sql
│
├── docs/
│   └── runbook.md                   # Operational runbook
│
└── .github/
    └── workflows/                   # GitHub Actions automation
        ├── morning_scan.yml         # 08:45 WIB daily
        ├── closing_scan.yml         # 16:45 WIB daily
        ├── monthly_cleanup.yml      # 1st of each month
        ├── weekly_report.yml        # Every Friday
        └── calendar_maintenance.yml # Monthly calendar validation
```

---

## GitHub Actions (Production)

### Required Repository Secrets

Set these in your repo **Settings → Secrets and variables → Actions**:

| Secret | Description |
|--------|-------------|
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_SERVICE_KEY` | Service role key (full API access) |
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Target chat/group ID for signals |
| `TELEGRAM_ADMIN_CHAT_ID` | Admin chat for failure alerts |

### Automated Workflows

| Workflow | Schedule | Description |
|----------|----------|-------------|
| **Morning scan** | Mon–Fri 08:45 WIB | Daily opening scan with previous close data |
| **Closing scan** | Mon–Fri 16:45 WIB | End-of-day scan (after market close) |
| **Weekly report** | Fri 17:00 WIB | Performance summary for the week |
| **Monthly cleanup** | 1st of month | Purge old cache data |
| **Calendar maintenance** | 1st of month | Validate market calendar source |

---

## Tickers (Fixed)

The following 20 IDX equities are scanned daily:

```
BBCA  BMRI  BBRI  NCKL  RMKE  BREN  CBDK  PTRO  BRPT  BUMI
DEWA  BRMS  ENRG  AMMN  OASA  ADMR  RAJA  SIMP  GZCO  PGEO
```

---

## Market Calendar

ZENTRA uses a **versioned JSON calendar** (`zentra/market_calendar.json`) sourced from the official IDX holiday schedule. This replaces fragile gap-based holiday heuristics.

### Closure Detection

```
weekend (Sat/Sun)
  └── is_weekend() → True → closed
official_holiday (from JSON calendar)
  └── is_closed() → True → closed
calendar_override (env IDX_MARKET_HOLIDAYS)
  └── emergency override for same-day closure
```

### Calendar Maintenance

- Update `zentra/market_calendar.json` with new IDX holiday announcements
- Validate with `python scripts/check_market_calendar.py --require-next-year`
- Calendar updates are tracked via a monthly CI workflow

---

## Tech Stack

| Component | Tool |
|-----------|------|
| Language | Python 3.11+ |
| Market data | yfinance |
| Technical analysis | pandas-ta (RSI, MACD, BB, SMA, ATR, volume) |
| Database | Supabase (PostgreSQL 17) |
| Notifications | python-telegram-bot (MarkdownV2) |
| Scheduler | GitHub Actions |
| Logging | structlog (structured JSON) |
| Testing | pytest + pytest-asyncio |
| Code quality | Ruff (linter + formatter) |
| Type checking | mypy (strict mode) |

---

## Operations

Refer to the [Operational Runbook](docs/runbook.md) for:

- **Market holiday handling** — How the calendar gates scans
- **Partial data recovery** — Handling incomplete market data
- **Database failures** — Recovery procedures
- **Duplicate trigger handling** — Run lock mechanics
- **Telegram failures** — Message delivery fallback

### Preflight

Always run preflight before deploying changes:

```bash
python scripts/preflight.py
```

---

## License

Internal use only.
