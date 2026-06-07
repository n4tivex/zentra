"""Run lock repository for scheduled scan idempotency."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from supabase import Client

from zentra.db.utils import looks_like_unique_conflict
from zentra.exceptions import DatabaseDeleteError, DatabaseInsertError, DatabaseUpdateError

log = structlog.get_logger()

LOCK_THROTTLE_HOURS = 2


class RunLocksRepo:
    """Repository for the run_locks table."""

    def __init__(self, client: Client) -> None:
        self._client = client
        self._table = "run_locks"

    @staticmethod
    def build_key(mode: str, run_date: str, slot: str) -> str:
        return f"{mode}:{run_date}:{slot}"

    def acquire(self, *, mode: str, run_date: str, slot: str, run_id: str | None = None, run_logs_repo: object | None = None) -> dict | None:
        """Acquire a lock, returning None when the slot is already running.

        Two layers of protection:
        1. Recent lock check — prevents sequential duplicates within N hours
           (e.g. cronjob.org triggering midday 4× in one hour).
        2. Unique constraint — prevents truly concurrent runs.

        If run_logs_repo is provided, Layer 1 checks if the previous run FAILED.
        If so, the old lock is deleted and the new acquisition is allowed (retry window).
        """
        lock_key = self.build_key(mode, run_date, slot)
        now = datetime.now(tz=timezone.utc)

        # Layer 1: Check for recent lock (sequential duplicate guard)
        try:
            cutoff = (now - timedelta(hours=LOCK_THROTTLE_HOURS)).isoformat()
            recent = (
                self._client.table(self._table)
                .select("id, owner_run_id")
                .eq("lock_key", lock_key)
                .gte("acquired_at", cutoff)
                .execute()
            )
            if recent.data:
                existing = recent.data[0]
                # If run_logs_repo is available, check if the previous run FAILED
                if run_logs_repo and existing.get("owner_run_id"):
                    try:
                        getter = getattr(run_logs_repo, "get_run", None)
                        if callable(getter):
                            prev_run = getter(existing["owner_run_id"])
                            if prev_run and prev_run.get("status") == "FAILED":
                                log.info(
                                    "run_lock_retry_allowed",
                                    lock_key=lock_key,
                                    previous_run_id=existing["owner_run_id"],
                                )
                                self._client.table(self._table).delete().eq("id", existing["id"]).execute()
                                # Proceed to Layer 2 insert
                                pass
                            else:
                                log.warning(
                                    "run_lock_throttled",
                                    lock_key=lock_key,
                                    run_id=run_id,
                                    existing_id=existing["id"],
                                )
                                return None
                        else:
                            return None
                    except Exception:
                        return None
                else:
                    log.warning(
                        "run_lock_throttled",
                        lock_key=lock_key,
                        run_id=run_id,
                        existing_id=existing["id"],
                    )
                    return None
        except Exception as e:
            log.error("run_lock_recent_check_failed", lock_key=lock_key, error=str(e))

        # Layer 2: Insert with unique constraint (concurrent guard)
        record: dict[str, Any] = {
            "lock_key": lock_key,
            "run_mode": mode,
            "run_date": run_date,
            "run_slot": slot,
            "owner_run_id": run_id,
            "acquired_at": now.isoformat(),
        }

        try:
            resp = self._client.table(self._table).insert(record).execute()
            lock = resp.data[0] if resp.data else record
            log.info("run_lock_acquired", lock_key=lock_key, run_id=run_id)
            return lock
        except Exception as e:
            if looks_like_unique_conflict(e):
                log.warning("run_lock_conflict", lock_key=lock_key, run_id=run_id)
                return None
            log.error("db_run_lock_insert_failed", lock_key=lock_key, error=str(e))
            raise DatabaseInsertError(f"Failed to acquire run lock {lock_key}") from e

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

    def cleanup_old_locks(self, retention_days: int = 90) -> int:
        """Delete run locks older than retention_days."""
        cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=retention_days)).isoformat()
        try:
            before = (
                self._client.table(self._table)
                .select("id")
                .lt("acquired_at", cutoff)
                .execute()
            )
            rows_to_delete = len(before.data) if before.data else 0
            if rows_to_delete == 0:
                return 0
            self._client.table(self._table).delete().lt("acquired_at", cutoff).execute()
            log.info("run_locks_cleanup", deleted=rows_to_delete, cutoff=cutoff, retention_days=retention_days)
            return rows_to_delete
        except Exception as e:
            log.error("run_locks_cleanup_failed", error=str(e))
            raise DatabaseDeleteError("Failed to cleanup old run locks") from e
