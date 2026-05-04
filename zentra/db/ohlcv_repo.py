"""OHLCV cache repository — cache check, upsert, cleanup.

Per PRD §5.1 (cache logic) and §10.2 (schema).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import structlog
from supabase import Client

from zentra.config import DATA
from zentra.exceptions import DatabaseError

log = structlog.get_logger()


class OHLCVRepo:
    """Repository for the ohlcv_cache table."""

    def __init__(self, client: Client) -> None:
        self._client = client
        self._table = "ohlcv_cache"

    def get_cached_data(self, ticker: str, min_rows: int = 30) -> pd.DataFrame | None:
        """Check if today's cache exists and has enough data."""
        try:
            result = (
                self._client.table(self._table)
                .select("trade_date, open, high, low, close, volume")
                .eq("ticker", ticker)
                .order("trade_date", desc=True)
                .limit(DATA.LOOKBACK_DAYS)
                .execute()
            )
            if not result.data or len(result.data) < min_rows:
                return None

            df = pd.DataFrame(result.data)
            df["trade_date"] = pd.to_datetime(df["trade_date"])
            df = df.set_index("trade_date").sort_index()

            # Cast types
            for col in ["open", "high", "low", "close"]:
                df[col] = df[col].astype("float64")
            df["volume"] = df["volume"].astype("int64")
            df.index.name = "date"

            # Check if data is fresh enough (today or yesterday)
            last_date = df.index[-1].date()
            today = datetime.now(tz=timezone.utc).date()
            if (today - last_date).days > 2:
                return None  # Cache is stale, re-fetch

            log.info("cache_hit", ticker=ticker, rows=len(df))
            return df
        except Exception as e:
            log.warning("cache_check_failed", ticker=ticker, error=str(e))
            return None

    def upsert_batch(self, ticker: str, df: pd.DataFrame) -> None:
        """Upsert OHLCV data for a ticker (batch operation)."""
        if df.empty:
            return

        rows = []
        for date, row in df.iterrows():
            rows.append({
                "ticker": ticker,
                "trade_date": pd.Timestamp(date).strftime("%Y-%m-%d"),
                "open": round(float(row["open"]), 2),
                "high": round(float(row["high"]), 2),
                "low": round(float(row["low"]), 2),
                "close": round(float(row["close"]), 2),
                "volume": int(row["volume"]),
            })

        try:
            # Batch upsert — single round trip per PRD §13.2
            self._client.table(self._table).upsert(
                rows, on_conflict="ticker,trade_date"
            ).execute()
            log.info("ohlcv_cached", ticker=ticker, rows=len(rows))
        except Exception as e:
            log.error("ohlcv_cache_failed", ticker=ticker, error=str(e))
            raise DatabaseError(f"Failed to cache OHLCV for {ticker}") from e

    def cleanup_old_data(self, retention_days: int = DATA.OHLCV_RETENTION_DAYS) -> int:
        """Delete data older than retention_days. Returns count deleted."""
        cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=retention_days)).strftime(
            "%Y-%m-%d"
        )
        try:
            result = (
                self._client.table(self._table)
                .delete()
                .lt("trade_date", cutoff)
                .execute()
            )
            count = len(result.data) if result.data else 0
            log.info("ohlcv_cleanup", deleted=count, cutoff=cutoff)
            return count
        except Exception as e:
            log.error("ohlcv_cleanup_failed", error=str(e))
            raise DatabaseError(f"Failed to cleanup old OHLCV data") from e
