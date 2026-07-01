"""ZENTRA Orchestrator — data pipeline helpers for trade date, readiness, candle handling, and lock release."""

from __future__ import annotations

from datetime import date

import pandas as pd
import structlog

import zentra.orchestrator as _orch
from zentra.orchestrator.core import ZENTRAOrchestrator

log = structlog.get_logger()


def _latest_trade_date(self: ZENTRAOrchestrator, all_data: dict[str, pd.DataFrame]) -> date | None:
    latest_trade_date = None
    for df in all_data.values():
        if df is None or df.empty:
            continue
        candidate = pd.Timestamp(df.index[-1]).date()
        if latest_trade_date is None or candidate > latest_trade_date:
            latest_trade_date = candidate
    if all_data and latest_trade_date is None:
        log.warning(
            "all_data_empty",
            phase="data_readiness",
            total=len(all_data),
            empty_count=sum(1 for df in all_data.values() if df is None or df.empty),
        )
    return latest_trade_date


def _data_readiness_status(
    self: ZENTRAOrchestrator,
    all_data: dict[str, pd.DataFrame],
) -> tuple[str, date | None, date]:
    expected_trade_date = self._market_calendar.expected_last_trade_day(
        _orch.today_jakarta(),
        mode=self._mode,
    )
    latest_trade_date = self._latest_trade_date(all_data)
    if latest_trade_date is None:
        return "provider_stale", None, expected_trade_date
    if latest_trade_date >= expected_trade_date:
        return "ready", latest_trade_date, expected_trade_date
    if self._mode == "closing" and latest_trade_date == self._market_calendar.previous_trading_day(expected_trade_date):
        return "market_data_pending", latest_trade_date, expected_trade_date
    return "provider_stale", latest_trade_date, expected_trade_date


def _handle_partial_candle(self: ZENTRAOrchestrator, df: pd.DataFrame, ticker_log) -> pd.DataFrame:
    """P1-8: Robust partial candle handling.

    Morning mode: always drop candle if last_date >= today (today's candle is partial).
    Closing mode keeps today's candle for the closed-session scan.
    """
    if self._mode == "morning" and not df.empty:
        last_date = pd.Timestamp(df.index[-1]).date()
        if last_date >= _orch.today_jakarta():
            df = df.iloc[:-1]
            ticker_log.info("dropped_partial_candle", phase="normalize", dropped_date=str(last_date))
    return df


def _release_run_lock(self: ZENTRAOrchestrator, locks_repo, run_lock: dict | None, run_log) -> bool:
    if not locks_repo or not run_lock:
        return True
    try:
        locks_repo.release(run_lock)
        return True
    except Exception as e:
        run_log.error("run_lock_release_failed", phase="lock", error=str(e))
        return False


ZENTRAOrchestrator._latest_trade_date = _latest_trade_date
ZENTRAOrchestrator._data_readiness_status = _data_readiness_status
ZENTRAOrchestrator._handle_partial_candle = _handle_partial_candle
ZENTRAOrchestrator._release_run_lock = _release_run_lock
