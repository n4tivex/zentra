"""Market data fetcher — retrieves OHLCV data from yfinance.

Per PRD §5.1: batch download, .JK suffix, cache check, retry logic.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import pandas as pd
import requests as reqs
import structlog
import yfinance as yf
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from zentra.config import DATA
from zentra.exceptions import DataFetchError, TickerNotFoundError

log = structlog.get_logger()

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_HTTP_SESSION = reqs.Session()
_HTTP_SESSION.headers.update({"User-Agent": _USER_AGENT})


@dataclass
class FetchCoverage:
    requested_tickers: list[str] = field(default_factory=list)
    fetched_tickers: list[str] = field(default_factory=list)
    cached_tickers: list[str] = field(default_factory=list)
    missing_tickers: list[str] = field(default_factory=list)
    failed_tickers: list[str] = field(default_factory=list)
    empty_tickers: list[str] = field(default_factory=list)
    extract_failed_tickers: list[str] = field(default_factory=list)
    cache_failed_tickers: list[str] = field(default_factory=list)
    provider_error: str | None = None

    @property
    def fetched_count(self) -> int:
        return len(self.fetched_tickers)

    @property
    def cached_count(self) -> int:
        return len(self.cached_tickers)

    @property
    def missing_count(self) -> int:
        return len(self.missing_tickers)

    @property
    def failure_count(self) -> int:
        return len(set(self.failed_tickers + self.cache_failed_tickers))

    @property
    def coverage_ratio(self) -> float:
        if not self.requested_tickers:
            return 1.0
        covered = len(set(self.fetched_tickers + self.cached_tickers))
        return covered / len(self.requested_tickers)

    @property
    def is_partial(self) -> bool:
        return self.missing_count > 0 or self.failure_count > 0 or self.provider_error is not None


@dataclass
class FetchResult:
    data: dict[str, pd.DataFrame]
    coverage: FetchCoverage


class MarketDataFetcher:
    """Fetches OHLCV data from Yahoo Finance for IDX tickers."""

    def __init__(self, ohlcv_repo: object | None = None) -> None:
        self._ohlcv_repo = ohlcv_repo
        self.last_coverage = FetchCoverage()

    def fetch_all(self, tickers: list[str], days: int = DATA.LOOKBACK_DAYS) -> dict[str, pd.DataFrame]:
        """Fetch OHLCV for all tickers using cache-first, batch-network fallback."""
        result = self.fetch_all_with_coverage(tickers, days=days)
        return result.data

    def fetch_all_with_coverage(
        self,
        tickers: list[str],
        days: int = DATA.LOOKBACK_DAYS,
        min_latest_date: date | None = None,
    ) -> FetchResult:
        """Fetch OHLCV and return explicit coverage telemetry."""
        results: dict[str, pd.DataFrame] = {}
        missing: list[str] = []
        coverage = FetchCoverage(requested_tickers=list(tickers))
        self.last_coverage = coverage

        for ticker in tickers:
            cached = self._get_cached(ticker, coverage, min_latest_date=min_latest_date)
            if cached is not None and not cached.empty:
                results[ticker] = cached
                coverage.cached_tickers.append(ticker)
                log.info("ticker_cache_hit", ticker=ticker, rows=len(cached))
            else:
                missing.append(ticker)

        if missing:
            tickers_jk = [f"{t}.JK" for t in missing]
            log.info("fetching_market_data", tickers=len(missing), days=days)
            try:
                raw = self._fetch_from_yahoo(tickers_jk, days)
            except Exception as e:
                coverage.provider_error = str(e)
                coverage.failed_tickers.extend(missing)
                coverage.missing_tickers = [t for t in tickers if t not in results]
                if results:
                    log.warning(
                        "partial_fetch",
                        error=str(e),
                        cached=len(results),
                        missing=coverage.missing_tickers,
                    )
                    return FetchResult(results, coverage)
                raise DataFetchError(f"Batch fetch failed: {e}") from e

            for ticker in missing:
                ticker_jk = f"{ticker}.JK"
                try:
                    df = raw.get(ticker_jk)
                    if df is None or df.empty:
                        coverage.empty_tickers.append(ticker)
                        coverage.failed_tickers.append(ticker)
                        log.warning("ticker_empty", ticker=ticker)
                        continue
                    normalized = self._normalize(df)
                    results[ticker] = normalized
                    coverage.fetched_tickers.append(ticker)
                    log.info("ticker_fetched", ticker=ticker, rows=len(normalized))
                except Exception as e:
                    coverage.extract_failed_tickers.append(ticker)
                    coverage.failed_tickers.append(ticker)
                    log.warning("ticker_extract_failed", ticker=ticker, error=str(e))

        coverage.missing_tickers = [t for t in tickers if t not in results]
        self.last_coverage = coverage

        if not results:
            raise DataFetchError("All tickers failed to fetch")

        if coverage.is_partial:
            log.warning(
                "partial_fetch",
                fetched=coverage.fetched_count,
                cached=coverage.cached_count,
                missing=coverage.missing_count,
                failed=coverage.failure_count,
                missing_tickers=coverage.missing_tickers,
            )

        return FetchResult(results, coverage)

    def fetch_single(self, ticker: str, days: int = DATA.LOOKBACK_DAYS, min_latest_date: date | None = None) -> pd.DataFrame:
        """Fetch a single ticker. Cache-first, then network fallback."""
        cached = self._get_cached(ticker, min_latest_date=min_latest_date)
        if cached is not None and not cached.empty:
            return cached

        ticker_jk = f"{ticker}.JK"
        end = datetime.now(tz=UTC) + timedelta(days=1)
        start = end - timedelta(days=days)

        try:
            df = yf.download(
                ticker_jk,
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                progress=False,
                auto_adjust=True,
                session=_HTTP_SESSION,
            )
        except Exception as e:
            raise DataFetchError(f"Failed to fetch {ticker}: {e}") from e

        if df is None or df.empty:
            raise TickerNotFoundError(f"No data returned for {ticker}")

        return self._normalize(df)

    def _get_cached(self, ticker: str, coverage: FetchCoverage | None = None, min_latest_date: date | None = None) -> pd.DataFrame | None:
        if self._ohlcv_repo is None:
            return None
        getter = getattr(self._ohlcv_repo, "get_cached_data", None)
        if not callable(getter):
            return None
        try:
            data = getter(ticker)
            if data is not None and not data.empty and min_latest_date is not None:
                cache_latest = pd.Timestamp(data.index[-1]).date()
                if cache_latest < min_latest_date:
                    log.info(
                        "cache_stale",
                        ticker=ticker,
                        last_date=str(cache_latest),
                        min_expected=str(min_latest_date),
                    )
                    return None
            return data
        except Exception as e:
            if coverage is not None:
                coverage.cache_failed_tickers.append(ticker)
            log.warning("cache_lookup_failed", ticker=ticker, error=str(e))
            return None

    @retry(
        stop=stop_after_attempt(DATA.FETCH_RETRY_ATTEMPTS),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
        reraise=True,
    )
    def _fetch_from_yahoo(self, tickers_jk: list[str], days: int) -> dict[str, pd.DataFrame]:
        end = datetime.now(tz=UTC) + timedelta(days=1)
        start = end - timedelta(days=days)
        results: dict[str, pd.DataFrame] = {}
        for ticker_jk in tickers_jk:
            try:
                df = yf.download(
                    ticker_jk,
                    start=start.strftime("%Y-%m-%d"),
                    end=end.strftime("%Y-%m-%d"),
                    progress=False,
                    auto_adjust=True,
                    session=_HTTP_SESSION,
                )
                if df is not None and not df.empty:
                    results[ticker_jk] = df
            except Exception:
                log.warning("ticker_fetch_failed", ticker=ticker_jk)
            time.sleep(1)
        if not results:
            raise DataFetchError("yfinance returned empty DataFrame for all tickers")
        return results

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
