"""Walk-forward backtest engine — no lookahead bias.

Fetches historical data, walks forward day-by-day, applies scoring engine,
tracks positions, and calculates performance metrics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pandas as pd
import structlog
import yfinance as yf

from zentra.analysis.indicators import TechnicalIndicators
from zentra.analysis.scorer import SignalScorer
from zentra.config import SCORING, TICKERS, SignalType
from zentra.data.validator import DataValidator
from zentra.exceptions import CalculationError

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Trade:
    """A single completed or open trade."""
    ticker: str
    entry_date: str
    entry_price: float
    stop_loss: float
    take_profit: float
    score: int
    confluence: int

    exit_date: str | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    pnl_pct: float | None = None
    holding_days: int | None = None
    is_open: bool = True


@dataclass
class TickerStats:
    """Per-ticker performance summary."""
    ticker: str
    total_signals: int = 0
    wins: int = 0
    losses: int = 0
    total_return_pct: float = 0.0
    avg_return_pct: float = 0.0
    avg_holding_days: float = 0.0
    win_rate: float = 0.0


@dataclass
class BacktestResult:
    """Full backtest output."""
    start_date: str
    end_date: str
    tickers_tested: int
    trading_days: int

    total_signals: int = 0
    total_trades_closed: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0

    avg_return_pct: float = 0.0
    total_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    profit_factor: float = 0.0
    avg_holding_days: float = 0.0

    trades: list[Trade] = field(default_factory=list)
    ticker_stats: list[TickerStats] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    edge_cases: list[str] = field(default_factory=list)

    lookahead_violations: int = 0
    duplicate_violations: int = 0


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class BacktestEngine:
    """Walk-forward backtest engine with strict no-lookahead guarantee."""

    MIN_WARMUP_DAYS = 30  # Enough for EMA_21 + buffer

    def __init__(self) -> None:
        self.indicators = TechnicalIndicators()
        self.scorer = SignalScorer()
        self.validator = DataValidator()

    def fetch_historical(
        self, tickers: list[str], months: int = 6
    ) -> dict[str, pd.DataFrame]:
        """Fetch historical data for all tickers."""
        end = datetime.now(tz=timezone.utc)
        start = end - timedelta(days=months * 30 + 90)  # Extra 90 days for warmup

        tickers_jk = [f"{t}.JK" for t in tickers]
        log.info("backtest_fetching", tickers=len(tickers), months=months)

        raw = yf.download(
            tickers_jk,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            group_by="ticker",
            progress=False,
            auto_adjust=True,
        )

        result: dict[str, pd.DataFrame] = {}
        for ticker in tickers:
            ticker_jk = f"{ticker}.JK"
            try:
                if isinstance(raw.columns, pd.MultiIndex):
                    if ticker_jk in raw.columns.get_level_values(0):
                        df = raw[ticker_jk].copy()
                    else:
                        continue
                else:
                    df = raw.copy()

                # Flatten MultiIndex if needed
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(-1)

                df.columns = [c.lower().strip() for c in df.columns]
                expected = ["open", "high", "low", "close", "volume"]
                available = [c for c in expected if c in df.columns]
                df = df[available]

                for col in ["open", "high", "low", "close"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce")
                if "volume" in df.columns:
                    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype("int64")

                if df.index.tz is not None:
                    df.index = df.index.tz_convert("UTC").tz_localize(None)
                df.index.name = "date"

                df = df.dropna(subset=["close"])
                if len(df) >= self.MIN_WARMUP_DAYS:
                    result[ticker] = df
                    log.info("backtest_ticker_loaded", ticker=ticker, rows=len(df))
                else:
                    log.warning("backtest_ticker_insufficient", ticker=ticker, rows=len(df))
            except Exception as e:
                log.warning("backtest_ticker_failed", ticker=ticker, error=str(e))

        return result

    def run(
        self,
        tickers: list[str] | None = None,
        months: int = 6,
        prefetched_data: dict[str, pd.DataFrame] | None = None,
    ) -> BacktestResult:
        """Run the full walk-forward backtest."""
        tickers = tickers or list(TICKERS)

        # 1. Fetch all historical data upfront or use prefetched
        all_data = prefetched_data if prefetched_data is not None else self.fetch_historical(tickers, months)
        if not all_data:
            raise RuntimeError("No historical data available for backtest")

        # 1.5 Precalculate indicators upfront (massively speeds up backtest)
        for ticker in list(all_data.keys()):
            try:
                all_data[ticker] = self.indicators.compute_all(all_data[ticker])
            except Exception as e:
                log.warning("backtest_indicator_failed", ticker=ticker, error=str(e))
                del all_data[ticker]

        # 2. Determine the common date range (after warmup)
        all_dates: set[datetime] = set()
        for df in all_data.values():
            all_dates.update(df.index[self.MIN_WARMUP_DAYS:].tolist())
        sorted_dates = sorted(all_dates)

        if not sorted_dates:
            raise RuntimeError("No trading days available after warmup period")

        # Trim to requested months
        cutoff = sorted_dates[-1] - timedelta(days=months * 30)
        sorted_dates = [d for d in sorted_dates if d >= cutoff]

        start_date = sorted_dates[0].strftime("%Y-%m-%d")
        end_date = sorted_dates[-1].strftime("%Y-%m-%d")

        log.info(
            "backtest_starting",
            start=start_date,
            end=end_date,
            trading_days=len(sorted_dates),
            tickers=len(all_data),
        )

        # 3. State tracking
        active_signals: dict[str, Trade] = {}  # ticker -> open trade
        all_trades: list[Trade] = []
        equity = 100.0  # Start at 100 for drawdown calculation
        equity_curve: list[float] = [100.0]
        peak_equity = 100.0
        max_drawdown = 0.0
        edge_cases: list[str] = []
        duplicate_violations = 0

        # 4. Walk forward — day by day
        for day_idx, current_date in enumerate(sorted_dates):
            date_str = current_date.strftime("%Y-%m-%d")

            for ticker in list(all_data.keys()):
                df_full = all_data[ticker]

                # CRITICAL: Only use data up to and including current_date (no lookahead)
                df_slice = df_full[df_full.index <= current_date]

                if len(df_slice) < self.MIN_WARMUP_DAYS:
                    continue

                # Get current prices
                try:
                    current_close = float(df_slice.iloc[-1]["close"])
                    current_low = float(df_slice.iloc[-1]["low"])
                    current_high = float(df_slice.iloc[-1]["high"])
                except (KeyError, IndexError):
                    continue

                # --- Check EXIT for active positions ---
                if ticker in active_signals:
                    trade = active_signals[ticker]

                    # Check expiry (10 days)
                    entry_dt = datetime.strptime(trade.entry_date, "%Y-%m-%d")
                    days_held = (current_date - entry_dt).days
                    if hasattr(current_date, 'date'):
                        days_held = (current_date - entry_dt).days

                    # SL hit (check low price first to be conservative)
                    if current_low <= trade.stop_loss:
                        self._close_trade(trade, date_str, trade.stop_loss, "SL hit")
                        del active_signals[ticker]
                        all_trades.append(trade)
                        equity += trade.pnl_pct or 0
                    # TP hit
                    elif current_high >= trade.take_profit:
                        self._close_trade(trade, date_str, trade.take_profit, "TP hit")
                        del active_signals[ticker]
                        all_trades.append(trade)
                        equity += trade.pnl_pct or 0
                    # Expiry
                    elif days_held >= SCORING.SIGNAL_EXPIRY_DAYS:
                        self._close_trade(trade, date_str, current_close, "Expired (10d)")
                        del active_signals[ticker]
                        all_trades.append(trade)
                        equity += trade.pnl_pct or 0
                    else:
                        # Check technical EXIT conditions
                        try:
                            # indicators are already precalculated in df_slice
                            exit_result = self.scorer.check_exit(ticker, df_slice, {
                                "entry_price": int(trade.entry_price),
                                "stop_loss": int(trade.stop_loss),
                                "take_profit": int(trade.take_profit),
                            }, days_held=days_held)
                            if exit_result:
                                reason = ", ".join(exit_result.exit_reasons[:2])
                                self._close_trade(trade, date_str, current_close, reason)
                                del active_signals[ticker]
                                all_trades.append(trade)
                                equity += trade.pnl_pct or 0
                        except CalculationError:
                            pass

                    # Track equity after EXIT
                    equity_curve.append(equity)
                    peak_equity = max(peak_equity, equity)
                    dd = (peak_equity - equity) / peak_equity * 100
                    max_drawdown = max(max_drawdown, dd)
                    continue  # Skip BUY scoring if we just handled EXIT

                # --- BUY scoring ---
                # Deduplication check
                if ticker in active_signals:
                    duplicate_violations += 1
                    edge_cases.append(f"Duplicate signal attempted for {ticker} on {date_str}")
                    continue

                try:
                    # indicators already precalculated in df_slice
                    buy_result = self.scorer.score_buy(ticker, df_slice)

                    if buy_result.signal_type == SignalType.BUY and buy_result.entry_price:
                        trade = Trade(
                            ticker=ticker,
                            entry_date=date_str,
                            entry_price=float(buy_result.entry_price),
                            stop_loss=float(buy_result.stop_loss or 0),
                            take_profit=float(buy_result.take_profit or 0),
                            score=buy_result.score,
                            confluence=buy_result.confluence_count,
                        )
                        active_signals[ticker] = trade

                except CalculationError:
                    pass

            # End-of-day equity update
            if len(equity_curve) == 0 or equity_curve[-1] != equity:
                equity_curve.append(equity)
                peak_equity = max(peak_equity, equity)
                dd = (peak_equity - equity) / peak_equity * 100
                max_drawdown = max(max_drawdown, dd)

        # 5. Force-close remaining open positions at last known price
        for ticker, trade in active_signals.items():
            if ticker in all_data:
                last_close = float(all_data[ticker].iloc[-1]["close"])
                self._close_trade(trade, end_date, last_close, "Backtest end (forced close)")
                all_trades.append(trade)
                equity += trade.pnl_pct or 0

        # 6. Calculate metrics
        closed_trades = [t for t in all_trades if not t.is_open]
        total_signals = len(all_trades)
        wins = sum(1 for t in closed_trades if (t.pnl_pct or 0) > 0)
        losses = sum(1 for t in closed_trades if (t.pnl_pct or 0) <= 0)
        win_rate = (wins / len(closed_trades) * 100) if closed_trades else 0.0

        returns = [t.pnl_pct or 0 for t in closed_trades]
        avg_return = sum(returns) / len(returns) if returns else 0.0
        total_return = equity - 100.0  # Net return from base 100

        winning_sum = sum(r for r in returns if r > 0)
        losing_sum = abs(sum(r for r in returns if r <= 0))
        profit_factor = (winning_sum / losing_sum) if losing_sum > 0 else float("inf")

        holding_days = [t.holding_days or 0 for t in closed_trades]
        avg_holding = sum(holding_days) / len(holding_days) if holding_days else 0.0

        # 7. Per-ticker stats
        ticker_map: dict[str, list[Trade]] = {}
        for t in closed_trades:
            ticker_map.setdefault(t.ticker, []).append(t)

        ticker_stats: list[TickerStats] = []
        for ticker, trades in sorted(ticker_map.items()):
            t_wins = sum(1 for t in trades if (t.pnl_pct or 0) > 0)
            t_returns = [t.pnl_pct or 0 for t in trades]
            t_holding = [t.holding_days or 0 for t in trades]
            ticker_stats.append(TickerStats(
                ticker=ticker,
                total_signals=len(trades),
                wins=t_wins,
                losses=len(trades) - t_wins,
                total_return_pct=sum(t_returns),
                avg_return_pct=sum(t_returns) / len(t_returns) if t_returns else 0,
                avg_holding_days=sum(t_holding) / len(t_holding) if t_holding else 0,
                win_rate=(t_wins / len(trades) * 100) if trades else 0,
            ))

        return BacktestResult(
            start_date=start_date,
            end_date=end_date,
            tickers_tested=len(all_data),
            trading_days=len(sorted_dates),
            total_signals=total_signals,
            total_trades_closed=len(closed_trades),
            wins=wins,
            losses=losses,
            win_rate=win_rate,
            avg_return_pct=avg_return,
            total_return_pct=total_return,
            max_drawdown_pct=max_drawdown,
            profit_factor=profit_factor,
            avg_holding_days=avg_holding,
            trades=all_trades,
            ticker_stats=ticker_stats,
            equity_curve=equity_curve,
            edge_cases=edge_cases,
            lookahead_violations=0,  # Guaranteed by design: df_slice = df[df.index <= current_date]
            duplicate_violations=duplicate_violations,
        )

    def _close_trade(
        self, trade: Trade, exit_date: str, exit_price: float, reason: str
    ) -> None:
        """Close a trade and calculate P&L."""
        trade.exit_date = exit_date
        trade.exit_price = exit_price
        trade.exit_reason = reason
        trade.is_open = False
        trade.pnl_pct = round(
            (exit_price - trade.entry_price) / trade.entry_price * 100, 2
        )
        entry_dt = datetime.strptime(trade.entry_date, "%Y-%m-%d")
        exit_dt = datetime.strptime(exit_date, "%Y-%m-%d")
        trade.holding_days = (exit_dt - entry_dt).days
