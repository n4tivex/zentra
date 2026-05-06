"""Signals repository — CRUD operations for the signals table.

Per PRD §10.1: create, get active, close, expire signals.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from supabase import Client

from zentra.config import SCORING, SignalResult, SignalStatus
from zentra.exceptions import DatabaseError

log = structlog.get_logger()


class SignalsRepo:
    """Repository for the signals table."""

    def __init__(self, client: Client) -> None:
        self._client = client
        self._table = "signals"

    def get_active_signal(self, ticker: str) -> dict | None:
        """Get the active signal for a ticker, if any."""
        try:
            result = (
                self._client.table(self._table)
                .select("*")
                .eq("ticker", ticker)
                .eq("status", SignalStatus.ACTIVE.value)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            log.error("db_get_active_signal_failed", ticker=ticker, error=str(e))
            raise DatabaseError(f"Failed to get active signal for {ticker}") from e

    def create_signal(self, result: SignalResult, run_id: str | None = None) -> dict:
        """Insert a new signal record."""
        record: dict[str, Any] = {
            "ticker": result.ticker,
            "signal_type": result.signal_type.value,
            "signal_strength": result.signal_strength.value,
            "score": result.score,
            "confluence_count": result.confluence_count,
            "entry_price": result.entry_price,
            "stop_loss": result.stop_loss,
            "take_profit": result.take_profit,
            "risk_pct": result.risk_pct,
            "reward_pct": result.reward_pct,
            "rr_ratio": result.rr_ratio,
            "narrative_text": result.narrative or "",
            "indicator_snapshot": result.indicator_snapshot,
            "status": SignalStatus.ACTIVE.value,
        }
        if run_id:
            record["run_id"] = run_id

        try:
            resp = self._client.table(self._table).insert(record).execute()
            log.info("signal_created", ticker=result.ticker, type=result.signal_type.value)
            return resp.data[0] if resp.data else record
        except Exception as e:
            log.error("db_create_signal_failed", ticker=result.ticker, error=str(e))
            raise DatabaseError(f"Failed to create signal for {result.ticker}") from e

    def close_signal(
        self,
        signal_id: str,
        status: SignalStatus,
        exit_price: int,
        entry_price: int,
    ) -> None:
        """Close an active signal with exit details."""
        exit_pct = ((exit_price - entry_price) / entry_price * 100) if entry_price else 0

        try:
            self._client.table(self._table).update({
                "status": status.value,
                "exit_price": exit_price,
                "exit_pct": round(exit_pct, 2),
                "closed_at": datetime.now(tz=timezone.utc).isoformat(),
            }).eq("id", signal_id).execute()
            log.info("signal_closed", signal_id=signal_id, status=status.value)
        except Exception as e:
            log.error("db_close_signal_failed", signal_id=signal_id, error=str(e))
            raise DatabaseError(f"Failed to close signal {signal_id}") from e

    def expire_old_signals(self) -> list[dict]:
        """Find and expire signals older than SIGNAL_EXPIRY_DAYS."""
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=SCORING.SIGNAL_EXPIRY_DAYS)
        try:
            result = (
                self._client.table(self._table)
                .select("*")
                .eq("status", SignalStatus.ACTIVE.value)
                .lt("created_at", cutoff.isoformat())
                .execute()
            )
            expired = result.data or []

            for signal in expired:
                self._client.table(self._table).update({
                    "status": SignalStatus.EXPIRED.value,
                    "closed_at": datetime.now(tz=timezone.utc).isoformat(),
                }).eq("id", signal["id"]).execute()

            if expired:
                log.info("signals_expired", count=len(expired))
            return expired
        except Exception as e:
            log.error("db_expire_signals_failed", error=str(e))
            raise DatabaseError(f"Failed to expire old signals") from e

    def get_all_closed_signals(self) -> list[dict]:
        """Get all closed signals for performance tracking."""
        try:
            result = (
                self._client.table(self._table)
                .select("*")
                .in_("status", [
                    SignalStatus.CLOSED_TP.value,
                    SignalStatus.CLOSED_SL.value,
                    SignalStatus.CLOSED_EXIT_SIGNAL.value,
                ])
                .execute()
            )
            return result.data or []
        except Exception as e:
            log.error("db_get_closed_signals_failed", error=str(e))
            raise DatabaseError("Failed to get closed signals") from e

    def get_active_signals_count(self) -> int:
        """Get the total number of currently active signals."""
        try:
            # Supabase python client doesn't support count() elegantly with select without data, 
            # so we just select id.
            result = (
                self._client.table(self._table)
                .select("id")
                .eq("status", SignalStatus.ACTIVE.value)
                .execute()
            )
            return len(result.data) if result.data else 0
        except Exception as e:
            log.error("db_get_active_count_failed", error=str(e))
            return 0
