"""Run logs repository — tracking execution metadata.

Per PRD §10.3: create, update, query run logs.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import structlog
from supabase import Client

from zentra.config import RunStatus
from zentra.exceptions import DatabaseInsertError, DatabaseUpdateError

log = structlog.get_logger()


class RunLogsRepo:
    """Repository for the run_logs table."""

    def __init__(self, client: Client) -> None:
        self._client = client
        self._table = "run_logs"

    def create_run(self, mode: str, *, run_slot: str | None = None) -> str:
        """Create a new run log and return its ID."""
        record: dict[str, Any] = {
            "run_mode": mode,
            "status": RunStatus.RUNNING.value,
            "github_run_id": os.getenv("GITHUB_RUN_ID", "local"),
        }
        if run_slot:
            record["run_slot"] = run_slot
        try:
            resp = self._client.table(self._table).insert(record).execute()
            run_id = resp.data[0]["id"] if resp.data else ""
            if not run_id:
                raise DatabaseInsertError("Run log insert returned no id")
            log.info("run_created", run_id=run_id, mode=mode)
            return run_id
        except DatabaseInsertError:
            raise
        except Exception as e:
            log.error("db_create_run_failed", error=str(e))
            raise DatabaseInsertError("Failed to create run log") from e

    def update_run(
        self,
        run_id: str,
        *,
        status: str | RunStatus,
        duration_seconds: float | None = None,
        tickers_scanned: int | None = None,
        tickers_failed: list[str] | None = None,
        signals_generated: int | None = None,
        buy_signals: int | None = None,
        exit_signals: int | None = None,
        watch_signals: int | None = None,
        telegram_sent: int | None = None,
        telegram_failed: int | None = None,
        fetched_count: int | None = None,
        cached_count: int | None = None,
        missing_count: int | None = None,
        failure_count: int | None = None,
        missing_tickers: list[str] | None = None,
        failed_fetch_tickers: list[str] | None = None,
        calendar_reason: str | None = None,
        data_readiness_status: str | None = None,
        failure_category: str | None = None,
        admin_alert_sent: bool | None = None,
        error_message: str | None = None,
    ) -> None:
        """Update a run log with completion details."""
        status_value = status.value if isinstance(status, RunStatus) else status
        update: dict[str, Any] = {
            "status": status_value,
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
        if fetched_count is not None:
            update["fetched_count"] = fetched_count
        if cached_count is not None:
            update["cached_count"] = cached_count
        if missing_count is not None:
            update["missing_count"] = missing_count
        if failure_count is not None:
            update["failure_count"] = failure_count
        if missing_tickers is not None:
            update["missing_tickers"] = missing_tickers
        if failed_fetch_tickers is not None:
            update["failed_fetch_tickers"] = failed_fetch_tickers
        if calendar_reason is not None:
            update["calendar_reason"] = calendar_reason
        if data_readiness_status is not None:
            update["data_readiness_status"] = data_readiness_status
        if failure_category is not None:
            update["failure_category"] = failure_category
        if admin_alert_sent is not None:
            update["admin_alert_sent"] = admin_alert_sent
        if error_message is not None:
            update["error_message"] = error_message

        try:
            self._client.table(self._table).update(update).eq("id", run_id).execute()
            log.info("run_updated", run_id=run_id, status=status_value)
        except Exception as e:
            log.error("db_update_run_failed", run_id=run_id, error=str(e))
            raise DatabaseUpdateError(f"Failed to update run log {run_id}") from e
