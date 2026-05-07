"""ZENTRA Orchestrator — top-level coordinator for the analysis pipeline.

Per PRD §11.3: validates env, fetches data, processes tickers, sends signals.
Isolation per ticker, graceful degradation, message ordering.
"""

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
    ZENTRABaseError,
)
from zentra.narrative.blocks import MARKET_CLOSED_HOLIDAY, MARKET_CLOSED_WEEKEND, NO_SIGNAL_MESSAGES
from zentra.narrative.generator import NarrativeGenerator
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
    """Coordinates the full ZENTRA pipeline."""

    def __init__(self, mode: str = "morning", dry_run: bool = False) -> None:
        self._mode = mode
        self._dry_run = dry_run
        self._today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

    async def run(self, single_ticker: str | None = None) -> bool:
        """Execute the full pipeline. Returns True on success/partial, False on failure."""
        start_time = time.time()

        # 1. Validate environment
        if not self._dry_run:
            try:
                validate_env()
            except ConfigurationError as e:
                log.error("config_validation_failed", error=str(e))
                return False

        # Initialize components
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

        # 2. Create run log
        run_id = None
        if run_logs_repo:
            try:
                run_id = run_logs_repo.create_run(self._mode)
            except Exception as e:
                log.error("run_log_creation_failed", error=str(e))

        # 3. Check market status
        today_dt = datetime.now(tz=timezone.utc)
        if today_dt.weekday() >= 5:  # Saturday=5, Sunday=6
            log.info("market_closed_weekend")
            if sender:
                await sender.send_signal(MARKET_CLOSED_WEEKEND)
            if run_logs_repo and run_id:
                run_logs_repo.update_run(run_id, status="SUCCESS", duration_seconds=0)
            return True

        # 3b. Holiday detection per PRD §5.3
        # Fetch 1 day of BBCA to check if market is open today
        try:
            # yfinance end date is exclusive, so we must add 1 day to fetch today's bar
            end = today_dt + timedelta(days=1)
            start = today_dt - timedelta(days=5)
            sample = yf.download(
                "BBCA.JK",
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                progress=False,
                auto_adjust=True,
            )
            if sample is not None and not sample.empty:
                last_trade = sample.index[-1]
                if hasattr(last_trade, 'tz') and last_trade.tz is not None:
                    last_trade = last_trade.tz_convert('UTC').tz_localize(None)
                
                # If last trade is not today, market is either closed or data is delayed
                days_since = (today_dt.replace(tzinfo=None).date() - last_trade.date()).days
                if days_since > 0 and self._mode == "closing":
                    log.info("market_likely_holiday", last_trade=str(last_trade.date()), days_since=days_since)
                    if sender:
                        await sender.send_signal(MARKET_CLOSED_HOLIDAY)
                    if run_logs_repo and run_id:
                        run_logs_repo.update_run(run_id, status="SUCCESS", duration_seconds=0)
                    return True
        except Exception as e:
            log.warning("holiday_check_failed", error=str(e))

        # 4. Determine tickers to process
        tickers = [single_ticker] if single_ticker else list(TICKERS)

        # 5. Fetch data
        fetcher = MarketDataFetcher(ohlcv_repo=ohlcv_repo)
        try:
            all_data = fetcher.fetch_all(tickers)
        except Exception as e:
            log.error("data_fetch_failed", error=str(e))
            if run_logs_repo and run_id:
                run_logs_repo.update_run(
                    run_id, status="FAILED", error_message=str(e),
                    duration_seconds=time.time() - start_time,
                )
            if sender:
                await sender.send_admin_alert(
                    escape_markdown_v2(f"⚠️ ZENTRA FAILED: Data fetch error — {e}")
                )
            return False

        # 6. Process each ticker (isolated)
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
                    ticker_log.warning("no_data_for_ticker")
                    failed_tickers.append(ticker)
                    continue

                # --- FIX 1: Morning Scan Contamination ---
                # Drop today's partial candle if in morning mode so we evaluate yesterday's close
                if self._mode == "morning" and not df.empty:
                    last_date_str = pd.Timestamp(df.index[-1]).strftime("%Y-%m-%d")
                    if last_date_str == self._today:
                        df = df.iloc[:-1]
                        ticker_log.info("dropped_partial_today_candle")
                        
                if df.empty:
                    ticker_log.warning("empty_after_drop")
                    failed_tickers.append(ticker)
                    continue

                # Validate
                validation = validator.validate(ticker, df)
                if not validation.is_valid:
                    ticker_log.warning("validation_failed", errors=validation.errors)
                    failed_tickers.append(ticker)
                    continue

                for w in validation.warnings:
                    ticker_log.warning("validation_warning", warning=w)

                # Clean dataframe (drop NaNs that break JSON and indicators)
                df = df.dropna(subset=["open", "high", "low", "close", "volume"])

                # Fix negative volumes before analysis
                if "volume" in df.columns:
                    df.loc[df["volume"] < 0, "volume"] = 0

                # Cache to Supabase
                if ohlcv_repo and not self._dry_run:
                    try:
                        ohlcv_repo.upsert_batch(ticker, df)
                    except Exception as e:
                        ticker_log.warning("cache_upsert_failed", error=str(e))

                # Compute indicators
                df_ind = indicators.compute_all(df)

                # Check for EXIT on active signals first
                if signals_repo:
                    active = signals_repo.get_active_signal(ticker)
                    if active:
                        # Calculate days held for grace period
                        created_str = active.get("created_at", "")
                        if created_str:
                            created_dt = datetime.fromisoformat(
                                created_str.replace("Z", "+00:00")
                            )
                            days_held = (
                                datetime.now(tz=timezone.utc) - created_dt
                            ).days
                        else:
                            days_held = 99  # Fallback: skip grace period
                        exit_result = scorer.check_exit(
                            ticker, df_ind, active, days_held=days_held
                        )
                        if exit_result:
                            exit_result.narrative = narrative_gen.generate_exit(
                                exit_result, active
                            )
                            all_signals.append(exit_result)
                            ticker_log.info(
                                "exit_signal_generated",
                                reasons=exit_result.exit_reasons,
                            )
                        # Skip BUY scoring — already have active signal
                        continue

                # Score for BUY
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

        # 7. Sort signals: STRONG EXIT > EXIT > BUY (by score desc)
        exit_signals = [s for s in all_signals if s.signal_type == SignalType.EXIT]
        buy_signals = [s for s in all_signals if s.signal_type == SignalType.BUY]
        watch_signals = [s for s in all_signals if s.signal_type == SignalType.WATCH]

        # Sort EXIT: STRONG first
        exit_signals.sort(key=lambda s: s.signal_strength == "STRONG", reverse=True)
        buy_signals.sort(key=lambda s: s.score, reverse=True)

        # 8. Expire old signals
        expired: list[dict] = []
        if signals_repo:
            try:
                expired = signals_repo.expire_old_signals()
            except Exception as e:
                log.warning("expire_signals_failed", error=str(e))

        # 9. Build messages in priority order
        messages: list[str] = []
        signal_lines: list[str] = []

        for sig in exit_signals:
            active = None
            if signals_repo:
                active = signals_repo.get_active_signal(sig.ticker)
            msg = format_exit_message(sig, active or {})
            messages.append(msg)
            signal_lines.append(f"🔴 EXIT {sig.ticker}")

            # Close the active signal in DB
            if signals_repo and active:
                close_price = int(sig.indicator_snapshot.get("close", 0))
                if "Target" in (sig.reason or ""):
                    status = SignalStatus.CLOSED_TP
                elif "Stop loss" in (sig.reason or ""):
                    status = SignalStatus.CLOSED_SL
                else:
                    status = SignalStatus.CLOSED_EXIT_SIGNAL
                try:
                    signals_repo.close_signal(
                        active["id"], status, close_price, active.get("entry_price", 0)
                    )
                except Exception as e:
                    log.error("close_signal_failed", ticker=sig.ticker, error=str(e))

        for sig in buy_signals:
            msg = format_buy_message(sig)
            messages.append(msg)
            signal_lines.append(f"🟢 BUY {sig.ticker} (skor: {sig.score})")

            # Persist to DB
            if signals_repo and run_id:
                try:
                    signals_repo.create_signal(sig, run_id=run_id)
                except Exception as e:
                    log.error("persist_signal_failed", ticker=sig.ticker, error=str(e))

        # Watch signals — admin only
        watch_messages: list[str] = []
        for sig in watch_signals:
            watch_messages.append(format_watch_message(sig))
            signal_lines.append(f"👁 WATCH {sig.ticker} (skor: {sig.score})")

            if signals_repo and run_id:
                try:
                    signals_repo.create_signal(sig, run_id=run_id)
                except Exception as e:
                    log.error("persist_watch_failed", ticker=sig.ticker, error=str(e))

        # Expired signal notifications
        for exp in expired:
            exp_ticker = exp.get("ticker", "?")
            days_active = (
                datetime.now(tz=timezone.utc)
                - datetime.fromisoformat(exp["created_at"].replace("Z", "+00:00"))
            ).days
            exp_msg = narrative_gen.generate_expired(exp_ticker, days_active)
            watch_messages.append(escape_markdown_v2(exp_msg))

        # No signal message
        if not messages and not watch_messages:
            rng = random.Random(self._today)
            no_sig_msg = rng.choice(NO_SIGNAL_MESSAGES)
            messages.append(no_sig_msg)

        # Daily summary (if >= 3 signals)
        duration = time.time() - start_time
        total = len(tickers)
        success_count = total - len(failed_tickers)

        if len(signal_lines) >= 3:
            summary = format_daily_summary(
                date_str=self._today,
                duration=duration,
                total=total,
                success=success_count,
                failed=len(failed_tickers),
                signal_lines=signal_lines,
            )
            messages.append(summary)

        # 10. Send to Telegram
        telegram_sent = 0
        telegram_failed_count = 0

        if sender and not self._dry_run:
            results = await sender.send_batch(messages)
            telegram_sent = sum(results)
            telegram_failed_count = len(results) - telegram_sent

            # Send watch signals to admin
            for wm in watch_messages:
                await sender.send_admin_alert(wm)
        else:
            log.info("dry_run_messages", count=len(messages))
            for msg in messages:
                # Strip non-ASCII for Windows console compatibility
                safe_msg = msg[:300].encode("ascii", errors="replace").decode("ascii")
                log.info("dry_run_message", message=safe_msg)
            telegram_sent = len(messages)

        # 11. Update run log
        if run_logs_repo and run_id:
            # Determine status
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

            # Admin alert for partial/failed
            if run_status == "PARTIAL" and len(failed_tickers) > 5 and sender:
                await sender.send_admin_alert(
                    escape_markdown_v2(
                        f"⚠️ ZENTRA PARTIAL: {len(failed_tickers)} ticker gagal: "
                        f"{', '.join(failed_tickers[:10])}"
                    )
                )
            elif run_status == "FAILED" and sender:
                await sender.send_admin_alert(
                    escape_markdown_v2(
                        f"🔴 ZENTRA FAILED: {len(failed_tickers)}/{total} ticker gagal"
                    )
                )

        # 12. Weekly Performance Summary (Phase 2)
        if self._mode == "closing" and datetime.now(tz=timezone.utc).weekday() == 4:
            if signals_repo:
                try:
                    closed_signals = signals_repo.get_all_closed_signals()
                    active_count = signals_repo.get_active_signals_count()
                    
                    if closed_signals:
                        wins = sum(1 for s in closed_signals if float(s.get("exit_pct", 0)) > 0)
                        losses = len(closed_signals) - wins
                        win_rate = (wins / len(closed_signals)) * 100
                        avg_return = sum(float(s.get("exit_pct", 0)) for s in closed_signals) / len(closed_signals)
                        
                        ticker_perf = {}
                        for s in closed_signals:
                            t = s["ticker"]
                            if t not in ticker_perf:
                                ticker_perf[t] = {"wins": 0, "total": 0, "returns": []}
                            ticker_perf[t]["total"] += 1
                            ticker_perf[t]["returns"].append(float(s.get("exit_pct", 0)))
                            if float(s.get("exit_pct", 0)) > 0:
                                ticker_perf[t]["wins"] += 1
                                
                        top_performers = []
                        for t, perf in ticker_perf.items():
                            wr = (perf["wins"] / perf["total"]) * 100
                            avg_ret = sum(perf["returns"]) / perf["total"]
                            top_performers.append({
                                "ticker": t,
                                "win_rate_pct": wr,
                                "avg_return_pct": avg_ret
                            })
                        
                        top_performers.sort(key=lambda x: (x["win_rate_pct"], x["avg_return_pct"]), reverse=True)
                        
                        summary_msg = format_weekly_performance_summary(
                            date_str=self._today,
                            total_closed=len(closed_signals),
                            wins=wins,
                            losses=losses,
                            win_rate_pct=win_rate,
                            avg_return_pct=avg_return,
                            top_performers=top_performers,
                            active_count=active_count,
                        )
                        
                        if sender and not self._dry_run:
                            # Send to channel (batch sends to TELEGRAM_CHAT_ID)
                            await sender.send_batch([summary_msg])
                        else:
                            safe_msg = summary_msg[:300].encode("ascii", errors="replace").decode("ascii")
                            log.info("dry_run_weekly_summary", message=safe_msg)
                except Exception as e:
                    log.error("weekly_summary_failed", error=str(e))

        log.info(
            "run_completed",
            duration=f"{duration:.1f}s",
            signals=len(all_signals),
            failed=len(failed_tickers),
        )

        return len(failed_tickers) <= 15
