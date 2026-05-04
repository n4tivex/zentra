"""Run logs repository — tracking execution metadata.

Per PRD §10.3: create, update, query run logs.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import structlog
from supabase import Client

from zentra.exceptions import DatabaseError

log = structlog.get_logger()


class RunLogsRepo:
    """Repository for the run_logs table."""

    def __init__(self, client: Client) -> None:
        self._client = client
        self._table = "run_logs"

    def create_run(self, mode: str) -> str:
        """Create a new run log and return its ID."""
        record: dict[str, Any] = {
            "run_mode": mode,
            "status": "RUNNING",
            "github_run_id": os.getenv("GITHUB_RUN_ID", "local"),
        }
        try:
            resp = self._client.table(self._table).insert(record).execute()
            run_id = resp.data[0]["id"] if resp.data else ""
            log.info("run_created", run_id=run_id, mode=mode)
            return run_id
        except Exception as e:
            log.error("db_create_run_failed", error=str(e))
            raise DatabaseError(f"Failed to create run log") from e

    def update_run(
        self,
        run_id: str,
        *,
        status: str,
        duration_seconds: float | None = None,
        tickers_scanned: int | None = None,
        tickers_failed: list[str] | None = None,
        signals_generated: int | None = None,
        buy_signals: int | None = None,
        exit_signals: int | None = None,
        watch_signals: int | None = None,
        telegram_sent: int | None = None,
        telegram_failed: int | None = None,
        error_message: str | None = None,
    ) -> None:
        """Update a run log with completion details."""
        update: dict[str, Any] = {
            "status": status,
            "completed_at": datetime.now(tz=timezone.utc).isoformat(),
        }
        if duration_seconds is not None:
            update["duration_seconds"] = round(duration_seconds, 2)
        if tickers_scanned is not None:
            update["tickers_scanned"] = tickers_scanned
        if tickers_failed is not None:
            update["tickers_failed"] = tickers_failed
        if signals_generated is not None:
            update["signals_generated"] = signals_generated
        if buy_signals is not None:
            update["buy_signals"] = buy_signals
        if exit_signals is not None:
            update["exit_signals"] = exit_signals
        if watch_signals is not None:
            update["watch_signals"] = watch_signals
        if telegram_sent is not None:
            update["telegram_sent"] = telegram_sent
        if telegram_failed is not None:
            update["telegram_failed"] = telegram_failed
        if error_message is not None:
            update["error_message"] = error_message

        try:
            self._client.table(self._table).update(update).eq("id", run_id).execute()
            log.info("run_updated", run_id=run_id, status=status)
        except Exception as e:
            log.error("db_update_run_failed", run_id=run_id, error=str(e))
