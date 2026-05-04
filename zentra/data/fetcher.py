"""Market data fetcher — retrieves OHLCV data from yfinance.

Per PRD §5.1: batch download, .JK suffix, cache check, retry logic.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

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
        """Fetch OHLCV for all tickers via batch download.

        Returns dict of ticker -> OHLCV DataFrame.
        Partial failures do not raise — only returns successful tickers.
        Raises DataFetchError if ALL tickers fail.
        """
        tickers_jk = [f"{t}.JK" for t in tickers]
        log.info("fetching_market_data", tickers=len(tickers), days=days)

        try:
            raw = self._fetch_from_yahoo(tickers_jk, days)
        except Exception as e:
            raise DataFetchError(f"Batch fetch failed: {e}") from e

        results: dict[str, pd.DataFrame] = {}
        for ticker in tickers:
            ticker_jk = f"{ticker}.JK"
            try:
                df = self._extract_ticker(raw, ticker_jk, tickers_jk)
                if df is not None and not df.empty:
                    df = self._normalize(df)
                    results[ticker] = df
                    log.info("ticker_fetched", ticker=ticker, rows=len(df))
                else:
                    log.warning("ticker_empty", ticker=ticker)
            except Exception as e:
                log.warning("ticker_extract_failed", ticker=ticker, error=str(e))

        if not results:
            raise DataFetchError("All tickers failed to fetch")

        return results

    def fetch_single(self, ticker: str, days: int = DATA.LOOKBACK_DAYS) -> pd.DataFrame:
        """Fetch a single ticker. Raises TickerNotFoundError or DataFetchError."""
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

    @retry(
        stop=stop_after_attempt(DATA.FETCH_RETRY_ATTEMPTS),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
        reraise=True,
    )
    def _fetch_from_yahoo(self, tickers_jk: list[str], days: int) -> pd.DataFrame:
        """Batch download with retry."""
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

    def _extract_ticker(
        self, raw: pd.DataFrame, ticker_jk: str, all_tickers: list[str]
    ) -> pd.DataFrame | None:
        """Extract a single ticker's data from multi-ticker download."""
        try:
            if isinstance(raw.columns, pd.MultiIndex):
                # yfinance returns MultiIndex (Ticker, PriceType) even for single ticker
                if ticker_jk in raw.columns.get_level_values(0):
                    return raw[ticker_jk].copy()
            # Flat columns (non-MultiIndex) — return as-is
            return raw.copy()
        except KeyError:
            return None

    def _normalize(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalize column names and index."""
        df = df.copy()

        # Flatten MultiIndex columns if present
        if isinstance(df.columns, pd.MultiIndex):
            # Use the last level (price type: Open, High, Low, Close, Volume)
            df.columns = df.columns.get_level_values(-1)

        # Lowercase column names
        df.columns = [c.lower().strip() for c in df.columns]

        # Rename 'adj close' to 'close' if needed
        if "adj close" in df.columns and "close" not in df.columns:
            df = df.rename(columns={"adj close": "close"})

        # Keep only OHLCV columns
        expected = ["open", "high", "low", "close", "volume"]
        available = [c for c in expected if c in df.columns]
        df = df[available]

        # Enforce types
        for col in ["open", "high", "low", "close"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
        if "volume" in df.columns:
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype("int64")

        # Normalize index to timezone-naive UTC date
        if df.index.tz is not None:
            df.index = df.index.tz_convert("UTC").tz_localize(None)
        df.index.name = "date"

        return df
