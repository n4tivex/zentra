"""Parameter sweep tuning script — finds the best config combination.

Tests multiple parameter combos against historical data and picks the best.
Fetches data once, then runs all combos on the same dataset.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zentra.backtest.engine import BacktestEngine, BacktestResult
from zentra.config import SCORING, TICKERS


@dataclass
class TuneCombo:
    name: str
    buy_threshold: int
    min_confluence: int
    sl_atr: float
    tp_atr: float


COMBOS = [
    TuneCombo("A_baseline",      buy_threshold=70, min_confluence=3, sl_atr=1.5, tp_atr=2.5),
    TuneCombo("C_buy60_sl1.5_tp2.5", buy_threshold=60, min_confluence=3, sl_atr=1.5, tp_atr=2.5),
    TuneCombo("C_buy60_sl1.5_tp3.0", buy_threshold=60, min_confluence=3, sl_atr=1.5, tp_atr=3.0),
    TuneCombo("C_buy60_sl1.5_tp2.0", buy_threshold=60, min_confluence=3, sl_atr=1.5, tp_atr=2.0),
    TuneCombo("C_buy60_sl1.2_tp2.5", buy_threshold=60, min_confluence=3, sl_atr=1.2, tp_atr=2.5),
    TuneCombo("C_buy60_sl1.2_tp3.0", buy_threshold=60, min_confluence=3, sl_atr=1.2, tp_atr=3.0),
    TuneCombo("C_buy55_sl1.5_tp2.5", buy_threshold=55, min_confluence=3, sl_atr=1.5, tp_atr=2.5),
    TuneCombo("C_buy55_sl1.2_tp3.0", buy_threshold=55, min_confluence=3, sl_atr=1.2, tp_atr=3.0),
]


def patch_scoring(combo: TuneCombo) -> None:
    """Monkey-patch SCORING config for this combo."""
    # SCORING is frozen dataclass, so we use object.__setattr__
    object.__setattr__(SCORING, "BUY_THRESHOLD", combo.buy_threshold)
    object.__setattr__(SCORING, "MIN_CONFLUENCE", combo.min_confluence)
    object.__setattr__(SCORING, "SL_ATR_MULTIPLIER", combo.sl_atr)
    object.__setattr__(SCORING, "TP_ATR_MULTIPLIER", combo.tp_atr)


def main() -> None:
    tickers = list(TICKERS)
    months = 6

    print("=" * 80)
    print("  ZENTRA PARAMETER SWEEP")
    print(f"  Testing {len(COMBOS)} combinations on {len(tickers)} tickers, {months} months")
    print("=" * 80)

    # Fetch data once
    engine = BacktestEngine()
    print("\nFetching historical data (one-time)...")
    all_data = engine.fetch_historical(tickers, months)
    print(f"Loaded {len(all_data)} tickers\n")

    results: list[tuple[TuneCombo, BacktestResult]] = []

    for i, combo in enumerate(COMBOS):
        print(f"[{i+1}/{len(COMBOS)}] Testing {combo.name} "
              f"(Buy={combo.buy_threshold}, Conf={combo.min_confluence}, SL={combo.sl_atr}x, TP={combo.tp_atr}x)")

        # Patch config
        patch_scoring(combo)

        # Run backtest with pre-fetched data
        engine2 = BacktestEngine()  # Fresh engine
        try:
            result = engine2.run(tickers=tickers, months=months, prefetched_data=all_data)
            results.append((combo, result))
            print(f"   -> Signals={result.total_signals}, "
                  f"WinRate={result.win_rate:.1f}%, "
                  f"PF={result.profit_factor:.2f}, "
                  f"DD={result.max_drawdown_pct:.1f}%, "
                  f"Return={result.total_return_pct:+.1f}%")
        except Exception as e:
            print(f"   -> ERROR: {e}")

    # Print comparison table
    print("\n" + "=" * 80)
    print("  RESULTS COMPARISON")
    print("=" * 80)
    header = (f"  {'Name':<22} {'Buy':>4} {'Conf':>4} {'SL':>4} {'TP':>4} "
              f"{'Sigs':>5} {'Win%':>6} {'PF':>6} {'DD%':>6} {'Ret%':>7} {'Status':>8}")
    print(header)
    print("  " + "-" * 80)

    best = None
    best_score = -999

    for combo, result in results:
        # Composite score: prioritize win rate and profit factor
        wr_pass = result.win_rate >= 30.0
        pf_pass = result.profit_factor >= 1.0
        dd_pass = result.max_drawdown_pct <= 30.0
        all_pass = wr_pass and pf_pass and dd_pass

        # Composite: weight profit factor heavily, then win rate, then drawdown
        composite = (
            result.profit_factor * 40
            + result.win_rate * 1.0
            - result.max_drawdown_pct * 0.5
            + result.total_return_pct * 0.3
        )

        status = "PASS" if all_pass else "FAIL"

        pf_str = f"{result.profit_factor:.2f}" if result.profit_factor != float("inf") else "INF"
        print(f"  {combo.name:<22} {combo.buy_threshold:>4} {combo.min_confluence:>4} {combo.sl_atr:>4.1f} {combo.tp_atr:>4.1f} "
              f"{result.total_signals:>5} {result.win_rate:>5.1f}% {pf_str:>6} {result.max_drawdown_pct:>5.1f}% "
              f"{result.total_return_pct:>+6.1f}% {status:>8}")

        if composite > best_score:
            best_score = composite
            best = (combo, result)

    if best:
        combo, result = best
        print(f"\n  RECOMMENDED: {combo.name}")
        print(f"  Buy={combo.buy_threshold}, Conf={combo.min_confluence}, SL={combo.sl_atr}x, TP={combo.tp_atr}x")
        print(f"  Win Rate={result.win_rate:.1f}%, PF={result.profit_factor:.2f}, "
              f"DD={result.max_drawdown_pct:.1f}%, Return={result.total_return_pct:+.1f}%")

    print()


if __name__ == "__main__":
    main()
