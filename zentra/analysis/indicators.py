"""Technical indicator calculations using pandas-ta.

Per PRD §6.1: EMA, MACD, RSI, StochRSI, Bollinger Bands, ATR, OBV, Volume SMA.
"""

from __future__ import annotations

import pandas as pd
import pandas_ta as ta  # noqa: F401 — needed for df.ta accessor
import structlog

from zentra.config import SCORING
from zentra.exceptions import CalculationError

log = structlog.get_logger()


class TechnicalIndicators:
    """Computes all technical indicators required by ZENTRA scoring engine."""

    # Expected output columns from compute_all
    REQUIRED_COLUMNS = [
        "EMA_9",
        "EMA_21",
        "MACD_12_26_9",
        "MACDh_12_26_9",
        "MACDs_12_26_9",
        "RSI_14",
        "STOCHRSIk_14_14_3_3",
        "STOCHRSId_14_14_3_3",
        "BBL_20_2.0_2.0",
        "BBM_20_2.0_2.0",
        "BBU_20_2.0_2.0",
        "BBP_20_2.0_2.0",
        "ATRr_14",
        "OBV",
        "VOL_SMA_5",
    ]

    def compute_all(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute all indicators and return a new DataFrame with indicator columns.

        Does not mutate the input DataFrame.
        Raises CalculationError if critical columns are NaN on the last row.
        """
        df = df.copy()

        # Trend
        df.ta.ema(length=SCORING.FAST_MA_DAYS, append=True)
        df.ta.ema(length=SCORING.SLOW_MA_DAYS, append=True)
        df.ta.macd(fast=12, slow=26, signal=9, append=True)

        # Momentum
        df.ta.rsi(length=14, append=True)
        df.ta.stochrsi(length=14, rsi_length=14, k=3, d=3, append=True)

        # Volatility
        df.ta.bbands(length=20, std=2, append=True)
        df.ta.atr(length=14, append=True)

        # Volume
        df.ta.obv(append=True)
        df["VOL_SMA_5"] = df["volume"].rolling(window=SCORING.VOLUME_LOOKBACK_DAYS).mean()

        # Validate critical columns on last row
        last = df.iloc[-1]
        critical = ["EMA_9", "EMA_21", "RSI_14", "MACD_12_26_9", "ATRr_14"]
        missing = [col for col in critical if col not in df.columns or pd.isna(last.get(col))]

        if missing:
            raise CalculationError(f"Critical indicator columns are NaN on last row: {missing}")

        # Check ATR too small (< 10 Rupiah)
        atr_val = last.get("ATRr_14", 0)
        if atr_val is not None and atr_val < 10:
            raise CalculationError(f"ATR too small ({atr_val:.2f}) — volatility too low for swing trading")

        return df
