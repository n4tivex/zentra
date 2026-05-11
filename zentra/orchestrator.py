"""ZENTRA Orchestrator — top-level coordinator for the analysis pipeline."""

from __future__ import annotations

import random
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import structlog
import yfinance as yf

from zentra.analysis.indicators import TechnicalIndicators
from zentra.analysis.scorer import SignalScorer
from zentra.config import (
    TICKERS,
    SignalResult,
    SignalStatus,
    SignalType,
    get_env,
    validate_env,
)
from zentra.data.fetcher import MarketDataFetcher
from zentra.data.validator import DataValidator
from zentra.db.client import get_client
from zentra.db.ohlcv_repo import OHLCVRepo
from zentra.db.run_logs_repo import RunLogsRepo
from zentra.db.signals_repo import SignalsRepo
from zentra.exceptions import (
    CalculationError,
    ConfigurationError,
    InsufficientDataError,
    StaleDataError,
)
from zentra.narrative.blocks import MARKET_CLOSED_HOLIDAY, MARKET_CLOSED_WEEKEND, NO_SIGNAL_MESSAGES
from zentra.narrative.generator import NarrativeGenerator
from zentra.runtime import is_weekend_jakarta, now_jakarta, today_jakarta
from zentra.telegram.formatter import (
    escape_markdown_v2,
    format_buy_message,
    format_daily_summary,
    format_exit_message,
    format_watch_message,
    format_weekly_performance_summary,
)
from zentra.telegram.sender import TelegramSender

log = structlog.get_logger()


