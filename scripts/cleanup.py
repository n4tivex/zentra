"""Monthly cleanup script — deletes old OHLCV cache data.

Per PRD §11.1 (monthly_cleanup workflow) and §10.2 (90 day retention).
"""

from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

from zentra.db.client import get_client
from zentra.db.ohlcv_repo import OHLCVRepo


def main() -> None:
    client = get_client()
    repo = OHLCVRepo(client)
    deleted = repo.cleanup_old_data()
    print(f"Cleanup complete: {deleted} rows deleted")


if __name__ == "__main__":
    main()
