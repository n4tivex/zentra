"""ZENTRA — Automated IDX Equity Signal Engine.

Entrypoint per PRD §11.2.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from dotenv import load_dotenv


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ZENTRA Trading Signal Engine")
    parser.add_argument(
        "--mode",
        choices=["morning", "closing", "manual", "weekly"],
        default="morning",
        help="Scan mode (weekly = performance report only)",
    )
    parser.add_argument(
        "--ticker",
        help="Scan single ticker only (for testing)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without sending to Telegram or writing to DB",
    )
    return parser.parse_args()


async def main() -> None:
    load_dotenv()

    args = parse_args()

    # Import after dotenv so env vars are available
    from zentra.orchestrator import ZENTRAOrchestrator

    orchestrator = ZENTRAOrchestrator(mode=args.mode, dry_run=args.dry_run)

    if args.mode == "weekly":
        success = await orchestrator.run_weekly_report()
    else:
        success = await orchestrator.run(single_ticker=args.ticker)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
