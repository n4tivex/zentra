"""ATR-based entry, stop loss, and take profit level calculator."""

from __future__ import annotations

from zentra.config import SCORING, RiskLevels


class RiskCalculator:
    """Calculates risk/reward levels from entry price and ATR."""

    SL_MULTIPLIER: float = SCORING.SL_ATR_MULTIPLIER
    TP_MULTIPLIER: float = SCORING.TP_ATR_MULTIPLIER
    MIN_RR_RATIO: float = SCORING.MIN_RR_RATIO
    MAX_SL_PCT: float = SCORING.MAX_SL_PCT

    def calculate(self, entry_price: float, atr: float, direction: str = "BUY") -> RiskLevels:
        """Calculate risk levels. All prices are rounded to nearest integer Rupiah."""
        sl_distance = self.SL_MULTIPLIER * atr

        max_sl_distance = entry_price * self.MAX_SL_PCT
        if sl_distance > max_sl_distance:
            sl_distance = max_sl_distance

        tp_distance = self.TP_MULTIPLIER * atr

        if direction == "BUY":
            stop_loss = entry_price - sl_distance
            take_profit = entry_price + tp_distance
        else:
            stop_loss = entry_price + sl_distance
            take_profit = entry_price - tp_distance

        risk_pct = sl_distance / entry_price
        reward_pct = tp_distance / entry_price
        rr_ratio = reward_pct / risk_pct if risk_pct > 0 else 0.0

        return RiskLevels(
            entry=round(entry_price),
            stop_loss=round(stop_loss),
            take_profit=round(take_profit),
            risk_reward_ratio=round(rr_ratio, 2),
            risk_pct=round(risk_pct * 100, 2),
            reward_pct=round(reward_pct * 100, 2),
        )
