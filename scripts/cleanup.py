"""Monthly cleanup script — deletes old OHLCV cache data.

Per PRD §11.1 (monthly_cleanup workflow) and §10.2 (90 day retention).
P1-14: Proper error handling and non-zero exit code on failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add root directory to python path
sys.path.insert(0, str(Path(__file__).parent.parent))

import structlog
from dotenv import load_dotenv

load_dotenv()

from zentra.db.client import get_client
from zentra.db.ohlcv_repo import OHLCVRepo

log = structlog.get_logger()


def main() -> None:
    try:
        client = get_client()
        repo = OHLCVRepo(client)
        deleted = repo.cleanup_old_data()
        log.info("cleanup_complete", deleted=deleted)
        print(f"Cleanup complete: {deleted} rows deleted")
    except Exception as e:
        log.error("cleanup_failed", error=str(e))
        print(f"Cleanup FAILED: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
