"""Critical P0 regression tests."""

from __future__ import annotations

import pandas as pd

from zentra.analysis.scorer import SignalScorer
from zentra.data.validator import DataValidator


class DummyRisk:
    entry = 100
    stop_loss = 95
    take_profit = 115
    risk_reward_ratio = 3.0
    risk_pct = 5.0
    reward_pct = 15.0


class DummyRiskCalc:
    def calculate(self, close: float, atr: float):
        return DummyRisk()


def test_macd_zero_values_are_not_silently_dropped(bullish_df: pd.DataFrame):
    df = bullish_df.copy()

    df["EMA_20"] = 100.0
    df["EMA_50"] = 99.0

    df["MACD_12_26_9"] = 0.0
    df["MACDs_12_26_9"] = -0.1
    df["MACDh_12_26_9"] = 0.2

    df["RSI_14"] = 45.0
    df["BBL_20_2.0"] = 95.0
    df["BBM_20_2.0"] = 100.0
    df["BBU_20_2.0"] = 110.0
    df["VOL_SMA_20"] = 1000
    df["ATRr_14"] = 3.0

    scorer = SignalScorer()
    scorer.risk_calc = DummyRiskCalc()

    result = scorer.score_buy("BBCA", df)

    assert result.indicator_snapshot["macd"] == 0.0
    assert result.score > 0


def test_validator_returns_cleaned_dataframe(minimal_df: pd.DataFrame):
    df = minimal_df.copy()
    df.iloc[0, df.columns.get_loc("volume")] = -100

    validator = DataValidator()
    result = validator.validate("BBCA", df)

    assert result.cleaned_df is not None
    assert (result.cleaned_df["volume"] >= 0).all()


def test_exit_priority_prefers_take_profit(exit_setup_df: pd.DataFrame):
    scorer = SignalScorer()

    active_signal = {
        "entry_price": 100,
        "take_profit": 110,
        "stop_loss": 90,
    }

    df = exit_setup_df.copy()
    df.iloc[-1, df.columns.get_loc("close")] = 120
    df["RSI_14"] = 72
    df["MACD_12_26_9"] = 1.0
    df["MACDs_12_26_9"] = 0.5
    df["BBU_20_2.0"] = 115

    result = scorer.check_exit("BBCA", df, active_signal)

    assert result is not None
    assert result.reason == "RSI overbought" or "Target price reached" in result.exit_reasons
    assert "Target price reached" in result.exit_reasons
