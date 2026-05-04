"""Full verification pipeline — regression tests + backtest + combined report.

Usage:
    python scripts/verify.py --months 6 --output reports/verification_report.txt

Exit codes:
    0 = READY
    1 = NOT READY
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import re

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run_regression_tests() -> tuple[int, int, list[str]]:
    """Run pytest and return (passed, total, failed_names)."""
    print("\n" + "=" * 50)
    print("  STEP 1: Running regression tests...")
    print("=" * 50)

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )

    print(result.stdout)
    if result.stderr:
        print(result.stderr)

    # Parse results from pytest output
    passed = 0
    failed = 0
    failed_names: list[str] = []

    # Match "X passed" and "Y failed" from summary line
    summary_match = re.search(r"(\d+) passed", result.stdout)
    if summary_match:
        passed = int(summary_match.group(1))

    failed_match = re.search(r"(\d+) failed", result.stdout)
    if failed_match:
        failed = int(failed_match.group(1))

    # Extract failed test names
    for line in result.stdout.splitlines():
        if line.startswith("FAILED "):
            name = line.replace("FAILED ", "").split(" ")[0]
            failed_names.append(name)

    total = passed + failed
    return passed, total, failed_names


def run_backtest(months: int, tickers: list[str] | None = None):
    """Run the backtest engine."""
    print("\n" + "=" * 50)
    print(f"  STEP 2: Running backtest ({months} months)...")
    print("=" * 50)

    from zentra.backtest.engine import BacktestEngine
    from zentra.config import TICKERS

    tickers = tickers or list(TICKERS)
    engine = BacktestEngine()
    return engine.run(tickers=tickers, months=months)


def main() -> None:
    parser = argparse.ArgumentParser(description="ZENTRA Full Verification Pipeline")
    parser.add_argument("--months", type=int, default=6, help="Months of backtest history")
    parser.add_argument("--output", type=str, default="reports/verification_report.txt", help="Output file")
    parser.add_argument("--tickers", type=str, nargs="*", help="Specific tickers (default: all 20)")
    parser.add_argument("--skip-backtest", action="store_true", help="Skip backtest, run tests only")
    args = parser.parse_args()

    print("=" * 50)
    print("  ZENTRA VERIFICATION PIPELINE")
    print("=" * 50)

    # Step 1: Regression tests
    reg_passed, reg_total, reg_failed = run_regression_tests()
    print(f"\nRegression: {reg_passed}/{reg_total} passed")

    # Step 2: Backtest
    if args.skip_backtest:
        print("\nSkipping backtest (--skip-backtest)")
        from zentra.backtest.engine import BacktestResult
        bt_result = BacktestResult(
            start_date="N/A", end_date="N/A", tickers_tested=0, trading_days=0,
        )
    else:
        bt_result = run_backtest(months=args.months, tickers=args.tickers)

    # Step 3: Generate combined report
    print("\n" + "=" * 50)
    print("  STEP 3: Generating verification report...")
    print("=" * 50)

    from zentra.backtest.report import generate_report, THRESHOLDS

    report = generate_report(
        bt=bt_result,
        regression_passed=reg_passed,
        regression_total=reg_total,
        regression_failed_names=reg_failed,
    )

    # Write to file
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(report)

    # Print report to console (ASCII-safe for Windows)
    safe_report = report.encode("ascii", errors="replace").decode("ascii")
    print("\n" + safe_report)
    print(f"Report saved to: {args.output}")

    # Determine exit code
    all_pass = True
    if reg_passed < reg_total:
        all_pass = False
    if not args.skip_backtest:
        if bt_result.win_rate < THRESHOLDS["win_rate_min"]:
            all_pass = False
        if bt_result.profit_factor < THRESHOLDS["profit_factor_min"]:
            all_pass = False
        if bt_result.max_drawdown_pct > THRESHOLDS["max_drawdown_max"]:
            all_pass = False
        if bt_result.lookahead_violations > THRESHOLDS["lookahead_max"]:
            all_pass = False
        if bt_result.duplicate_violations > THRESHOLDS["duplicate_max"]:
            all_pass = False
        if bt_result.total_signals == 0:
            all_pass = False

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
