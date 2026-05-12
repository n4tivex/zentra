"""ZENTRA Orchestrator — top-level coordinator for the analysis pipeline.

Refactored per roadmap P1-9 (pipeline stages), P0-5 (exit classification),
P1-8 (morning candle), P1-11 (skip reasons), P1-15 (admin isolation),
P2-19 (structured logging), P2-21 (enum harmonization).
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
    RunStatus,
    SignalResult,
    SignalStatus,
    SignalType,
    get_env,
    validate_env,
)
from zentra.data.fetcher import MarketDataFetcher
from zentra.data.schema import validate_indicator_schema, validate_ohlcv_schema
from zentra.data.validator import DataValidator
from zentra.db.client import get_client
from zentra.db.ohlcv_repo import OHLCVRepo
from zentra.db.run_logs_repo import RunLogsRepo
from zentra.db.signals_repo import SignalsRepo
from zentra.exceptions import (
    CalculationError,
    ConfigurationError,
    DataIntegrityError,
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
    format_rupiah,
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

        # P2-19: Bind structured context for all logging in this run
        run_log = log.bind(mode=self._mode, run_date=self._today)

        # --- Phase: Config validation ---
        if not self._dry_run:
            try:
                validate_env()
            except ConfigurationError as e:
                run_log.error("config_validation_failed", phase="init", error=str(e))
                return False

        # --- Phase: Initialize services ---
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
                run_log = run_log.bind(run_id=run_id)
            except Exception as e:
                run_log.error("run_log_creation_failed", phase="init", error=str(e))

        # --- Phase: Market status check ---
        if is_weekend_jakarta():
            run_log.info("market_closed_weekend", phase="market_check")
            if sender:
                await sender.send_signal(MARKET_CLOSED_WEEKEND)
            if run_logs_repo and run_id:
                run_logs_repo.update_run(run_id, status=RunStatus.SUCCESS.value, duration_seconds=0)
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
                if days_since > 0:
                    run_log.info("market_likely_holiday", phase="market_check", last_trade=str(last_trade))
                    if sender:
                        await sender.send_signal(MARKET_CLOSED_HOLIDAY)
                    if run_logs_repo and run_id:
                        run_logs_repo.update_run(run_id, status=RunStatus.SUCCESS.value, duration_seconds=0)
                    return True
        except Exception as e:
            run_log.warning("holiday_check_failed", phase="market_check", error=str(e))

        # --- Phase: Data fetch ---
        tickers = [single_ticker] if single_ticker else list(TICKERS)
        fetcher = MarketDataFetcher(ohlcv_repo=ohlcv_repo)

        try:
            all_data = fetcher.fetch_all(tickers)
        except Exception as e:
            run_log.error("data_fetch_failed", phase="fetch", error=str(e))
            if run_logs_repo and run_id:
                run_logs_repo.update_run(
                    run_id,
                    status=RunStatus.FAILED.value,
                    error_message=str(e),
                    duration_seconds=time.time() - start_time,
                )
            # P1-15: Admin alert isolation — failure here doesn't crash
            if sender:
                try:
                    await sender.send_admin_alert(
                        escape_markdown_v2(
                            f"⚠️ SCAN FAILED\n"
                            f"Mode: {self._mode}\n"
                            f"Date: {self._today}\n"
                            f"Error: {e}"
                        )
                    )
                except Exception:
                    run_log.warning("admin_alert_failed_on_fetch_error", phase="notify")
            return False

        # --- Phase: Process tickers (validate, enrich, score) ---
        validator = DataValidator()
        indicators = TechnicalIndicators()
        scorer = SignalScorer()
        narrative_gen = NarrativeGenerator(run_date=self._today)

        all_signals: list[SignalResult] = []
        failed_tickers: list[str] = []
        skipped: list[dict[str, str]] = []  # P1-11: structured skip tracking

        for ticker in tickers:
            ticker_log = run_log.bind(ticker=ticker)
            result = self._process_ticker(
                ticker=ticker,
                all_data=all_data,
                validator=validator,
                indicators=indicators,
                scorer=scorer,
                narrative_gen=narrative_gen,
                signals_repo=signals_repo,
                ohlcv_repo=ohlcv_repo,
                ticker_log=ticker_log,
            )

            if result is None:
                # Ticker was skipped or failed — already tracked internally
                pass
            elif isinstance(result, dict):
                # Skip/fail info
                if result.get("status") == "failed":
                    failed_tickers.append(ticker)
                skipped.append(result)
            elif isinstance(result, list):
                all_signals.extend(result)
            elif isinstance(result, SignalResult):
                all_signals.append(result)

        # --- Phase: Classify signals ---
        exit_signals = [s for s in all_signals if s.signal_type == SignalType.EXIT]
        buy_signals = [s for s in all_signals if s.signal_type == SignalType.BUY]
        watch_signals = [s for s in all_signals if s.signal_type == SignalType.WATCH]

        exit_signals.sort(key=lambda s: s.signal_strength == "STRONG", reverse=True)
        buy_signals.sort(key=lambda s: s.score, reverse=True)

        # --- Phase: Expire old signals ---
        expired: list[dict] = []
        if signals_repo:
            try:
                expired = signals_repo.expire_old_signals()
            except Exception as e:
                run_log.warning("expire_signals_failed", phase="lifecycle", error=str(e))

        # --- Phase: Build messages ---
        messages, signal_lines = self._build_messages(
            exit_signals=exit_signals,
            buy_signals=buy_signals,
            watch_signals=watch_signals,
            expired=expired,
            signals_repo=signals_repo,
            narrative_gen=narrative_gen,
            run_id=run_id,
            run_log=run_log,
        )

        if not messages:
            # Check for active positions — avoid misleading "no signal" when positions exist
            active_positions = []
            if signals_repo:
                try:
                    active_positions = signals_repo.get_all_active_signals()
                except Exception:
                    pass

            if active_positions:
                esc = escape_markdown_v2
                pos_lines = []
                for pos in active_positions:
                    t = pos.get("ticker", "?")
                    ep = pos.get("entry_price", 0)
                    tp_val = pos.get("take_profit", 0)
                    sl_val = pos.get("stop_loss", 0)

                    # Get current price from fetched data
                    current_price = 0
                    ticker_df = all_data.get(t)
                    if ticker_df is not None and not ticker_df.empty:
                        current_price = float(ticker_df.iloc[-1].get("close", 0) or 0)

                    if current_price and ep:
                        pnl_pct = (current_price - ep) / ep * 100
                        pnl_str = f"\\+{esc(f'{pnl_pct:.1f}')}%" if pnl_pct >= 0 else f"{esc(f'{pnl_pct:.1f}')}%"
                        price_info = f" → sekarang {esc(format_rupiah(current_price))} \\({pnl_str}\\)"
                    else:
                        price_info = ""

                    pos_lines.append(
                        f"▸ *${esc(t)}*: entry {esc(format_rupiah(ep))}{price_info}\n"
                        f"  TP {esc(format_rupiah(tp_val))} / SL {esc(format_rupiah(sl_val))}"
                    )
                positions_text = "\n".join(pos_lines)
                messages.append(
                    f"📊 *Daily Scan — {esc(self._today)}*\n\n"
                    f"Tidak ada sinyal baru hari ini\\.\n\n"
                    f"*Posisi aktif yang sedang dimonitor:*\n{positions_text}\n\n"
                    f"_Exit akan otomatis dikirim jika TP/SL tercapai\\._"
                )
            else:
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

        # --- Phase: Send notifications ---
        # P1-15: Signal delivery and admin alerts are isolated
        telegram_sent = 0
        telegram_failed_count = 0

        if sender and not self._dry_run:
            # Main channel delivery — all signals (BUY, EXIT, WATCH, expired)
            results = await sender.send_batch(messages)
            telegram_sent = sum(results)
            telegram_failed_count = len(results) - telegram_sent

            # Alert admin if too many tickers failed
            if len(failed_tickers) >= 5:
                try:
                    await sender.send_admin_alert(
                        escape_markdown_v2(
                            f"⚠️ HIGH FAILURE RATE\n"
                            f"Mode: {self._mode}\n"
                            f"Failed: {len(failed_tickers)}/{total} tickers\n"
                            f"Tickers: {', '.join(failed_tickers[:10])}"
                        )
                    )
                except Exception:
                    run_log.warning("admin_alert_failed_ticker_warning", phase="notify")
        else:
            telegram_sent = len(messages)

        # --- Phase: Update run log ---
        if run_logs_repo and run_id:
            if len(failed_tickers) == 0:
                run_status = RunStatus.SUCCESS.value
            elif len(failed_tickers) > 15:
                run_status = RunStatus.FAILED.value
            else:
                run_status = RunStatus.PARTIAL.value

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

        # P1-11: Log skip reasons summary
        if skipped:
            run_log.info("tickers_skipped", phase="summary", skipped=skipped)

        run_log.info(
            "run_completed",
            phase="summary",
            duration=f"{duration:.1f}s",
            signals=len(all_signals),
            failed=len(failed_tickers),
            skipped=len(skipped),
        )

        return len(failed_tickers) <= 15

    # --- Pipeline stage methods (P1-9) ---

    def _process_ticker(
        self,
        *,
        ticker: str,
        all_data: dict[str, pd.DataFrame],
        validator: DataValidator,
        indicators: TechnicalIndicators,
        scorer: SignalScorer,
        narrative_gen: NarrativeGenerator,
        signals_repo: SignalsRepo | None,
        ohlcv_repo: OHLCVRepo | None,
        ticker_log,
    ) -> SignalResult | list[SignalResult] | dict[str, str] | None:
        """Process a single ticker through the full pipeline.

        Returns:
            SignalResult or list of them on success,
            dict with skip/fail info,
            None if nothing to report.
        """
        try:
            # 1. Get raw data
            df = all_data.get(ticker)
            if df is None or df.empty:
                return {"ticker": ticker, "status": "failed", "reason": "no_data"}

            # 2. P1-8: Handle partial candle for morning mode
            df = self._handle_partial_candle(df, ticker_log)
            if df.empty:
                return {"ticker": ticker, "status": "failed", "reason": "empty_after_candle_drop"}

            # 3. Validate
            validation = validator.validate(ticker, df)
            if not validation.is_valid:
                ticker_log.warning("validation_failed", phase="validate", errors=validation.errors)
                return {"ticker": ticker, "status": "failed", "reason": f"validation: {validation.errors[0]}"}

            for warning in validation.warnings:
                ticker_log.warning("validation_warning", phase="validate", warning=warning)

            # 4. Use cleaned DataFrame (P0-6: validator is source of truth for cleaning)
            df_clean = validation.cleaned_df if validation.cleaned_df is not None else df

            # 5. Validate OHLCV schema contract (P1-10)
            try:
                validate_ohlcv_schema(df_clean, ticker)
            except DataIntegrityError as e:
                ticker_log.warning("ohlcv_schema_failed", phase="validate", error=str(e))
                return {"ticker": ticker, "status": "skipped", "reason": "schema_violation"}

            # 6. Persist to cache
            if ohlcv_repo and not self._dry_run:
                try:
                    ohlcv_repo.upsert_batch(ticker, df_clean)
                except Exception as e:
                    ticker_log.warning("cache_upsert_failed", phase="persist", error=str(e))

            # 7. Enrich with indicators
            df_ind = indicators.compute_all(df_clean)

            # 8. Validate indicator schema (P1-10)
            try:
                validate_indicator_schema(df_ind, ticker)
            except DataIntegrityError as e:
                ticker_log.warning("indicator_schema_failed", phase="enrich", error=str(e))
                return {"ticker": ticker, "status": "skipped", "reason": "indicator_schema_violation"}

            # 9. Check for active signal (EXIT path)
            # Only BUY signals are persisted — WATCH signals are info-only
            active = signals_repo.get_active_signal(ticker) if signals_repo else None
            if active and active.get("signal_type") == "BUY":
                return self._handle_exit(
                    ticker=ticker,
                    df_ind=df_ind,
                    active=active,
                    scorer=scorer,
                    narrative_gen=narrative_gen,
                    ticker_log=ticker_log,
                )

            # 10. Score for BUY
            return self._handle_buy_scoring(
                ticker=ticker,
                df_ind=df_ind,
                scorer=scorer,
                narrative_gen=narrative_gen,
                ticker_log=ticker_log,
            )

        except (CalculationError, InsufficientDataError, StaleDataError) as e:
            ticker_log.warning("ticker_processing_error", phase="process", error=str(e))
            return {"ticker": ticker, "status": "failed", "reason": str(e)}
        except Exception as e:
            ticker_log.error("ticker_unexpected_error", phase="process", error=str(e))
            return {"ticker": ticker, "status": "failed", "reason": f"unexpected: {e}"}

    def _handle_partial_candle(self, df: pd.DataFrame, ticker_log) -> pd.DataFrame:
        """P1-8: Robust partial candle handling.

        Morning mode: always drop candle if last_date >= today (today's candle is partial).
        Closing mode: keep all candles (today's candle should be closed by now).
        """
        if self._mode == "morning" and not df.empty:
            last_date = pd.Timestamp(df.index[-1]).date()
            if last_date >= today_jakarta():
                df = df.iloc[:-1]
                ticker_log.info("dropped_partial_candle", phase="normalize", dropped_date=str(last_date))
        return df

    def _handle_exit(
        self,
        *,
        ticker: str,
        df_ind: pd.DataFrame,
        active: dict,
        scorer: SignalScorer,
        narrative_gen: NarrativeGenerator,
        ticker_log,
    ) -> SignalResult | None:
        """Handle EXIT check for a ticker with an active signal."""
        created_str = active.get("created_at", "")
        if created_str:
            created_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
            days_held = (datetime.now(tz=timezone.utc) - created_dt).days
        else:
            days_held = 99

        exit_result = scorer.check_exit(ticker, df_ind, active, days_held=days_held)
        if exit_result:
            exit_result.narrative = narrative_gen.generate_exit(exit_result, active)
            ticker_log.info(
                "exit_signal_detected",
                phase="score",
                exit_status=exit_result.exit_status.value if exit_result.exit_status else "unknown",
                reasons=exit_result.exit_reasons,
            )
            return exit_result
        return None

    def _handle_buy_scoring(
        self,
        *,
        ticker: str,
        df_ind: pd.DataFrame,
        scorer: SignalScorer,
        narrative_gen: NarrativeGenerator,
        ticker_log,
    ) -> SignalResult | None:
        """Score a ticker for BUY/WATCH signal."""
        buy_result = scorer.score_buy(ticker, df_ind)
        ticker_log.info(
            "scored",
            phase="score",
            score=buy_result.score,
            type=buy_result.signal_type.value,
            confluence=buy_result.confluence_count,
        )

        if buy_result.signal_type in (SignalType.BUY, SignalType.WATCH):
            buy_result.narrative = narrative_gen.generate_buy(buy_result)
            return buy_result
        return None

    def _build_messages(
        self,
        *,
        exit_signals: list[SignalResult],
        buy_signals: list[SignalResult],
        watch_signals: list[SignalResult],
        expired: list[dict],
        signals_repo: SignalsRepo | None,
        narrative_gen: NarrativeGenerator,
        run_id: str | None,
        run_log,
    ) -> tuple[list[str], list[str]]:
        """Build all message lists for Telegram delivery.

        All signals go to main channel — admin only gets errors.
        """
        messages: list[str] = []
        signal_lines: list[str] = []

        for sig in exit_signals:
            active = signals_repo.get_active_signal(sig.ticker) if signals_repo else None
            messages.append(format_exit_message(sig, active or {}))
            signal_lines.append(f"🔴 EXIT {sig.ticker}")

            if signals_repo and active:
                close_price = int(sig.indicator_snapshot.get("close", 0))

                # P0-5: Use exit_status from scorer (deterministic priority)
                status = sig.exit_status or SignalStatus.CLOSED_EXIT_SIGNAL

                try:
                    signals_repo.close_signal(
                        active["id"],
                        status,
                        close_price,
                        active.get("entry_price", 0),
                    )
                except Exception as e:
                    run_log.error("close_signal_failed", phase="persist", ticker=sig.ticker, error=str(e))

        for sig in buy_signals:
            messages.append(format_buy_message(sig))
            signal_lines.append(f"🟢 BUY {sig.ticker} (skor: {sig.score})")
            if signals_repo and run_id:
                try:
                    signals_repo.create_signal(sig, run_id=run_id)
                except Exception as e:
                    run_log.error("persist_signal_failed", phase="persist", ticker=sig.ticker, error=str(e))

        # WATCH signals — transparent to channel, NOT persisted to DB
        for sig in watch_signals:
            messages.append(format_watch_message(sig))
            signal_lines.append(f"👁 WATCH {sig.ticker} (skor: {sig.score})")

        # Expired signals — transparent to channel
        for exp in expired:
            exp_ticker = exp.get("ticker", "?")
            days_active = (
                datetime.now(tz=timezone.utc)
                - datetime.fromisoformat(exp["created_at"].replace("Z", "+00:00"))
            ).days
            messages.append(
                escape_markdown_v2(narrative_gen.generate_expired(exp_ticker, days_active))
            )
            signal_lines.append(f"⏰ EXPIRED {exp_ticker}")

        return messages, signal_lines

    async def run_weekly_report(self) -> bool:
        """Generate and send weekly performance report."""
        run_log = log.bind(mode="weekly", run_date=self._today)

        if not self._dry_run:
            try:
                validate_env()
            except ConfigurationError as e:
                run_log.error("config_validation_failed", error=str(e))
                return False

        if not self._dry_run:
            db = get_client()
            signals_repo = SignalsRepo(db)
            sender = TelegramSender(
                bot_token=get_env("TELEGRAM_BOT_TOKEN"),
                chat_id=get_env("TELEGRAM_CHAT_ID"),
                admin_chat_id=get_env("TELEGRAM_ADMIN_CHAT_ID"),
            )
        else:
            return True

        try:
            closed = signals_repo.get_all_closed_signals()
            active_count = signals_repo.get_active_signals_count()
        except Exception as e:
            run_log.error("weekly_report_db_failed", error=str(e))
            return False

        # Filter to last 7 days
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=7)
        recent = []
        for sig in closed:
            closed_at = sig.get("closed_at", "")
            if closed_at:
                try:
                    dt = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
                    if dt >= cutoff:
                        recent.append(sig)
                except (ValueError, TypeError):
                    pass

        if not recent:
            run_log.info("weekly_report_no_closed_signals")
            return True

        # Calculate metrics
        wins = sum(1 for s in recent if s.get("status") == SignalStatus.CLOSED_TP.value)
        losses = sum(1 for s in recent if s.get("status") == SignalStatus.CLOSED_SL.value)
        exits = sum(1 for s in recent if s.get("status") == SignalStatus.CLOSED_EXIT_SIGNAL.value)
        total_closed = wins + losses + exits
        win_rate = (wins / total_closed * 100) if total_closed else 0.0

        returns = [s.get("exit_pct", 0) or 0 for s in recent]
        avg_return = sum(returns) / len(returns) if returns else 0.0

        # Top performers by return
        sorted_signals = sorted(recent, key=lambda s: s.get("exit_pct", 0) or 0, reverse=True)
        top_performers = []
        for s in sorted_signals[:5]:
            top_performers.append({
                "ticker": s.get("ticker", "?"),
                "win_rate_pct": 100.0 if (s.get("exit_pct", 0) or 0) > 0 else 0.0,
                "avg_return_pct": s.get("exit_pct", 0) or 0,
            })

        message = format_weekly_performance_summary(
            date_str=self._today,
            total_closed=total_closed,
            wins=wins,
            losses=losses,
            win_rate_pct=win_rate,
            avg_return_pct=avg_return,
            top_performers=top_performers,
            active_count=active_count,
        )

        success = await sender.send_signal(message)
        run_log.info("weekly_report_sent", success=success, total_closed=total_closed)
        return success
