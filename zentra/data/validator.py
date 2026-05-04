"""Data validator — ensures OHLCV data integrity before analysis.

All validation rules per PRD §5.2.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import structlog

from zentra.config import DATA, ValidationResult

log = structlog.get_logger()


class DataValidator:
    """Validates OHLCV DataFrames for completeness and integrity."""

    def validate(self, ticker: str, df: pd.DataFrame) -> ValidationResult:
        """Run all validation checks. Returns ValidationResult (does not raise)."""
        warnings: list[str] = []
        errors: list[str] = []
        ticker_log = log.bind(ticker=ticker)

        # 1. DataFrame not empty
        if df is None or df.empty:
            errors.append("DataFrame is empty")
            return ValidationResult(is_valid=False, warnings=warnings, errors=errors)

        # 2. Drop NaN in close/volume, recheck row count
        pre_drop = len(df)
        df_clean = df.dropna(subset=["close", "volume"])
        dropped = pre_drop - len(df_clean)
        if dropped > 0:
            warnings.append(f"Dropped {dropped} rows with NaN in close/volume")
            ticker_log.warning("nan_rows_dropped", dropped=dropped)

        # 3. Minimum rows
        if len(df_clean) < DATA.MIN_TRADING_DAYS:
            errors.append(
                f"Insufficient data: {len(df_clean)} rows (minimum {DATA.MIN_TRADING_DAYS})"
            )
            return ValidationResult(is_valid=False, warnings=warnings, errors=errors)

        # 4. Close price > 0
        if (df_clean["close"] <= 0).any():
            errors.append("Close price contains zero or negative values")
            return ValidationResult(is_valid=False, warnings=warnings, errors=errors)

        # 5. Volume >= 0 (fix negatives)
        neg_vol = df_clean["volume"] < 0
        if neg_vol.any():
            warnings.append(f"Fixed {neg_vol.sum()} negative volume values to 0")
            ticker_log.warning("negative_volume_fixed", count=int(neg_vol.sum()))

        # 6. All volume == 0 check (possible suspension)
        if (df_clean["volume"] == 0).all():
            errors.append("All volume is 0 — stock may be suspended")
            return ValidationResult(is_valid=False, warnings=warnings, errors=errors)

        # 7. High >= Low
        bad_hl = df_clean["high"] < df_clean["low"]
        if bad_hl.any():
            errors.append(f"High < Low on {bad_hl.sum()} rows")
            return ValidationResult(is_valid=False, warnings=warnings, errors=errors)

        # 8. High >= Close and High >= Open
        if "open" in df_clean.columns:
            bad_ho = df_clean["high"] < df_clean["open"]
            if bad_ho.any():
                errors.append(f"High < Open on {bad_ho.sum()} rows")
                return ValidationResult(is_valid=False, warnings=warnings, errors=errors)

        bad_hc = df_clean["high"] < df_clean["close"]
        if bad_hc.any():
            errors.append(f"High < Close on {bad_hc.sum()} rows")
            return ValidationResult(is_valid=False, warnings=warnings, errors=errors)

        # 9. Low <= Close and Low <= Open
        if "open" in df_clean.columns:
            bad_lo = df_clean["low"] > df_clean["open"]
            if bad_lo.any():
                errors.append(f"Low > Open on {bad_lo.sum()} rows")
                return ValidationResult(is_valid=False, warnings=warnings, errors=errors)

        bad_lc = df_clean["low"] > df_clean["close"]
        if bad_lc.any():
            errors.append(f"Low > Close on {bad_lc.sum()} rows")
            return ValidationResult(is_valid=False, warnings=warnings, errors=errors)

        # 10. Data staleness check
        today = datetime.now(tz=timezone.utc).date()
        last_date = pd.Timestamp(df_clean.index[-1]).date()
        days_old = (today - last_date).days

        if days_old > DATA.STALE_DATA_THRESHOLD_DAYS:
            errors.append(f"Data is {days_old} days old (threshold: {DATA.STALE_DATA_THRESHOLD_DAYS})")
            return ValidationResult(is_valid=False, warnings=warnings, errors=errors)

        if days_old > 1:
            warnings.append(f"Data may be stale: last date is {last_date} ({days_old} days ago)")
            ticker_log.warning("data_possibly_stale", last_date=str(last_date), days_old=days_old)

        # 11. Gap check
        dates = pd.Series(df_clean.index)
        gaps = dates.diff().dt.days
        large_gaps = gaps[gaps > 7]
        if not large_gaps.empty:
            warnings.append(f"Found {len(large_gaps)} gaps > 7 calendar days in data")
            ticker_log.warning("large_data_gaps", count=len(large_gaps))

        # 4-day gap warning (normal is <= 4 for weekends + holidays)
        medium_gaps = gaps[(gaps > 4) & (gaps <= 7)]
        if not medium_gaps.empty:
            warnings.append(f"Found {len(medium_gaps)} gaps of 5-7 days (possible extended holiday)")

        is_valid = len(errors) == 0
        return ValidationResult(is_valid=is_valid, warnings=warnings, errors=errors)
