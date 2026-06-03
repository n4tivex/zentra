"""Tests for RiskCalculator.

The risk model must keep stop loss capped at 5%, preserve integer prices,
and calculate a positive risk/reward profile.
"""

from __future__ import annotations

import pytest

from zentra.analysis.risk import RiskCalculator


@pytest.fixture
def calc():
    return RiskCalculator()


class TestRiskCalculator:
    def test_basic_buy_calculation(self, calc):
        result = calc.calculate(entry_price=3000.0, atr=100.0)
        assert result.entry == 3000
        assert result.stop_loss < result.entry
        assert result.take_profit > result.entry
        assert result.risk_reward_ratio >= 1.0

    def test_prices_are_integers(self, calc):
        result = calc.calculate(entry_price=3150.7, atr=89.3)
        assert isinstance(result.entry, int)
        assert isinstance(result.stop_loss, int)
        assert isinstance(result.take_profit, int)

    def test_sl_below_entry_for_buy(self, calc):
        result = calc.calculate(entry_price=5000.0, atr=200.0, direction="BUY")
        assert result.stop_loss < result.entry

    def test_tp_above_entry_for_buy(self, calc):
        result = calc.calculate(entry_price=5000.0, atr=200.0, direction="BUY")
        assert result.take_profit > result.entry

    def test_sl_capped_at_5_percent(self, calc):
        result = calc.calculate(entry_price=1000.0, atr=200.0)
        sl_pct = (result.entry - result.stop_loss) / result.entry
        assert sl_pct <= 0.05 + 0.001

    def test_rr_ratio_calculation(self, calc):
        result = calc.calculate(entry_price=3000.0, atr=100.0)
        assert result.risk_reward_ratio >= 1.5

    def test_small_atr_still_works(self, calc):
        result = calc.calculate(entry_price=500.0, atr=15.0)
        assert result.stop_loss < result.entry
        assert result.take_profit > result.entry
        assert result.risk_reward_ratio > 0

    def test_risk_pct_and_reward_pct(self, calc):
        result = calc.calculate(entry_price=10000.0, atr=300.0)
        assert result.risk_pct > 0
        assert result.reward_pct > 0
        assert result.reward_pct > result.risk_pct

    def test_large_atr_sl_cap_enforced(self, calc):
        result = calc.calculate(entry_price=1000.0, atr=100.0)
        max_sl_distance = 1000 * 0.05
        actual_sl_distance = result.entry - result.stop_loss
        assert actual_sl_distance <= max_sl_distance + 1
