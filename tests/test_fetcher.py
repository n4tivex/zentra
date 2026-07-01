"""Tests for MarketDataFetcher data normalization.

Regression test for MultiIndex normalization (yfinance 1.4.x format).
Bug: _normalize() uses get_level_values(-1) which gets Ticker level
instead of get_level_values(0) which gets Price level.
"""

from __future__ import annotations

import pandas as pd

from zentra.data.fetcher import MarketDataFetcher


class TestNormalize:
    def test_multiindex_normalization(self):
        """MultiIndex columns normalize to flat lowercase OHLCV with correct dtypes.

        yfinance 1.4.x returns MultiIndex with levels ['Price', 'Ticker'].
        get_level_values(-1) returns ticker names ('TICKER', ...) — wrong.
        get_level_values(0) returns price fields ('Close', 'High', ...).
        """
        fetcher = MarketDataFetcher()

        multi_index = pd.MultiIndex.from_tuples(
            [
                ("Close", "TICKER"),
                ("High", "TICKER"),
                ("Low", "TICKER"),
                ("Open", "TICKER"),
                ("Volume", "TICKER"),
            ],
            names=["Price", "Ticker"],
        )
        dates = pd.date_range("2026-01-01", periods=3, freq="B")
        data = [
            [100.0, 105.0, 99.0, 101.0, 1_000_000],
            [102.0, 106.0, 100.0, 103.0, 1_100_000],
            [104.0, 108.0, 102.0, 105.0, 1_200_000],
        ]
        df = pd.DataFrame(data, index=dates, columns=multi_index)

        result = fetcher._normalize(df)

        expected_cols = ["open", "high", "low", "close", "volume"]
        assert list(result.columns) == expected_cols

        assert result["open"].dtype == "float64"
        assert result["high"].dtype == "float64"
        assert result["low"].dtype == "float64"
        assert result["close"].dtype == "float64"
        assert result["volume"].dtype == "int64"

        assert list(result["open"]) == [101.0, 103.0, 105.0]
        assert list(result["close"]) == [100.0, 102.0, 104.0]
        assert list(result["volume"]) == [1_000_000, 1_100_000, 1_200_000]

    def test_multiindex_normalization_different_order(self):
        """MultiIndex columns in shuffled order still normalize correctly.

        Proves order-independence: the expected output columns always
        appear as [open, high, low, close, volume] regardless of input order.
        """
        fetcher = MarketDataFetcher()

        multi_index = pd.MultiIndex.from_tuples(
            [
                ("Open", "TICKER"),
                ("Volume", "TICKER"),
                ("Close", "TICKER"),
                ("Low", "TICKER"),
                ("High", "TICKER"),
            ],
            names=["Price", "Ticker"],
        )
        dates = pd.date_range("2026-01-01", periods=3, freq="B")
        data = [
            [101.0, 1_000_000, 100.0, 99.0, 105.0],
            [103.0, 1_100_000, 102.0, 100.0, 106.0],
            [105.0, 1_200_000, 104.0, 102.0, 108.0],
        ]
        df = pd.DataFrame(data, index=dates, columns=multi_index)

        result = fetcher._normalize(df)

        expected_cols = ["open", "high", "low", "close", "volume"]
        assert list(result.columns) == expected_cols

        assert result["open"].dtype == "float64"
        assert result["close"].dtype == "float64"
        assert result["volume"].dtype == "int64"

        assert list(result["open"]) == [101.0, 103.0, 105.0]
        assert list(result["close"]) == [100.0, 102.0, 104.0]

    def test_normalize_empty_dataframe(self):
        """Empty DataFrame or DataFrame with missing columns produces graceful empty result."""
        fetcher = MarketDataFetcher()

        # Empty DataFrame with no columns
        df_empty = pd.DataFrame()
        result = fetcher._normalize(df_empty)
        assert isinstance(result, pd.DataFrame)
        assert result.empty

        # DataFrame with columns but none matching OHLCV
        df_other = pd.DataFrame({"foo": [1, 2, 3], "bar": [4, 5, 6]})
        result = fetcher._normalize(df_other)
        assert isinstance(result, pd.DataFrame)
        assert result.empty
