"""Monthly cleanup script — deletes old data from all tables.

Per PRD §11.1 (monthly_cleanup workflow) and §10.2 (90 day retention).
P1-14: Proper error handling and non-zero exit code on failure.

Cleanup targets:
  - ohlcv_cache : 90 days (PRD §10.2)
  - run_locks   : 90 days
  - run_logs    : 180 days
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import structlog
from dotenv import load_dotenv

load_dotenv()

from zentra.db.client import get_client  # noqa: E402
from zentra.db.ohlcv_repo import OHLCVRepo  # noqa: E402
from zentra.db.run_locks_repo import RunLocksRepo  # noqa: E402
from zentra.db.run_logs_repo import RunLogsRepo  # noqa: E402

log = structlog.get_logger()


def main() -> None:
    try:
        client = get_client()

        deleted_ohlcv = OHLCVRepo(client).cleanup_old_data()
        deleted_locks = RunLocksRepo(client).cleanup_old_locks()
        deleted_logs = RunLogsRepo(client).cleanup_old_logs()

        total = deleted_ohlcv + deleted_locks + deleted_logs
        log.info("cleanup_complete", ohlcv=deleted_ohlcv, locks=deleted_locks, logs=deleted_logs, total=total)
        print(f"Cleanup complete: {total} rows deleted (ohlcv={deleted_ohlcv}, locks={deleted_locks}, logs={deleted_logs})")
    except Exception as e:
        log.error("cleanup_failed", error=str(e))
        print(f"Cleanup FAILED: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
