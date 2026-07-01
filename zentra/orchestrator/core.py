"""ZENTRA Orchestrator — core coordinator with run orchestration."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta

import structlog

import zentra.orchestrator as _orch
from zentra.analysis.indicators import TechnicalIndicators
from zentra.analysis.scorer import SignalScorer
from zentra.config import (
    TICKERS,
    RunStatus,
    SignalResult,
    SignalStatus,
    SignalType,
    get_env,
)
from zentra.data.fetcher import FetchCoverage, MarketDataFetcher
from zentra.data.validator import DataValidator
from zentra.db.ohlcv_repo import OHLCVRepo
from zentra.db.run_locks_repo import RunLocksRepo
from zentra.exceptions import ConfigurationError
from zentra.market_calendar import MarketCalendar
from zentra.narrative.blocks import MARKET_CLOSED_HOLIDAY, MARKET_CLOSED_WEEKEND
from zentra.narrative.generator import NarrativeGenerator
from zentra.telegram.formatter import (
    _pct_str,
    escape_markdown_v2,
    format_active_positions_message,
    format_daily_summary,
    format_no_signal_message,
    format_rupiah,
    format_weekly_performance_summary,
)

log = structlog.get_logger()


class ZENTRAOrchestrator:
    def __init__(self, mode: str = "morning", dry_run: bool = False) -> None:
        self._mode = mode
        self._dry_run = dry_run
        self._today = _orch.today_jakarta().strftime("%Y-%m-%d")
        self._run_slot = os.getenv("ZENTRA_SCHEDULE_SLOT", mode)
        self._market_calendar = MarketCalendar.from_env()

    @staticmethod
    def _classify_run_status(
        *,
        failed_count: int,
        coverage: FetchCoverage,
        telegram_failed: int,
        persistence_failures: list[str],
    ) -> str:
        if failed_count == 0 and not coverage.is_partial and telegram_failed == 0 and not persistence_failures:
            return RunStatus.SUCCESS.value
        if failed_count > 15 or coverage.coverage_ratio < 0.8:
            return RunStatus.FAILED.value
        return RunStatus.PARTIAL.value

    async def run(self, single_ticker: str | None = None) -> bool:
        start_time = time.time()

        # P2-19: Bind structured context for all logging in this run
        run_log = log.bind(mode=self._mode, run_date=self._today)

        # --- Phase: Config validation ---
        if not self._dry_run:
            try:
                _orch.validate_env()
            except ConfigurationError as e:
                run_log.error("config_validation_failed", phase="init", error=str(e))
                return False

        # --- Phase: Initialize services ---
        if not self._dry_run:
            db = _orch.get_client()
            signals_repo = _orch.SignalsRepo(db)
            ohlcv_repo = OHLCVRepo(db)
            run_logs_repo = _orch.RunLogsRepo(db)
            locks_repo = RunLocksRepo(db)
            sender = _orch.TelegramSender(
                bot_token=get_env("TELEGRAM_BOT_TOKEN"),
                chat_id=get_env("TELEGRAM_CHAT_ID"),
                admin_chat_id=get_env("TELEGRAM_ADMIN_CHAT_ID"),
            )
        else:
            signals_repo = None
            ohlcv_repo = None
            run_logs_repo = None
            locks_repo = None
            sender = None

        run_id = None
        run_lock = None
        if run_logs_repo:
            try:
                run_id = run_logs_repo.create_run(self._mode, run_slot=self._run_slot)
                run_log = run_log.bind(run_id=run_id)
            except Exception as e:
                run_log.error("run_log_creation_failed", phase="init", error=str(e))
                await self._send_admin_alert(
                    sender,
                    run_log,
                    "\n".join(
                        [
                            "SCAN FAILED",
                            f"Mode: {self._mode}",
                            f"Date: {self._today}",
                            "Category: db_insert",
                            f"Error: {e}",
                        ]
                    ),
                    "admin_alert_failed_on_run_log_create",
                )
                return False

        if locks_repo:
            try:
                run_lock = locks_repo.acquire(
                    mode=self._mode,
                    run_date=self._today,
                    slot=self._run_slot,
                    run_id=run_id,
                    run_logs_repo=run_logs_repo,
                )
            except Exception as e:
                run_log.error("run_lock_acquire_failed", phase="lock", error=str(e))
                await self._send_admin_alert(
                    sender,
                    run_log,
                    "\n".join(
                        [
                            "SCAN FAILED",
                            f"Run ID: {run_id}",
                            f"Mode: {self._mode}",
                            f"Date: {self._today}",
                            "Category: db_insert",
                            f"Error: {e}",
                        ]
                    ),
                    "admin_alert_failed_on_run_lock",
                )
                await self._update_run_log(
                    run_logs_repo,
                    run_id,
                    run_log,
                    sender,
                    status=RunStatus.FAILED.value,
                    duration_seconds=time.time() - start_time,
                    failure_category="db_insert",
                    error_message=str(e),
                )
                return False
            if run_lock is None:
                run_log.warning("duplicate_run_blocked", phase="lock", run_slot=self._run_slot)
                await self._send_admin_alert(
                    sender,
                    run_log,
                    "\n".join(
                        [
                            "DUPLICATE RUN BLOCKED",
                            f"Run ID: {run_id}",
                            f"Mode: {self._mode}",
                            f"Date: {self._today}",
                            f"Slot: {self._run_slot}",
                        ]
                    ),
                    "admin_alert_failed_on_duplicate_run",
                )
                updated = await self._update_run_log(
                    run_logs_repo,
                    run_id,
                    run_log,
                    sender,
                    status=RunStatus.SUCCESS.value,
                    duration_seconds=time.time() - start_time,
                    failure_category="duplicate_run_lock",
                    error_message=f"Duplicate run blocked for slot {self._run_slot}",
                )
                return updated

        # --- Phase: Market status check ---
        market_status = self._market_calendar.closure_reason(_orch.today_jakarta())
        if market_status == "weekend":
            run_log.info("market_closed_weekend", phase="market_check")
            sent_ok = False
            if sender:
                sent_ok = await sender.send_signal(MARKET_CLOSED_WEEKEND)
            updated = await self._update_run_log(
                run_logs_repo,
                run_id,
                run_log,
                sender,
                status=RunStatus.SUCCESS.value,
                duration_seconds=0,
                telegram_sent=1 if sent_ok else 0,
                calendar_reason=market_status,
                data_readiness_status="market_closed",
            )
            released = self._release_run_lock(locks_repo, run_lock, run_log)
            return updated and released
        if market_status in {"official_holiday", "calendar_override"}:
            run_log.info(f"market_closed_{market_status}", phase="market_check")
            sent_ok = False
            if sender:
                sent_ok = await sender.send_signal(MARKET_CLOSED_HOLIDAY)
            updated = await self._update_run_log(
                run_logs_repo,
                run_id,
                run_log,
                sender,
                status=RunStatus.SUCCESS.value,
                duration_seconds=0,
                telegram_sent=1 if sent_ok else 0,
                calendar_reason=market_status,
                data_readiness_status="market_closed",
            )
            released = self._release_run_lock(locks_repo, run_lock, run_log)
            return updated and released

        # --- Phase: Data fetch ---
        tickers = [single_ticker] if single_ticker else list(TICKERS)
        fetcher = MarketDataFetcher(ohlcv_repo=ohlcv_repo)
        coverage = FetchCoverage(requested_tickers=tickers)
        expected_trade_date = self._market_calendar.expected_last_trade_day(_orch.today_jakarta(), mode=self._mode)

        try:
            fetch_result = fetcher.fetch_all_with_coverage(tickers, min_latest_date=expected_trade_date)
            all_data = fetch_result.data
            coverage = fetch_result.coverage
        except Exception as e:
            run_log.error("data_fetch_failed", phase="fetch", error=str(e))
            coverage = fetcher.last_coverage
            admin_alert_sent = False
            # P1-15: Admin alert isolation — failure here doesn't crash
            if sender:
                try:
                    admin_alert_sent = await sender.send_admin_alert(
                        escape_markdown_v2(
                            f"⚠️ SCAN FAILED\n"
                            f"Run ID: {run_id}\n"
                            f"Mode: {self._mode}\n"
                            f"Date: {self._today}\n"
                            f"Category: data_provider_error\n"
                            f"Missing tickers: {', '.join(coverage.missing_tickers[:10])}\n"
                            f"Error: {e}"
                        )
                    )
                except Exception:
                    run_log.warning("admin_alert_failed_on_fetch_error", phase="notify")
            await self._update_run_log(
                run_logs_repo,
                run_id,
                run_log,
                sender,
                status=RunStatus.FAILED.value,
                error_message=str(e),
                duration_seconds=time.time() - start_time,
                fetched_count=coverage.fetched_count,
                cached_count=coverage.cached_count,
                missing_count=coverage.missing_count,
                failure_count=coverage.failure_count,
                missing_tickers=coverage.missing_tickers,
                failed_fetch_tickers=coverage.failed_tickers,
                failure_category="data_provider_error",
                admin_alert_sent=admin_alert_sent,
            )
            self._release_run_lock(locks_repo, run_lock, run_log)
            return False

        data_readiness_status, latest_trade_date, expected_trade_date = self._data_readiness_status(all_data)
        if data_readiness_status != "ready":
            run_log.warning(
                data_readiness_status,
                phase="market_check",
                latest_trade_date=str(latest_trade_date),
                expected_trade_date=str(expected_trade_date),
            )
            admin_alert_sent = await self._send_admin_alert(
                sender,
                run_log,
                "\n".join(
                    [
                        data_readiness_status.upper(),
                        f"Run ID: {run_id}",
                        f"Mode: {self._mode}",
                        f"Date: {self._today}",
                        f"Latest trade date: {latest_trade_date}",
                        f"Expected trade date: {expected_trade_date}",
                    ]
                ),
                f"admin_alert_failed_on_{data_readiness_status}",
            )
            await self._update_run_log(
                run_logs_repo,
                run_id,
                run_log,
                sender,
                status=RunStatus.FAILED.value,
                error_message=(f"{data_readiness_status}: latest={latest_trade_date}, expected={expected_trade_date}"),
                duration_seconds=time.time() - start_time,
                fetched_count=coverage.fetched_count,
                cached_count=coverage.cached_count,
                missing_count=coverage.missing_count,
                failure_count=coverage.failure_count,
                missing_tickers=coverage.missing_tickers,
                failed_fetch_tickers=coverage.failed_tickers,
                calendar_reason=market_status,
                data_readiness_status=data_readiness_status,
                failure_category=data_readiness_status,
                admin_alert_sent=admin_alert_sent,
            )
            self._release_run_lock(locks_repo, run_lock, run_log)
            return False

        if coverage.is_partial:
            run_log.warning(
                "partial_fetch",
                phase="fetch",
                fetched=coverage.fetched_count,
                cached=coverage.cached_count,
                missing=coverage.missing_count,
                failed=coverage.failure_count,
                missing_tickers=coverage.missing_tickers,
            )

        # --- Phase: Expire old signals before fresh scoring ---
        expired: list[dict] = []
        if signals_repo:
            try:
                expired = signals_repo.expire_old_signals()
            except Exception as e:
                run_log.warning("expire_signals_failed", phase="lifecycle", error=str(e))

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
            elif isinstance(result, SignalResult):
                all_signals.append(result)

        # --- Phase: Classify signals ---
        exit_signals = [s for s in all_signals if s.signal_type == SignalType.EXIT]
        buy_signals = [s for s in all_signals if s.signal_type == SignalType.BUY]
        watch_signals = [s for s in all_signals if s.signal_type == SignalType.WATCH]

        exit_signals.sort(key=lambda s: s.signal_strength == "STRONG", reverse=True)
        buy_signals.sort(key=lambda s: s.score, reverse=True)

        # --- Phase: Build messages ---
        messages, signal_lines, persistence_failures = self._build_messages(
            exit_signals=exit_signals,
            buy_signals=buy_signals,
            watch_signals=watch_signals,
            expired=expired,
            signals_repo=signals_repo,
            narrative_gen=narrative_gen,
            run_id=run_id,
            run_log=run_log,
        )
        if persistence_failures:
            run_log.error(
                "db_write_failure",
                phase="persist",
                failures=persistence_failures,
            )

        if not messages:
            # Check for active positions — avoid misleading "no signal" when positions exist
            active_positions = []
            if signals_repo:
                try:
                    active_positions = signals_repo.get_all_active_signals()
                except Exception as e:
                    run_log.error("active_positions_lookup_failed", phase="persist", error=str(e))
                    admin_alert_sent = await self._send_admin_alert(
                        sender,
                        run_log,
                        "\n".join(
                            [
                                "SCAN FAILED",
                                f"Run ID: {run_id}",
                                f"Mode: {self._mode}",
                                f"Date: {self._today}",
                                "Category: db_read",
                                f"Error: {e}",
                            ]
                        ),
                        "admin_alert_failed_on_active_positions",
                    )
                    await self._update_run_log(
                        run_logs_repo,
                        run_id,
                        run_log,
                        sender,
                        status=RunStatus.FAILED.value,
                        duration_seconds=time.time() - start_time,
                        fetched_count=coverage.fetched_count,
                        cached_count=coverage.cached_count,
                        missing_count=coverage.missing_count,
                        failure_count=coverage.failure_count,
                        missing_tickers=coverage.missing_tickers,
                        failed_fetch_tickers=coverage.failed_tickers,
                        calendar_reason=market_status,
                        data_readiness_status=data_readiness_status,
                        failure_category="db_read",
                        admin_alert_sent=admin_alert_sent,
                        error_message=str(e),
                    )
                    self._release_run_lock(locks_repo, run_lock, run_log)
                    return False

            if active_positions:
                esc = escape_markdown_v2
                pos_lines = []
                for pos in active_positions:
                    t = pos.get("ticker", "?")
                    ep = pos.get("entry_price", 0)
                    created_at = pos.get("created_at", "")

                    current_price = 0
                    ticker_df = all_data.get(t)
                    if ticker_df is not None and not ticker_df.empty:
                        current_price = float(ticker_df.iloc[-1].get("close", 0) or 0)

                    price_info = ""
                    days_info = ""
                    if current_price and ep:
                        pnl_pct = (current_price - ep) / ep * 100
                        pnl_str = _pct_str(pnl_pct)
                        price_info = f" \u2192 {esc(format_rupiah(current_price))} \\({esc(pnl_str)}\\)"
                    if created_at:
                        try:
                            created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                            held = (datetime.now(tz=UTC) - created_dt).days
                            days_info = f" \u00b7 {held} hari"
                        except (ValueError, TypeError):
                            pass

                    pos_lines.append(f"\u25b8 *\\${esc(t)}*: Entry {esc(format_rupiah(ep))}{price_info}{esc(days_info)}")

                messages.append(
                    format_active_positions_message(
                        date_str=self._today,
                        positions=pos_lines,
                        mode=self._mode,
                    )
                )
            else:
                run_log.info("no_signal_output", phase="summary")
                messages.append(format_no_signal_message(date_str=self._today, mode=self._mode))

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
                    mode=self._mode,
                )
            )

        # --- Phase: Send notifications ---
        # P1-15: Signal delivery and admin alerts are isolated
        telegram_sent = 0
        telegram_failed_count = 0
        admin_alert_sent = False

        if sender and not self._dry_run:
            # Main channel delivery — all signals (BUY, EXIT, WATCH, expired)
            results = await sender.send_batch(messages)
            telegram_sent = sum(results)
            telegram_failed_count = len(results) - telegram_sent
            if telegram_failed_count:
                run_log.error(
                    "telegram_delivery_partial",
                    phase="notify",
                    sent=telegram_sent,
                    failed=telegram_failed_count,
                )
                admin_alert_sent = await self._send_admin_alert(
                    sender,
                    run_log,
                    "\n".join(
                        [
                            "TELEGRAM DELIVERY FAILURE",
                            f"Run ID: {run_id}",
                            f"Mode: {self._mode}",
                            f"Sent: {telegram_sent}",
                            f"Failed: {telegram_failed_count}",
                        ]
                    ),
                    "admin_alert_failed_on_telegram_delivery",
                )

            # Alert admin if too many tickers failed
            if len(failed_tickers) >= 5 or coverage.missing_count > 0:
                try:
                    admin_alert_sent = await sender.send_admin_alert(
                        escape_markdown_v2(
                            f"⚠️ HIGH FAILURE RATE\nMode: {self._mode}\nFailed: {len(failed_tickers)}/{total} tickers\nTickers: {', '.join(failed_tickers[:10])}"
                        )
                    )
                except Exception:
                    run_log.warning("admin_alert_failed_ticker_warning", phase="notify")
        else:
            telegram_sent = len(messages)

        # --- Phase: Update run log ---
        failed_fetch_tickers = sorted(set(coverage.failed_tickers + coverage.missing_tickers))
        run_status = self._classify_run_status(
            failed_count=len(failed_tickers),
            coverage=coverage,
            telegram_failed=telegram_failed_count,
            persistence_failures=persistence_failures,
        )

        updated = await self._update_run_log(
            run_logs_repo,
            run_id,
            run_log,
            sender,
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
            fetched_count=coverage.fetched_count,
            cached_count=coverage.cached_count,
            missing_count=coverage.missing_count,
            failure_count=coverage.failure_count,
            missing_tickers=coverage.missing_tickers,
            failed_fetch_tickers=failed_fetch_tickers,
            calendar_reason=market_status,
            data_readiness_status=data_readiness_status,
            failure_category=("db_write" if persistence_failures else "partial_fetch" if coverage.is_partial else None),
            admin_alert_sent=admin_alert_sent,
            error_message="; ".join(persistence_failures) if persistence_failures else None,
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
            status=run_status,
            coverage_ratio=round(coverage.coverage_ratio, 3),
        )

        released = self._release_run_lock(locks_repo, run_lock, run_log)
        return updated and released and run_status != RunStatus.FAILED.value

    async def run_weekly_report(self) -> bool:
        """Generate and send weekly performance report."""
        run_log = log.bind(mode="weekly", run_date=self._today)
        start_time = datetime.now(tz=UTC)

        if not self._dry_run:
            try:
                _orch.validate_env()
            except ConfigurationError as e:
                run_log.error("config_validation_failed", error=str(e))
                return False

        if not self._dry_run:
            db = _orch.get_client()
            signals_repo = _orch.SignalsRepo(db)
            run_logs_repo = _orch.RunLogsRepo(db)
            run_id = run_logs_repo.create_run("weekly", run_slot="weekly_report")
            sender = _orch.TelegramSender(
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
            run_logs_repo.update_run(
                run_id,
                status=RunStatus.FAILED,
                duration_seconds=(datetime.now(tz=UTC) - start_time).total_seconds(),
                error_message=str(e),
            )
            return False

        # Filter to last 7 days
        cutoff = datetime.now(tz=UTC) - timedelta(days=7)
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
            run_logs_repo.update_run(
                run_id,
                status=RunStatus.SUCCESS,
                duration_seconds=(datetime.now(tz=UTC) - start_time).total_seconds(),
            )
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
            top_performers.append(
                {
                    "ticker": s.get("ticker", "?"),
                    "win_rate_pct": 100.0 if (s.get("exit_pct", 0) or 0) > 0 else 0.0,
                    "avg_return_pct": s.get("exit_pct", 0) or 0,
                }
            )

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
        if not self._dry_run:
            run_logs_repo.update_run(
                run_id,
                status=RunStatus.SUCCESS if success else RunStatus.FAILED,
                duration_seconds=(datetime.now(tz=UTC) - start_time).total_seconds(),
            )
        run_log.info("weekly_report_sent", success=success, total_closed=total_closed)
        return success
