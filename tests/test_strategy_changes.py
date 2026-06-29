from __future__ import annotations

import pandas as pd

from zentra.analysis.indicators import TechnicalIndicators
from zentra.analysis.risk import RiskCalculator
from zentra.analysis.scorer import SignalScorer
from zentra.config import TICKER_NAMES, RiskLevels, SignalType


class FixedRiskCalculator:
    def calculate(self, entry_price: float, atr: float) -> RiskLevels:
        return RiskLevels(
            entry=round(entry_price),
            stop_loss=round(entry_price * 0.95),
            take_profit=round(entry_price * 1.12),
            risk_reward_ratio=2.4,
            risk_pct=5.0,
            reward_pct=12.0,
        )


def _strategy_df(
    *,
    prev_rsi: float,
    rsi: float,
    macd: float,
    macd_signal: float,
    prev_macd: float = 0.05,
    prev_signal: float = 0.04,
) -> pd.DataFrame:
    dates = pd.date_range("2026-05-01", periods=2, freq="B")
    return pd.DataFrame(
        [
            {
                "open": 100.0,
                "high": 103.0,
                "low": 98.0,
                "close": 100.0,
                "volume": 1_000_000,
                "EMA_9": 99.0,
                "EMA_21": 101.0,
                "MACD_12_26_9": prev_macd,
                "MACDh_12_26_9": prev_macd - prev_signal,
                "MACDs_12_26_9": prev_signal,
                "RSI_14": prev_rsi,
                "BBL_20_2.0_2.0": 95.0,
                "BBM_20_2.0_2.0": 104.0,
                "BBU_20_2.0_2.0": 120.0,
                "BBP_20_2.0_2.0": 0.32,
                "ATRr_14": 20.0,
                "OBV": 10_000,
                "VOL_SMA_5": 700_000.0,
            },
            {
                "open": 102.0,
                "high": 108.0,
                "low": 101.0,
                "close": 106.0,
                "volume": 1_400_000,
                "EMA_9": 105.0,
                "EMA_21": 103.0,
                "MACD_12_26_9": macd,
                "MACDh_12_26_9": macd - macd_signal,
                "MACDs_12_26_9": macd_signal,
                "RSI_14": rsi,
                "BBL_20_2.0_2.0": 96.0,
                "BBM_20_2.0_2.0": 110.0,
                "BBU_20_2.0_2.0": 122.0,
                "BBP_20_2.0_2.0": 0.40,
                "ATRr_14": 20.0,
                "OBV": 11_000,
                "VOL_SMA_5": 700_000.0,
            },
        ],
        index=dates,
    )


def test_ticker_names_use_verified_idx_display_names() -> None:
    assert TICKER_NAMES["RMKE"] == "RMK Energy"
    assert TICKER_NAMES["OASA"] == "Maharaksa Biru Energi"
    assert TICKER_NAMES["CBDK"] == "Bangun Kosambi Sukses"
    assert TICKER_NAMES["ADMR"] == "Alamtri Minerals Indonesia"


def test_indicators_use_ema_9_21_and_volume_sma_5(bullish_df: pd.DataFrame) -> None:
    df = TechnicalIndicators().compute_all(bullish_df)

    assert "EMA_9" in df.columns
    assert "EMA_21" in df.columns
    assert "VOL_SMA_5" in df.columns
    assert "EMA_20" not in df.columns
    assert "EMA_50" not in df.columns
    assert "VOL_SMA_20" not in df.columns


def test_rsi_crossing_with_macd_confirmation_is_buy() -> None:
    scorer = SignalScorer()
    scorer.risk_calc = FixedRiskCalculator()
    df = _strategy_df(prev_rsi=49.0, rsi=53.0, macd=0.12, macd_signal=0.08)

    result = scorer.score_buy("BBCA", df)

    assert result.signal_type == SignalType.BUY
    assert result.reason == "rsi_cross_buy"
    assert result.indicator_snapshot["rsi_crossed_up"] is True
    assert result.indicator_snapshot["macd_confirmed"] is True


def test_macd_confirmation_without_rsi_crossing_cannot_create_buy() -> None:
    scorer = SignalScorer()
    scorer.risk_calc = FixedRiskCalculator()
    df = _strategy_df(prev_rsi=39.0, rsi=42.0, macd=0.20, macd_signal=0.05)

    result = scorer.score_buy("BBCA", df)

    assert result.signal_type != SignalType.BUY
    assert result.reason == "rsi_not_crossed"


def test_stop_loss_is_capped_at_5_percent() -> None:
    result = RiskCalculator().calculate(entry_price=1000.0, atr=100.0)

    assert result.risk_pct <= 5.0
    assert result.stop_loss >= 950
