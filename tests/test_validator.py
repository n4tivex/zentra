"""Tests for DataValidator.

Per PRD §16.3: empty df, close=0, high<low, stale data, insufficient rows.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

from zentra.data.validator import DataValidator


@pytest.fixture
def validator():
    return DataValidator()


@pytest.fixture(autouse=True)
def freeze_today(monkeypatch):
    monkeypatch.setattr("zentra.data.validator.today_jakarta", lambda: datetime(2026, 5, 4).date())


class TestDataValidator:
    def test_empty_dataframe(self, validator):
        df = pd.DataFrame()
        result = validator.validate("TEST", df)
        assert not result.is_valid
        assert any("empty" in e.lower() for e in result.errors)

    def test_insufficient_rows(self, validator, insufficient_df):
        result = validator.validate("TEST", insufficient_df)
        assert not result.is_valid
        assert any("insufficient" in e.lower() for e in result.errors)

    def test_valid_bullish_data(self, validator, bullish_df):
        result = validator.validate("TEST", bullish_df)
        assert result.is_valid

    def test_valid_minimal_data(self, validator, minimal_df):
        result = validator.validate("TEST", minimal_df)
        assert result.is_valid

    def test_close_zero_invalid(self, validator, bullish_df):
        df = bullish_df.copy()
        df.loc[df.index[-1], "close"] = 0
        result = validator.validate("TEST", df)
        assert not result.is_valid
        assert any("zero" in e.lower() or "negative" in e.lower() for e in result.errors)

    def test_close_negative_invalid(self, validator, bullish_df):
        df = bullish_df.copy()
        df.loc[df.index[5], "close"] = -100
        result = validator.validate("TEST", df)
        assert not result.is_valid

    def test_high_less_than_low(self, validator, bullish_df):
        df = bullish_df.copy()
        idx = df.index[10]
        df.loc[idx, "high"] = df.loc[idx, "low"] - 10
        result = validator.validate("TEST", df)
        assert not result.is_valid
        assert any("high" in e.lower() and "low" in e.lower() for e in result.errors)

    def test_stale_data(self, validator, stale_df):
        result = validator.validate("TEST", stale_df)
        assert not result.is_valid
        assert any("days old" in e.lower() or "stale" in e.lower() for e in result.errors)

    def test_nan_rows_dropped_with_warning(self, validator, bullish_df):
        df = bullish_df.copy()
        df.loc[df.index[5], "close"] = float("nan")
        result = validator.validate("TEST", df)
        # Should still be valid (dropped 1 row, still >= 30)
        assert result.is_valid
        assert any("dropped" in w.lower() or "nan" in w.lower() for w in result.warnings)

    def test_negative_volume_warning(self, validator, bullish_df):
        df = bullish_df.copy()
        df.loc[df.index[3], "volume"] = -100
        result = validator.validate("TEST", df)
        # Should be valid — negative volumes are fixed to 0
        assert result.is_valid
        assert any("negative" in w.lower() and "volume" in w.lower() for w in result.warnings)

    def test_all_volume_zero_invalid(self, validator, bullish_df):
        df = bullish_df.copy()
        df["volume"] = 0
        result = validator.validate("TEST", df)
        assert not result.is_valid
        assert any("suspended" in e.lower() or "volume" in e.lower() for e in result.errors)

    def test_high_less_than_close(self, validator, bullish_df):
        df = bullish_df.copy()
        idx = df.index[15]
        df.loc[idx, "high"] = df.loc[idx, "close"] - 5
        result = validator.validate("TEST", df)
        assert not result.is_valid

    def test_low_greater_than_close(self, validator, bullish_df):
        df = bullish_df.copy()
        idx = df.index[15]
        df.loc[idx, "low"] = df.loc[idx, "close"] + 5
        result = validator.validate("TEST", df)
        assert not result.is_valid
