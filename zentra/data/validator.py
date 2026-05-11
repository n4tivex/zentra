"""Data validator — ensures OHLCV data integrity before analysis.

All validation rules per PRD §5.2.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import structlog

from zentra.config import DATA, ValidationResult
from zentra.runtime import today_jakarta

log = structlog.get_logger()


class DataValidator:
    """Validates OHLCV DataFrames for completeness and integrity."""

    def validate(self, ticker: str, df: pd.DataFrame) -> ValidationResult:
        warnings: list[str] = []
        errors: list[str] = []
        ticker_log = log.bind(ticker=ticker)

        if df is None or df.empty:
            errors.append("DataFrame is empty")
            return ValidationResult(False, warnings, errors, None)

        df_clean = df.copy()
        df_clean = df_clean.sort_index()
        df_clean = df_clean[~df_clean.index.duplicated(keep="last")]

        pre_drop = len(df_clean)
        df_clean = df_clean.dropna(subset=["open", "high", "low", "close", "volume"])
        dropped = pre_drop - len(df_clean)

        if dropped > 0:
            warnings.append(f"Dropped {dropped} rows with NaN values")
            ticker_log.warning("nan_rows_dropped", dropped=dropped)

        neg_vol = df_clean["volume"] < 0
        if neg_vol.any():
            count = int(neg_vol.sum())
            df_clean.loc[neg_vol, "volume"] = 0
            warnings.append(f"Fixed {count} negative volume values to 0")
            ticker_log.warning("negative_volume_fixed", count=count)

        if len(df_clean) < DATA.MIN_TRADING_DAYS:
            errors.append(
                f"Insufficient data: {len(df_clean)} rows (minimum {DATA.MIN_TRADING_DAYS})"
            )
            return ValidationResult(False, warnings, errors, df_clean)

        if (df_clean["close"] <= 0).any():
            errors.append("Close price contains zero or negative values")

        if (df_clean["volume"] == 0).all():
            errors.append("All volume is 0 — stock may be suspended")

        if (df_clean["high"] < df_clean["low"]).any():
            errors.append("High < Low detected")

        if (df_clean["high"] < df_clean["close"]).any():
            errors.append("High < Close detected")

        if (df_clean["low"] > df_clean["close"]).any():
            errors.append("Low > Close detected")

        if "open" in df_clean.columns:
            if (df_clean["high"] < df_clean["open"]).any():
                errors.append("High < Open detected")
            if (df_clean["low"] > df_clean["open"]).any():
                errors.append("Low > Open detected")

        today = today_jakarta()
        last_date = pd.Timestamp(df_clean.index[-1]).date()
        days_old = (today - last_date).days

        if days_old > DATA.STALE_DATA_THRESHOLD_DAYS:
            errors.append(
                f"Data is {days_old} days old (threshold: {DATA.STALE_DATA_THRESHOLD_DAYS})"
            )

        if days_old > 1:
            warnings.append(
                f"Data may be stale: last date is {last_date} ({days_old} days ago)"
            )

        dates = pd.Series(df_clean.index)
        gaps = dates.diff().dt.days

        if not gaps[gaps > 7].empty:
            warnings.append("Found gaps > 7 calendar days in data")

        if not gaps[(gaps > 4) & (gaps <= 7)].empty:
            warnings.append("Found extended market holiday gaps")

        return ValidationResult(
            is_valid=len(errors) == 0,
            warnings=warnings,
            errors=errors,
            cleaned_df=df_clean,
        )
