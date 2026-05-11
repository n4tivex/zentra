"""Market data fetcher — retrieves OHLCV data from yfinance.

Per PRD §5.1: batch download, .JK suffix, cache check, retry logic.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

import pandas as pd
import structlog
import yfinance as yf
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from zentra.config import DATA
from zentra.exceptions import DataFetchError, TickerNotFoundError

log = structlog.get_logger()


class MarketDataFetcher:
    """Fetches OHLCV data from Yahoo Finance for IDX tickers."""

    def __init__(self, ohlcv_repo: object | None = None) -> None:
        self._ohlcv_repo = ohlcv_repo

    def fetch_all(self, tickers: list[str], days: int = DATA.LOOKBACK_DAYS) -> dict[str, pd.DataFrame]:
        """Fetch OHLCV for all tickers using cache-first, batch-network fallback."""
        results: dict[str, pd.DataFrame] = {}
        missing: list[str] = []

        for ticker in tickers:
            cached = self._get_cached(ticker)
            if cached is not None and not cached.empty:
                results[ticker] = cached
                log.info("ticker_cache_hit", ticker=ticker, rows=len(cached))
            else:
                missing.append(ticker)

        if missing:
            tickers_jk = [f"{t}.JK" for t in missing]
            log.info("fetching_market_data", tickers=len(missing), days=days)
            try:
                raw = self._fetch_from_yahoo(tickers_jk, days)
            except Exception as e:
                if results:
                    log.warning("batch_fetch_failed_partial_return", error=str(e), cached=len(results))
                    return results
                raise DataFetchError(f"Batch fetch failed: {e}") from e

            for ticker in missing:
                ticker_jk = f"{ticker}.JK"
                try:
                    df = self._extract_ticker(raw, ticker_jk)
                    if df is None or df.empty:
                        log.warning("ticker_empty", ticker=ticker)
                        continue
                    normalized = self._normalize(df)
                    results[ticker] = normalized
                    log.info("ticker_fetched", ticker=ticker, rows=len(normalized))
                except Exception as e:
                    log.warning("ticker_extract_failed", ticker=ticker, error=str(e))

        if not results:
            raise DataFetchError("All tickers failed to fetch")

        return results

    def fetch_single(self, ticker: str, days: int = DATA.LOOKBACK_DAYS) -> pd.DataFrame:
        """Fetch a single ticker. Cache-first, then network fallback."""
        cached = self._get_cached(ticker)
        if cached is not None and not cached.empty:
            return cached

        ticker_jk = f"{ticker}.JK"
        end = datetime.now(tz=timezone.utc)
        start = end - timedelta(days=days)

        try:
            df = yf.download(
                ticker_jk,
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                progress=False,
                auto_adjust=True,
            )
        except Exception as e:
            raise DataFetchError(f"Failed to fetch {ticker}: {e}") from e

        if df is None or df.empty:
            raise TickerNotFoundError(f"No data returned for {ticker}")

        return self._normalize(df)

    def _get_cached(self, ticker: str) -> pd.DataFrame | None:
        if self._ohlcv_repo is None:
            return None
        getter = getattr(self._ohlcv_repo, "get_cached_data", None)
        if not callable(getter):
            return None
        try:
            return getter(ticker)
        except Exception as e:
            log.warning("cache_lookup_failed", ticker=ticker, error=str(e))
            return None

    @retry(
        stop=stop_after_attempt(DATA.FETCH_RETRY_ATTEMPTS),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
        reraise=True,
    )
    def _fetch_from_yahoo(self, tickers_jk: list[str], days: int) -> pd.DataFrame:
        end = datetime.now(tz=timezone.utc)
        start = end - timedelta(days=days)
        df = yf.download(
            tickers_jk,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            group_by="ticker",
            progress=False,
            auto_adjust=True,
        )
        if df is None or df.empty:
            raise DataFetchError("yfinance returned empty DataFrame")
        return df

    def _extract_ticker(self, raw: pd.DataFrame, ticker_jk: str) -> pd.DataFrame | None:
        """Extract a single ticker's data from a download payload."""
        if raw is None or raw.empty:
            return None

        if isinstance(raw.columns, pd.MultiIndex):
            level0 = raw.columns.get_level_values(0)
            if ticker_jk in level0:
                return raw[ticker_jk].copy()
            bare = ticker_jk.replace(".JK", "")
            if bare in level0:
                return raw[bare].copy()
            return None

        return raw.copy()

    def _normalize(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalize column names and index."""
        df = df.copy()

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(-1)

        df.columns = [c.lower().strip() for c in df.columns]
        if "adj close" in df.columns and "close" not in df.columns:
            df = df.rename(columns={"adj close": "close"})

        expected = ["open", "high", "low", "close", "volume"]
        available = [c for c in expected if c in df.columns]
        df = df[available]

        for col in ["open", "high", "low", "close"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
        if "volume" in df.columns:
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype("int64")

        if getattr(df.index, "tz", None) is not None:
            df.index = df.index.tz_convert("UTC").tz_localize(None)
        df.index.name = "date"

        return df
