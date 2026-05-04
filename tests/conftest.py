"""Shared test fixtures and configuration."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> pd.DataFrame:
    """Load a CSV fixture as a DataFrame with proper types."""
    path = FIXTURES_DIR / name
    df = pd.read_csv(path, parse_dates=["date"], index_col="date")
    for col in ["open", "high", "low", "close"]:
        if col in df.columns:
            df[col] = df[col].astype("float64")
    if "volume" in df.columns:
        df["volume"] = df["volume"].astype("int64")
    return df


@pytest.fixture
def bullish_df() -> pd.DataFrame:
    return load_fixture("ohlcv_bullish.csv")


@pytest.fixture
def bearish_df() -> pd.DataFrame:
    return load_fixture("ohlcv_bearish.csv")


@pytest.fixture
def minimal_df() -> pd.DataFrame:
    return load_fixture("ohlcv_minimal.csv")


@pytest.fixture
def insufficient_df() -> pd.DataFrame:
    return load_fixture("ohlcv_insufficient.csv")


@pytest.fixture
def stale_df() -> pd.DataFrame:
    return load_fixture("ohlcv_stale.csv")


@pytest.fixture
def exit_setup_df() -> pd.DataFrame:
    return load_fixture("ohlcv_exit_setup.csv")