class ZENTRAOrchestrator:
    def __init__(self, mode: str = "morning", dry_run: bool = False) -> None:
        self._mode = mode
        self._dry_run = dry_run
        self._today = today_jakarta().strftime("%Y-%m-%d")

    async def run(self, single_ticker: str | None = None) -> bool:
        start_time = time.time()

        if not self._dry_run:
            try:
                validate_env()
            except ConfigurationError as e:
                log.error("config_validation_failed", error=str(e))
                return False

        if not self._dry_run:
            db = get_client()
            signals_repo = SignalsRepo(db)
            ohlcv_repo = OHLCVRepo(db)
            run_logs_repo = RunLogsRepo(db)
            sender = TelegramSender(
                bot_token=get_env("TELEGRAM_BOT_TOKEN"),
                chat_id=get_env("TELEGRAM_CHAT_ID"),
                admin_chat_id=get_env("TELEGRAM_ADMIN_CHAT_ID"),
            )
        else:
            signals_repo = None
            ohlcv_repo = None
            run_logs_repo = None
            sender = None

        run_id = None
        if run_logs_repo:
            try:
                run_id = run_logs_repo.create_run(self._mode)
            except Exception as e:
                log.error("run_log_creation_failed", error=str(e))

        if is_weekend_jakarta():
            log.info("market_closed_weekend")
            if sender:
                await sender.send_signal(MARKET_CLOSED_WEEKEND)
            if run_logs_repo and run_id:
                run_logs_repo.update_run(run_id, status="SUCCESS", duration_seconds=0)
            return True

        jakarta_now = now_jakarta()
        try:
            end = jakarta_now + timedelta(days=1)
            start = jakarta_now - timedelta(days=5)
            sample = yf.download(
                "BBCA.JK",
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                progress=False,
                auto_adjust=True,
            )

            if sample is not None and not sample.empty:
                last_trade = pd.Timestamp(sample.index[-1]).date()
                days_since = (today_jakarta() - last_trade).days
                if days_since > 0 and self._mode == "closing":
                    log.info("market_likely_holiday", last_trade=str(last_trade))
                    if sender:
                        await sender.send_signal(MARKET_CLOSED_HOLIDAY)
                    if run_logs_repo and run_id:
                        run_logs_repo.update_run(run_id, status="SUCCESS", duration_seconds=0)
                    return True
        except Exception as e:
            log.warning("holiday_check_failed", error=str(e))

        tickers = [single_ticker] if single_ticker else list(TICKERS)
        fetcher = MarketDataFetcher(ohlcv_repo=ohlcv_repo)

        try:
            all_data = fetcher.fetch_all(tickers)
        except Exception as e:
            log.error("data_fetch_failed", error=str(e))
            if run_logs_repo and run_id:
                run_logs_repo.update_run(
                    run_id,
                    status="FAILED",
                    error_message=str(e),
                    duration_seconds=time.time() - start_time,
                )
            if sender:
                await sender.send_admin_alert(
                    escape_markdown_v2(f"⚠️ ZENTRA FAILED: Data fetch error — {e}")
                )
            return False

        validator = DataValidator()
        indicators = TechnicalIndicators()
        scorer = SignalScorer()
        narrative_gen = NarrativeGenerator(run_date=self._today)

        all_signals: list[SignalResult] = []
        failed_tickers: list[str] = []

        for ticker in tickers:
            ticker_log = log.bind(ticker=ticker)

            try:
                df = all_data.get(ticker)
                if df is None or df.empty:
                    failed_tickers.append(ticker)
                    continue

                if self._mode == "morning" and not df.empty:
                    last_date = pd.Timestamp(df.index[-1]).date()
                    if last_date == today_jakarta():
                        df = df.iloc[:-1]
                        ticker_log.info("dropped_partial_today_candle")

                if df.empty:
                    failed_tickers.append(ticker)
                    continue

                validation = validator.validate(ticker, df)
                if not validation.is_valid:
                    ticker_log.warning("validation_failed", errors=validation.errors)
                    failed_tickers.append(ticker)
                    continue

                for warning in validation.warnings:
                    ticker_log.warning("validation_warning", warning=warning)

                df_clean = validation.cleaned_df if validation.cleaned_df is not None else df

                if ohlcv_repo and not self._dry_run:
                    try:
                        ohlcv_repo.upsert_batch(ticker, df_clean)
                    except Exception as e:
                        ticker_log.warning("cache_upsert_failed", error=str(e))

                df_ind = indicators.compute_all(df_clean)

                active = signals_repo.get_active_signal(ticker) if signals_repo else None
                if active:
                    created_str = active.get("created_at", "")
                    if created_str:
                        created_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                        days_held = (datetime.now(tz=timezone.utc) - created_dt).days
                    else:
                        days_held = 99

                    exit_result = scorer.check_exit(ticker, df_ind, active, days_held=days_held)
                    if exit_result:
                        exit_result.narrative = narrative_gen.generate_exit(exit_result, active)
                        all_signals.append(exit_result)
                    continue

                buy_result = scorer.score_buy(ticker, df_ind)
                ticker_log.info(
                    "scored",
                    score=buy_result.score,
                    type=buy_result.signal_type.value,
                    confluence=buy_result.confluence_count,
                )

                if buy_result.signal_type in (SignalType.BUY, SignalType.WATCH):
                    buy_result.narrative = narrative_gen.generate_buy(buy_result)
                    all_signals.append(buy_result)

            except (CalculationError, InsufficientDataError, StaleDataError) as e:
                ticker_log.warning("ticker_processing_error", error=str(e))
                failed_tickers.append(ticker)
            except Exception as e:
                ticker_log.error("ticker_unexpected_error", error=str(e))
                failed_tickers.append(ticker)

        exit_signals = [s for s in all_signals if s.signal_type == SignalType.EXIT]
        buy_signals = [s for s in all_signals if s.signal_type == SignalType.BUY]
        watch_signals = [s for s in all_signals if s.signal_type == SignalType.WATCH]

        exit_signals.sort(key=lambda s: s.signal_strength == "STRONG", reverse=True)
        buy_signals.sort(key=lambda s: s.score, reverse=True)

        expired: list[dict] = []
        if signals_repo:
            try:
                expired = signals_repo.expire_old_signals()
            except Exception as e:
                log.warning("expire_signals_failed", error=str(e))

        messages: list[str] = []
        signal_lines: list[str] = []

        for sig in exit_signals:
            active = signals_repo.get_active_signal(sig.ticker) if signals_repo else None
            messages.append(format_exit_message(sig, active or {}))
            signal_lines.append(f"🔴 EXIT {sig.ticker}")

            if signals_repo and active:
                close_price = int(sig.indicator_snapshot.get("close", 0))

                if "Target price reached" in sig.exit_reasons:
                    status = SignalStatus.CLOSED_TP
                elif "Stop loss hit" in sig.exit_reasons:
                    status = SignalStatus.CLOSED_SL
                else:
                    status = SignalStatus.CLOSED_EXIT_SIGNAL

                try:
                    signals_repo.close_signal(
                        active["id"],
                        status,
                        close_price,
                        active.get("entry_price", 0),
                    )
                except Exception as e:
                    log.error("close_signal_failed", ticker=sig.ticker, error=str(e))

        for sig in buy_signals:
            messages.append(format_buy_message(sig))
            signal_lines.append(f"🟢 BUY {sig.ticker} (skor: {sig.score})")
            if signals_repo and run_id:
                try:
                    signals_repo.create_signal(sig, run_id=run_id)
                except Exception as e:
                    log.error("persist_signal_failed", ticker=sig.ticker, error=str(e))

        watch_messages: list[str] = []
        for sig in watch_signals:
            watch_messages.append(format_watch_message(sig))
            signal_lines.append(f"👁 WATCH {sig.ticker} (skor: {sig.score})")
            if signals_repo and run_id:
                try:
                    signals_repo.create_signal(sig, run_id=run_id)
                except Exception as e:
                    log.error("persist_watch_failed", ticker=sig.ticker, error=str(e))

        for exp in expired:
            exp_ticker = exp.get("ticker", "?")
            days_active = (
                datetime.now(tz=timezone.utc)
                - datetime.fromisoformat(exp["created_at"].replace("Z", "+00:00"))
            ).days
            watch_messages.append(
                escape_markdown_v2(narrative_gen.generate_expired(exp_ticker, days_active))
            )

        if not messages and not watch_messages:
            messages.append(random.Random(self._today).choice(NO_SIGNAL_MESSAGES))

        duration = time.time() - start_time
        total = len(tickers)
        success_count = total - len(failed_tickers)

        if len(signal_lines) >= 3:
            messages.append(
                format_daily_summary(
                    date_str=self._today,
                    duration=duration,
                    total=total,
                    success=success_count,
                    failed=len(failed_tickers),
                    signal_lines=signal_lines,
                )
            )

        telegram_sent = 0
        telegram_failed_count = 0

        if sender and not self._dry_run:
            results = await sender.send_batch(messages)
            telegram_sent = sum(results)
            telegram_failed_count = len(results) - telegram_sent

            for wm in watch_messages:
                await sender.send_admin_alert(wm)
        else:
            telegram_sent = len(messages)

        if run_logs_repo and run_id:
            if len(failed_tickers) == 0:
                run_status = "SUCCESS"
            elif len(failed_tickers) > 15:
                run_status = "FAILED"
            else:
                run_status = "PARTIAL"

            run_logs_repo.update_run(
                run_id,
                status=run_status,
                duration_seconds=duration,
                tickers_scanned=total,
                tickers_failed=failed_tickers if failed_tickers else None,
                signals_generated=len(all_signals),
                buy_signals=len(buy_signals),
                exit_signals=len(exit_signals),
                watch_signals=len(watch_signals),
                telegram_sent=telegram_sent,
                telegram_failed=telegram_failed_count,
            )

        log.info(
            "run_completed",
            duration=f"{duration:.1f}s",
            signals=len(all_signals),
            failed=len(failed_tickers),
        )

        return len(failed_tickers) <= 15
