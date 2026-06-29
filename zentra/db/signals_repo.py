"""Signals repository — CRUD operations for the signals table.

Per PRD §10.1: create, get active, close, expire signals.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from supabase import Client

from zentra.config import SCORING, VALID_TRANSITIONS, SignalResult, SignalStatus, SignalType
from zentra.db.utils import looks_like_unique_conflict
from zentra.exceptions import (
    DatabaseConflictError,
    DatabaseError,
    DatabaseInsertError,
    DatabaseUpdateError,
)

log = structlog.get_logger()


class SignalsRepo:
    """Repository for the signals table."""

    def __init__(self, client: Client) -> None:
        self._client = client
        self._table = "signals"

    def get_active_signal(self, ticker: str, signal_type: str | None = "BUY") -> dict | None:
        try:
            query = (
                self._client.table(self._table)
                .select("*")
                .eq("ticker", ticker)
                .eq("status", SignalStatus.ACTIVE.value)
            )
            if signal_type:
                query = query.eq("signal_type", signal_type)
            result = query.order("created_at", desc=True).limit(1).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            log.error("db_get_active_signal_failed", ticker=ticker, error=str(e))
            raise DatabaseError(f"Failed to get active signal for {ticker}") from e

    def get_all_active_signals(self) -> list[dict]:
        """Return all currently active BUY signals."""
        try:
            result = (
                self._client.table(self._table)
                .select("ticker, entry_price, take_profit, stop_loss, created_at")
                .eq("status", SignalStatus.ACTIVE.value)
                .eq("signal_type", "BUY")
                .order("created_at", desc=True)
                .execute()
            )
            return result.data or []
        except Exception as e:
            log.error("db_get_all_active_failed", error=str(e))
            raise DatabaseError("Failed to get active signals") from e

    def create_signal(self, result: SignalResult, run_id: str | None = None) -> dict:
        """Insert a new signal record with active dedup protection.

        Only BUY signals are dedup-protected — WATCH and EXIT signals pass through.
        """

        if result.signal_type == SignalType.BUY:
            existing = self.get_active_signal(result.ticker, signal_type="BUY")
            if existing and existing.get("signal_type") == "BUY":
                log.warning(
                    "duplicate_active_signal_blocked",
                    ticker=result.ticker,
                    existing_id=existing.get("id"),
                )
                return existing

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
            if looks_like_unique_conflict(e):
                existing_after_conflict = self.get_active_signal(result.ticker)
                if existing_after_conflict and existing_after_conflict.get("signal_type") == "BUY":
                    log.warning(
                        "signal_dedup_conflict",
                        ticker=result.ticker,
                        existing_id=existing_after_conflict.get("id"),
                    )
                    return existing_after_conflict
                log.error("db_create_signal_conflict_unresolved", ticker=result.ticker, error=str(e))
                raise DatabaseConflictError(
                    f"Signal insert conflict for {result.ticker}, but no active BUY was found"
                ) from e
            log.error("db_create_signal_failed", ticker=result.ticker, error=str(e))
            raise DatabaseInsertError(f"Failed to create signal for {result.ticker}") from e

    @staticmethod
    def _validate_transition(current: SignalStatus, target: SignalStatus) -> None:
        """Validate that a status transition is legal per P1-13 lifecycle."""
        allowed = VALID_TRANSITIONS.get(current, ())
        if target not in allowed:
            raise DatabaseError(
                f"Invalid signal transition: {current.value} → {target.value}. "
                f"Allowed: {[s.value for s in allowed]}"
            )

    def close_signal(
        self,
        signal_id: str,
        status: SignalStatus,
        exit_price: int,
        entry_price: int,
    ) -> None:
        # Validate transition from ACTIVE
        self._validate_transition(SignalStatus.ACTIVE, status)

        exit_pct = ((exit_price - entry_price) / entry_price * 100) if entry_price else 0

        try:
            resp = self._client.table(self._table).update({
                "status": status.value,
                "exit_price": exit_price,
                "exit_pct": round(exit_pct, 2),
                "closed_at": datetime.now(tz=UTC).isoformat(),
            }).eq("id", signal_id).eq("status", SignalStatus.ACTIVE.value).execute()

            if isinstance(resp.data, list) and len(resp.data) == 0:
                existing = self._get_signal_by_id(signal_id)
                existing_status = existing.get("status") if existing else None
                if existing_status == status.value:
                    log.info("signal_close_idempotent", signal_id=signal_id, status=status.value)
                    return
                log.warning(
                    "signal_close_no_rows",
                    signal_id=signal_id,
                    requested_status=status.value,
                    existing_status=existing_status,
                )
                raise DatabaseUpdateError(f"Signal {signal_id} was not active when close was requested")

            log.info("signal_closed", signal_id=signal_id, status=status.value)
        except DatabaseError:
            raise
        except Exception as e:
            log.error("db_close_signal_failed", signal_id=signal_id, error=str(e))
            raise DatabaseUpdateError(f"Failed to close signal {signal_id}") from e

    def expire_old_signals(self) -> list[dict]:
        now = datetime.now(tz=UTC)
        cutoff_buy = now - timedelta(days=SCORING.SIGNAL_EXPIRY_DAYS)
        cutoff_watch = now - timedelta(days=1)

        try:
            result = (
                self._client.table(self._table)
                .select("*")
                .eq("status", SignalStatus.ACTIVE.value)
                .execute()
            )

            expired: list[dict] = []
            for row in (result.data or []):
                created = row.get("created_at", "")
                if not created:
                    continue
                st = row.get("signal_type", "BUY")
                cutoff = cutoff_watch if st == "WATCH" else cutoff_buy
                if datetime.fromisoformat(created.replace("Z", "+00:00")) >= cutoff:
                    continue
                expired.append(row)
                # Validate transition
                self._validate_transition(SignalStatus.ACTIVE, SignalStatus.EXPIRED)
                resp = self._client.table(self._table).update({
                    "status": SignalStatus.EXPIRED.value,
                    "closed_at": now.isoformat(),
                }).eq("id", row["id"]).eq("status", SignalStatus.ACTIVE.value).execute()
                if isinstance(resp.data, list) and len(resp.data) == 0:
                    log.info("signal_expire_idempotent", signal_id=row["id"])

            if expired:
                log.info("signals_expired", count=len(expired))

            return expired
        except DatabaseError:
            raise
        except Exception as e:
            log.error("db_expire_signals_failed", error=str(e))
            raise DatabaseUpdateError("Failed to expire old signals") from e

    def _get_signal_by_id(self, signal_id: str) -> dict | None:
        try:
            result = (
                self._client.table(self._table)
                .select("*")
                .eq("id", signal_id)
                .limit(1)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            log.error("db_get_signal_by_id_failed", signal_id=signal_id, error=str(e))
            raise DatabaseError(f"Failed to get signal {signal_id}") from e

    def get_all_closed_signals(self) -> list[dict]:
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

    def watch_exists_today(self, ticker: str) -> bool:
        """Check if a WATCH signal was already created today for this ticker."""
        today_start = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            result = (
                self._client.table(self._table)
                .select("id")
                .eq("ticker", ticker)
                .eq("signal_type", "WATCH")
                .eq("status", SignalStatus.ACTIVE.value)
                .gte("created_at", today_start.isoformat())
                .limit(1)
                .execute()
            )
            return len(result.data) > 0 if result.data else False
        except Exception as e:
            log.error("db_watch_exists_failed", ticker=ticker, error=str(e))
            return False

    def get_active_signals_count(self) -> int:
        try:
            result = (
                self._client.table(self._table)
                .select("id")
                .eq("status", SignalStatus.ACTIVE.value)
                .execute()
            )
            return len(result.data) if result.data else 0
        except Exception as e:
            log.error("db_get_active_count_failed", error=str(e))
            raise DatabaseError("Failed to count active signals") from e
