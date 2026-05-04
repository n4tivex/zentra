# ZENTRA — Automated IDX Equity Signal Engine

ZENTRA is an automated equity signal engine for the Indonesian stock market (IDX). It analyzes 20 tickers daily using multi-indicator technical analysis, generates BUY/EXIT signals, and delivers them to Telegram with contextual narratives.

**ZENTRA is NOT a trading bot.** It does not execute orders. It is a decision-support system.

## Quick Start

### Prerequisites
- Python 3.11+
- Supabase project (free tier)
- Telegram bot (via @BotFather)

### Local Development

```bash
# Clone and install
pip install -r requirements.txt

# Copy and fill env variables
cp .env.example .env
# Edit .env with your actual values

# Dry run (no Telegram, no DB writes)
python main.py --mode morning --dry-run

# Single ticker test
python main.py --mode morning --dry-run --ticker BBCA

# Run tests
pytest tests/ -v
```

### GitHub Actions (Production)

Set these secrets in your repo Settings → Secrets:
- `SUPABASE_URL`
- `SUPABASE_SERVICE_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `TELEGRAM_ADMIN_CHAT_ID`

Workflows run automatically:
- **Morning scan**: 08:45 WIB (Mon-Fri)
- **Closing scan**: 16:45 WIB (Mon-Fri)
- **Monthly cleanup**: 1st of each month

## Architecture

```
Data (yfinance) → Validate → Indicators (pandas-ta) → Score → Narrate → Telegram
                                                                    ↕
                                                              Supabase (persist)
```

Each ticker is processed independently. One failure does not affect other tickers.

## Tickers (Fixed)

```
BBCA, BMRI, BBRI, NCKL, RMKE, BREN, CBDK, PTRO, BRPT, BUMI,
DEWA, BRMS, ENRG, AMMN, OASA, ADMR, RAJA, SIMP, GZCO, PGEO
```

## Tech Stack

| Component | Tool |
|-----------|------|
| Language | Python 3.11+ |
| Market data | yfinance |
| Technical analysis | pandas-ta |
| Database | Supabase (PostgreSQL) |
| Notifications | Telegram Bot API |
| Scheduler | GitHub Actions |
| Logging | structlog |

## License

Internal use only.
