"""Production preflight checks for ZENTRA.

Checks environment, calendar source, Supabase reachability, and Telegram
credentials. Use --skip-network for CI or local offline validation.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv
from telegram import Bot

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.check_market_calendar import validate_calendar  # noqa: E402
from zentra.config import get_env, validate_env  # noqa: E402
from zentra.db.client import get_client  # noqa: E402
from zentra.exceptions import ConfigurationError  # noqa: E402
from zentra.market_calendar import BUNDLED_CALENDAR_PATH, MarketCalendar  # noqa: E402


async def _check_telegram() -> None:
    bot = Bot(token=get_env("TELEGRAM_BOT_TOKEN"))
    await bot.get_me()


def _check_supabase() -> None:
    client = get_client()
    client.table("run_logs").select("id").limit(1).execute()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run ZENTRA production preflight checks")
    parser.add_argument("--skip-network", action="store_true", help="Skip Supabase and Telegram probes")
    args = parser.parse_args()

    load_dotenv()
    checks: list[tuple[str, bool, str]] = []

    try:
        validate_env()
        checks.append(("env", True, "required variables present"))
    except ConfigurationError as e:
        checks.append(("env", False, str(e)))

    calendar_errors = validate_calendar(BUNDLED_CALENDAR_PATH)
    checks.append(("calendar_json", not calendar_errors, "; ".join(calendar_errors) or "valid"))

    try:
        MarketCalendar.from_env()
        checks.append(("calendar_load", True, "calendar loaded"))
    except Exception as e:
        checks.append(("calendar_load", False, str(e)))

    if not args.skip_network:
        try:
            _check_supabase()
            checks.append(("supabase", True, "reachable"))
        except Exception as e:
            checks.append(("supabase", False, str(e)))

        try:
            asyncio.run(_check_telegram())
            checks.append(("telegram", True, "reachable"))
        except Exception as e:
            checks.append(("telegram", False, str(e)))

    for name, ok, detail in checks:
        status = "OK" if ok else "FAIL"
        print(f"{status} {name}: {detail}")

    return 0 if all(ok for _, ok, _ in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
