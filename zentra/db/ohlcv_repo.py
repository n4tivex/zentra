"""OHLCV cache repository — cache check, upsert, cleanup.

Per PRD §5.1 (cache logic) and §10.2 (schema).
"""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import structlog
from supabase import Client

from zentra.config import DATA
from zentra.exceptions import DatabaseError
from zentra.runtime import today_jakarta

log = structlog.get_logger()


class OHLCVRepo:
    """Repository for the ohlcv_cache table."""

    def __init__(self, client: Client) -> None:
        self._client = client
        self._table = "ohlcv_cache"

    def get_cached_data(self, ticker: str, min_rows: int = 30) -> pd.DataFrame | None:
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
            required = {"trade_date", "open", "high", "low", "close", "volume"}
            if not required.issubset(set(df.columns)):
                return None

            df["trade_date"] = pd.to_datetime(df["trade_date"])
            df = df.set_index("trade_date").sort_index()
            df = df[~df.index.duplicated(keep="last")]

            for col in ["open", "high", "low", "close"]:
                df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")

            df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype("int64")
            df.index.name = "date"

            last_date = df.index[-1].date()
            if (today_jakarta() - last_date).days > 2:
                log.info("cache_stale", ticker=ticker, last_date=str(last_date))
                return None

            log.info("cache_hit", ticker=ticker, rows=len(df))
            return df
        except Exception as e:
            log.warning("cache_check_failed", ticker=ticker, error=str(e))
            return None

    def upsert_batch(self, ticker: str, df: pd.DataFrame) -> None:
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
            self._client.table(self._table).upsert(
                rows,
                on_conflict="ticker,trade_date",
            ).execute()
            log.info("ohlcv_cached", ticker=ticker, rows=len(rows))
        except Exception as e:
            log.error("ohlcv_cache_failed", ticker=ticker, error=str(e))
            raise DatabaseError(f"Failed to cache OHLCV for {ticker}") from e

    def cleanup_old_data(self, retention_days: int = DATA.OHLCV_RETENTION_DAYS) -> int:
        cutoff = (today_jakarta() - timedelta(days=retention_days)).strftime("%Y-%m-%d")

        try:
            before = (
                self._client.table(self._table)
                .select("trade_date")
                .lt("trade_date", cutoff)
                .execute()
            )

            rows_to_delete = len(before.data) if before.data else 0

            if rows_to_delete == 0:
                return 0

            self._client.table(self._table).delete().lt("trade_date", cutoff).execute()

            log.info("ohlcv_cleanup", deleted=rows_to_delete, cutoff=cutoff)
            return rows_to_delete
        except Exception as e:
            log.error("ohlcv_cleanup_failed", error=str(e))
            raise DatabaseError("Failed to cleanup old OHLCV data") from e
