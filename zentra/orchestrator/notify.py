"""ZENTRA Orchestrator — message building and notification helpers."""

from __future__ import annotations

import structlog

from zentra.config import SignalResult, SignalStatus
from zentra.db.signals_repo import SignalsRepo
from zentra.orchestrator.core import ZENTRAOrchestrator
from zentra.telegram.formatter import (
    _pct_str,
    escape_markdown_v2,
    format_buy_message,
    format_exit_message,
    format_expired_message,
    format_watch_message,
)
from zentra.telegram.sender import TelegramSender

log = structlog.get_logger()


async def _send_admin_alert(self: ZENTRAOrchestrator, sender: TelegramSender | None, run_log, message: str, event: str) -> bool:
    if not sender:
        return False
    try:
        sent = await sender.send_admin_alert(escape_markdown_v2(message))
        if not sent:
            run_log.warning(event, phase="notify")
        return bool(sent)
    except Exception as e:
        run_log.warning(event, phase="notify", error=str(e))
        return False


async def _update_run_log(self: ZENTRAOrchestrator, run_logs_repo, run_id: str | None, run_log, sender, **kwargs) -> bool:
    if not run_logs_repo or not run_id:
        return True
    try:
        run_logs_repo.update_run(run_id, **kwargs)
        return True
    except Exception as e:
        run_log.error("run_log_update_failed", phase="persist", error=str(e))
        await self._send_admin_alert(
            sender,
            run_log,
            "\n".join(
                [
                    "RUN LOG UPDATE FAILED",
                    f"Run ID: {run_id}",
                    f"Mode: {self._mode}",
                    f"Date: {self._today}",
                    "Category: db_update",
                    f"Error: {e}",
                ]
            ),
            "admin_alert_failed_on_run_log_update",
        )
        return False


def _build_messages(
    self,
    *,
    exit_signals: list[SignalResult],
    buy_signals: list[SignalResult],
    watch_signals: list[SignalResult],
    expired: list[dict],
    signals_repo: SignalsRepo | None,
    narrative_gen,
    run_id: str | None,
    run_log,
) -> tuple[list[str], list[str], list[str]]:
    """Build all message lists for Telegram delivery.

    All signals go to main channel — admin only gets errors.
    """
    messages: list[str] = []
    signal_lines: list[str] = []
    persistence_failures: list[str] = []

    for sig in exit_signals:
        active = signals_repo.get_active_signal(sig.ticker) if signals_repo else None
        if active and active.get("created_at"):
            sig.created_at = active["created_at"]
        messages.append(format_exit_message(sig, active or {}))
        pnl = ""
        close = sig.indicator_snapshot.get("close", 0)
        entry = (active or {}).get("entry_price", 0)
        if entry and close:
            p = (close - entry) / entry * 100
            pnl = f" \u00b7 {_pct_str(p)}"
        signal_lines.append(f"\U0001f534 EXIT {sig.ticker}{pnl}")

        if signals_repo and active:
            close_price = int(sig.indicator_snapshot.get("close", 0))
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
                persistence_failures.append(f"close_signal:{sig.ticker}:{e}")

    for sig in buy_signals:
        if signals_repo and run_id:
            try:
                created = signals_repo.create_signal(sig, run_id=run_id)
                if created and created.get("created_at"):
                    sig.created_at = created["created_at"]
            except Exception as e:
                run_log.error("persist_signal_failed", phase="persist", ticker=sig.ticker, error=str(e))
                persistence_failures.append(f"create_signal:{sig.ticker}:{e}")
        messages.append(format_buy_message(sig))
        signal_lines.append(f"\U0001f7e2 BUY {sig.ticker} \u00b7 Skor {sig.score}")

    # WATCH signals — persisted for cross-run dedup (TTL: 1 day via expire)
    seen_watch_tickers: set[str] = set()
    for sig in watch_signals:
        if sig.ticker in seen_watch_tickers:
            continue
        seen_watch_tickers.add(sig.ticker)

        if signals_repo and signals_repo.watch_exists_today(sig.ticker):
            continue

        if signals_repo and run_id:
            try:
                created = signals_repo.create_signal(sig, run_id=run_id)
                if created and created.get("created_at"):
                    sig.created_at = created["created_at"]
            except Exception as e:
                run_log.warning("watch_persist_failed", phase="persist", ticker=sig.ticker, error=str(e))

        messages.append(format_watch_message(sig))
        signal_lines.append(f"\U0001f441 WATCH {sig.ticker} \u00b7 Skor {sig.score}")

    for exp in expired:
        messages.append(format_expired_message(exp))
        st = exp.get("signal_type", "BUY")
        signal_lines.append(f"\u23f0 EXP {exp.get('ticker', '?')} \u00b7 {st}")

    return messages, signal_lines, persistence_failures


ZENTRAOrchestrator._send_admin_alert = _send_admin_alert
ZENTRAOrchestrator._update_run_log = _update_run_log
ZENTRAOrchestrator._build_messages = _build_messages
