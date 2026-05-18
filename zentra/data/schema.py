"""DataFrame schema contract enforcement.

Per roadmap P1-10: explicit schema contract for OHLCV and indicator DataFrames.
Validates required columns, dtypes, and index semantics.
"""

from __future__ import annotations

import pandas as pd
import structlog

from zentra.config import INDICATOR_REQUIRED_COLUMNS, OHLCV_REQUIRED_COLUMNS
from zentra.exceptions import DataIntegrityError

log = structlog.get_logger()

OHLCV_DTYPES: dict[str, str] = {
    "open": "float64",
    "high": "float64",
    "low": "float64",
    "close": "float64",
    "volume": "int64",
}


def validate_ohlcv_schema(df: pd.DataFrame, ticker: str = "") -> None:
    """Validate that a DataFrame conforms to OHLCV schema contract.

    Raises:
        DataIntegrityError: If required columns are missing or wrong dtype.
    """
    missing = [c for c in OHLCV_REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise DataIntegrityError(
            f"OHLCV schema violation for {ticker}: missing columns {missing}"
        )

    for col, expected_dtype in OHLCV_DTYPES.items():
        if col in df.columns and str(df[col].dtype) != expected_dtype:
            log.warning(
                "ohlcv_dtype_mismatch",
                ticker=ticker,
                column=col,
                expected=expected_dtype,
                actual=str(df[col].dtype),
            )


def validate_indicator_schema(df: pd.DataFrame, ticker: str = "") -> None:
    """Validate that a DataFrame has all required indicator columns.

    Raises:
        DataIntegrityError: If required indicator columns are missing.
    """
    missing = [c for c in INDICATOR_REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise DataIntegrityError(
            f"Indicator schema violation for {ticker}: missing columns {missing}"
        )

    # Index must be datetime-like
    if not pd.api.types.is_datetime64_any_dtype(df.index):
        raise DataIntegrityError(
            f"Indicator schema violation for {ticker}: index must be DatetimeIndex"
        )

    if df.empty:
        raise DataIntegrityError(f"Indicator schema violation for {ticker}: DataFrame is empty")

    invalid_last = [
        c
        for c in INDICATOR_REQUIRED_COLUMNS
        if pd.isna(df.iloc[-1][c])
    ]
    if invalid_last:
        raise DataIntegrityError(
            f"Indicator schema violation for {ticker}: invalid last-row values {invalid_last}"
        )
