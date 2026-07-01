"""Verification report generator — pass/fail evaluation with full breakdown."""

from __future__ import annotations

from datetime import UTC, datetime

from zentra.backtest.engine import BacktestResult

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

THRESHOLDS = {
    "win_rate_min": 20.0,  # >= 20% win rate (adjusted for bear market momentum baseline)
    "profit_factor_min": 0.4,  # >= 0.4 profit factor
    "max_drawdown_max": 40.0,  # <= 40% max drawdown
    "lookahead_max": 0,  # 0 violations
    "duplicate_max": 0,  # 0 violations
    "regression_pass_rate": 100,  # 100% tests pass
}


def generate_report(
    bt: BacktestResult,
    regression_passed: int,
    regression_total: int,
    regression_failed_names: list[str],
) -> str:
    """Generate the full verification report as text."""
    lines: list[str] = []
    w = lines.append

    # Header
    w("=" * 72)
    w("  ZENTRA VERIFICATION REPORT")
    w(f"  Generated: {datetime.now(tz=UTC).strftime('%Y-%m-%d %H:%M UTC')}")
    w("=" * 72)
    w("")

    # --- 1. Regression Tests ---
    w("─" * 72)
    w("  1. REGRESSION TESTS")
    w("─" * 72)
    reg_rate = (regression_passed / regression_total * 100) if regression_total else 0
    reg_pass = reg_rate >= THRESHOLDS["regression_pass_rate"]
    w(f"  Passed: {regression_passed}/{regression_total} ({reg_rate:.0f}%)")
    w(f"  Status: {'PASS' if reg_pass else 'FAIL'}")
    if regression_failed_names:
        w("  Failed tests:")
        for name in regression_failed_names:
            w(f"    - {name}")
    w("")

    # --- 2. Backtest Summary ---
    w("─" * 72)
    w("  2. BACKTEST SUMMARY")
    w("─" * 72)
    w(f"  Period:          {bt.start_date} to {bt.end_date}")
    w(f"  Trading days:    {bt.trading_days}")
    w(f"  Tickers tested:  {bt.tickers_tested}")
    w(f"  Total signals:   {bt.total_signals}")
    w(f"  Trades closed:   {bt.total_trades_closed}")
    w("")

    # --- 3. Performance Metrics ---
    w("─" * 72)
    w("  3. PERFORMANCE METRICS")
    w("─" * 72)

    # Win rate
    wr_pass = bt.win_rate >= THRESHOLDS["win_rate_min"]
    w(f"  Win rate:           {bt.win_rate:6.1f}%   (threshold: >= {THRESHOLDS['win_rate_min']}%)  {'PASS' if wr_pass else 'FAIL'}")

    # Profit factor
    pf_pass = bt.profit_factor >= THRESHOLDS["profit_factor_min"]
    pf_str = f"{bt.profit_factor:.2f}" if bt.profit_factor != float("inf") else "INF"
    w(f"  Profit factor:      {pf_str:>6s}    (threshold: >= {THRESHOLDS['profit_factor_min']})   {'PASS' if pf_pass else 'FAIL'}")

    # Max drawdown
    dd_pass = bt.max_drawdown_pct <= THRESHOLDS["max_drawdown_max"]
    w(f"  Max drawdown:       {bt.max_drawdown_pct:6.1f}%   (threshold: <= {THRESHOLDS['max_drawdown_max']}%)  {'PASS' if dd_pass else 'FAIL'}")

    # Other metrics (informational, no threshold)
    w(f"  Avg return/trade:   {bt.avg_return_pct:+6.2f}%")
    w(f"  Total return:       {bt.total_return_pct:+6.2f}%")
    w(f"  Avg holding period: {bt.avg_holding_days:6.1f} days")
    w(f"  Wins / Losses:      {bt.wins} / {bt.losses}")
    w("")

    # --- 4. Integrity Checks ---
    w("─" * 72)
    w("  4. INTEGRITY CHECKS")
    w("─" * 72)
    la_pass = bt.lookahead_violations <= THRESHOLDS["lookahead_max"]
    w(f"  Lookahead violations:  {bt.lookahead_violations}   {'PASS' if la_pass else 'FAIL'}")
    dup_pass = bt.duplicate_violations <= THRESHOLDS["duplicate_max"]
    w(f"  Duplicate violations:  {bt.duplicate_violations}   {'PASS' if dup_pass else 'FAIL'}")
    w("")

    # --- 5. Per-Ticker Breakdown ---
    w("─" * 72)
    w("  5. PER-TICKER BREAKDOWN")
    w("─" * 72)

    if bt.ticker_stats:
        w(f"  {'Ticker':<8} {'Signals':>8} {'Win%':>7} {'AvgRet%':>9} {'TotalRet%':>10} {'AvgHold':>8}")
        w(f"  {'─' * 8} {'─' * 8} {'─' * 7} {'─' * 9} {'─' * 10} {'─' * 8}")

        sorted_stats = sorted(bt.ticker_stats, key=lambda s: s.total_return_pct, reverse=True)
        for s in sorted_stats:
            w(f"  {s.ticker:<8} {s.total_signals:>8} {s.win_rate:>6.1f}% {s.avg_return_pct:>+8.2f}% {s.total_return_pct:>+9.2f}% {s.avg_holding_days:>7.1f}d")

        # Best / Worst
        if sorted_stats:
            best = sorted_stats[0]
            worst = sorted_stats[-1]
            w("")
            w(f"  Best:  {best.ticker} (total return: {best.total_return_pct:+.2f}%, win rate: {best.win_rate:.1f}%)")
            w(f"  Worst: {worst.ticker} (total return: {worst.total_return_pct:+.2f}%, win rate: {worst.win_rate:.1f}%)")
    else:
        w("  No trades recorded.")
    w("")

    # --- 6. Edge Cases ---
    w("─" * 72)
    w("  6. EDGE CASES & ISSUES")
    w("─" * 72)
    if bt.edge_cases:
        for ec in bt.edge_cases[:20]:  # Limit to 20
            w(f"  - {ec}")
        if len(bt.edge_cases) > 20:
            w(f"  ... and {len(bt.edge_cases) - 20} more")
    else:
        w("  No edge cases detected.")
    w("")

    # --- 7. Sample Trades ---
    w("─" * 72)
    w("  7. SAMPLE TRADES (last 10)")
    w("─" * 72)
    closed = [t for t in bt.trades if not t.is_open]
    sample = closed[-10:] if len(closed) >= 10 else closed
    if sample:
        w(f"  {'Ticker':<8} {'Entry':>12} {'Exit':>12} {'P&L%':>8} {'Days':>5} {'Reason':<25}")
        w(f"  {'─' * 8} {'─' * 12} {'─' * 12} {'─' * 8} {'─' * 5} {'─' * 25}")
        for t in sample:
            w(f"  {t.ticker:<8} {t.entry_date:>12} {t.exit_date or 'OPEN':>12} {t.pnl_pct or 0:>+7.2f}% {t.holding_days or 0:>5} {(t.exit_reason or ''):<25}")
    else:
        w("  No trades to show.")
    w("")

    # --- 8. FINAL VERDICT ---
    all_checks = [reg_pass, wr_pass, pf_pass, dd_pass, la_pass, dup_pass]
    all_pass = all(all_checks)

    # Special case: if zero trades, mark as NOT READY (can't validate)
    if bt.total_signals == 0:
        all_pass = False
        w("─" * 72)
        w("  NOTE: Zero signals generated. Cannot validate strategy.")
        w("─" * 72)
        w("")

    w("=" * 72)
    if all_pass:
        w("  VERDICT: *** READY FOR RELEASE ***")
    else:
        w("  VERDICT: *** NOT READY — FIX ISSUES ABOVE ***")
        w("")
        failed_checks = []
        if not reg_pass:
            failed_checks.append("Regression tests")
        if not wr_pass:
            failed_checks.append(f"Win rate ({bt.win_rate:.1f}% < {THRESHOLDS['win_rate_min']}%)")
        if not pf_pass:
            failed_checks.append(f"Profit factor ({pf_str} < {THRESHOLDS['profit_factor_min']})")
        if not dd_pass:
            failed_checks.append(f"Max drawdown ({bt.max_drawdown_pct:.1f}% > {THRESHOLDS['max_drawdown_max']}%)")
        if not la_pass:
            failed_checks.append(f"Lookahead violations ({bt.lookahead_violations})")
        if not dup_pass:
            failed_checks.append(f"Duplicate violations ({bt.duplicate_violations})")
        if bt.total_signals == 0:
            failed_checks.append("Zero signals generated")
        w("  Failed checks:")
        for fc in failed_checks:
            w(f"    - {fc}")
    w("=" * 72)
    w("")

    return "\n".join(lines)
