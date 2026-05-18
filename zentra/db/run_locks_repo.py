"""Run lock repository for scheduled scan idempotency."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from supabase import Client

from zentra.db.utils import looks_like_unique_conflict
from zentra.exceptions import DatabaseConflictError, DatabaseInsertError, DatabaseUpdateError

log = structlog.get_logger()


class RunLocksRepo:
    """Repository for the run_locks table."""

    def __init__(self, client: Client) -> None:
        self._client = client
        self._table = "run_locks"

    @staticmethod
    def build_key(mode: str, run_date: str, slot: str) -> str:
        return f"{mode}:{run_date}:{slot}"

    def acquire(self, *, mode: str, run_date: str, slot: str, run_id: str | None = None) -> dict | None:
        """Acquire a lock, returning None when the slot is already running."""
        record: dict[str, Any] = {
            "lock_key": self.build_key(mode, run_date, slot),
            "run_mode": mode,
            "run_date": run_date,
            "run_slot": slot,
            "owner_run_id": run_id,
            "acquired_at": datetime.now(tz=timezone.utc).isoformat(),
        }

        try:
            resp = self._client.table(self._table).insert(record).execute()
            lock = resp.data[0] if resp.data else record
            log.info("run_lock_acquired", lock_key=record["lock_key"], run_id=run_id)
            return lock
        except Exception as e:
            if looks_like_unique_conflict(e):
                log.warning("run_lock_conflict", lock_key=record["lock_key"], run_id=run_id)
                return None
            log.error("db_run_lock_insert_failed", lock_key=record["lock_key"], error=str(e))
            raise DatabaseInsertError(f"Failed to acquire run lock {record['lock_key']}") from e

    def release(self, lock: dict) -> None:
        lock_id = lock.get("id")
        lock_key = lock.get("lock_key")
        if not lock_id and not lock_key:
            raise DatabaseUpdateError("Cannot release run lock without id or lock_key")

        update = {"released_at": datetime.now(tz=timezone.utc).isoformat()}
        try:
            query = self._client.table(self._table).update(update)
            if lock_id:
                query = query.eq("id", lock_id)
            else:
                query = query.eq("lock_key", lock_key)
            query.execute()
            log.info("run_lock_released", lock_key=lock_key, lock_id=lock_id)
        except Exception as e:
            log.error("db_run_lock_release_failed", lock_key=lock_key, lock_id=lock_id, error=str(e))
            raise DatabaseUpdateError(f"Failed to release run lock {lock_key or lock_id}") from e
