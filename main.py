"""ZENTRA — Automated IDX Equity Signal Engine.

Entrypoint per PRD §11.2.

CLI Arguments
-------------
--mode {morning,closing,manual,weekly}
    Scan mode. Default: morning.
    - morning: Scheduled scan at 08:45 WIB. Covers full ticker universe,
      generates BUY/WATCH/EXIT signals with scored rationale.
    - closing: Scheduled scan at 16:45 WIB. Covers full ticker universe
      with end-of-day indicator assessment.
    - manual: On-demand scan with full processing pipeline. Same logic
      as morning/closing but not tied to a scheduled window.
    - weekly: Performance report only. Aggregates open and closed signals
      with P&L summaries. Does NOT run individual ticker scans.

--ticker TICKER
    Single ticker override (e.g. BBCA, BMRI). When provided, the scan
    processes only this ticker. Useful for testing, debugging, or ad-hoc
    signal checks without running the full universe of 20 IDX tickers.

--dry-run
    Dry-run mode. When set, the pipeline runs normally but DOES NOT
    persist results to Supabase or deliver messages via Telegram.
    Useful for local testing and CI validation.

Usage Examples
--------------
    python main.py --mode morning --dry-run
    python main.py --mode closing --ticker BBCA --dry-run
    python main.py --mode morning
    python main.py --mode weekly
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from dotenv import load_dotenv


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ZENTRA Automated IDX Equity Signal Engine — scan, score, and report on "
        "a fixed universe of 20 IDX tickers using multi-indicator technical analysis.",
        epilog=(
            "Examples:\n"
            "  python main.py --mode morning --dry-run        Morning scan, no persistence\n"
            "  python main.py --mode closing --ticker BBCA     Closing scan, single ticker only\n"
            "  python main.py --mode morning                   Full morning scan (requires .env)\n"
            "  python main.py --mode weekly                    Weekly P&L performance report\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--mode",
        choices=["morning", "closing", "manual", "weekly"],
        default="morning",
        help=(
            "Scan mode (default: morning). "
            "morning=08:45 WIB daily scan, closing=16:45 WIB daily scan, "
            "manual=on-demand full pipeline, weekly=aggregated P&L report"
        ),
    )
    parser.add_argument(
        "--ticker",
        metavar="TICKER",
        help=("Single ticker to scan (e.g. BBCA, BMRI). Overrides the full 20-ticker universe. Useful for targeted testing or debugging a specific symbol."),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=("Simulate the run without side effects. Signals are computed and printed but NOT persisted to Supabase or delivered via Telegram."),
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
