"""Backtest CLI — run backtest and output report.

Usage:
    python scripts/backtest.py --months 6 --output reports/backtest_report.txt
"""

from __future__ import annotations

import argparse
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zentra.backtest.engine import BacktestEngine
from zentra.backtest.report import generate_report
from zentra.config import TICKERS


def main() -> None:
    parser = argparse.ArgumentParser(description="ZENTRA Backtest")
    parser.add_argument("--months", type=int, default=6, help="Months of history to test")
    parser.add_argument("--output", type=str, default="reports/backtest_report.txt", help="Output file")
    parser.add_argument("--tickers", type=str, nargs="*", help="Specific tickers (default: all 20)")
    args = parser.parse_args()

    tickers = args.tickers if args.tickers else list(TICKERS)

    print(f"ZENTRA Backtest — {args.months} months, {len(tickers)} tickers")
    print("Fetching historical data...")

    engine = BacktestEngine()
    result = engine.run(tickers=tickers, months=args.months)

    report = generate_report(
        bt=result,
        regression_passed=0,
        regression_total=0,
        regression_failed_names=[],
    )

    # Write to file
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\nReport saved to: {args.output}")
    print(f"Signals: {result.total_signals}, Win rate: {result.win_rate:.1f}%, "
          f"Profit factor: {result.profit_factor:.2f}")


if __name__ == "__main__":
    main()
