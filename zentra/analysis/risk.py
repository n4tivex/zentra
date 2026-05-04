"""Risk calculator — ATR-based entry, stop loss, and take profit levels.

Per PRD §6.2: SL/TP multipliers, 8% SL cap, RR ratio check.
"""

from __future__ import annotations

from zentra.config import SCORING, RiskLevels


class RiskCalculator:
    """Calculates risk/reward levels from entry price and ATR."""

    SL_MULTIPLIER: float = SCORING.SL_ATR_MULTIPLIER   # 1.5
    TP_MULTIPLIER: float = SCORING.TP_ATR_MULTIPLIER   # 2.5
    MIN_RR_RATIO: float = SCORING.MIN_RR_RATIO         # 1.5
    MAX_SL_PCT: float = SCORING.MAX_SL_PCT              # 0.08

    def calculate(self, entry_price: float, atr: float, direction: str = "BUY") -> RiskLevels:
        """Calculate risk levels. All prices are rounded to nearest integer (Rupiah).

        If SL exceeds 8% of entry, cap it at 8% per PRD §6.2.
        """
        # Raw stop loss distance
        sl_distance = self.SL_MULTIPLIER * atr

        # Cap SL at MAX_SL_PCT of entry
        max_sl_distance = entry_price * self.MAX_SL_PCT
        if sl_distance > max_sl_distance:
            sl_distance = max_sl_distance

        # Calculate TP using the TP multiplier
        tp_distance = self.TP_MULTIPLIER * atr

        if direction == "BUY":
            stop_loss = entry_price - sl_distance
            take_profit = entry_price + tp_distance
        else:
            stop_loss = entry_price + sl_distance
            take_profit = entry_price - tp_distance

        # Risk/reward percentages
        risk_pct = sl_distance / entry_price
        reward_pct = tp_distance / entry_price

        # RR ratio
        rr_ratio = reward_pct / risk_pct if risk_pct > 0 else 0.0

        return RiskLevels(
            entry=round(entry_price),
            stop_loss=round(stop_loss),
            take_profit=round(take_profit),
            risk_reward_ratio=round(rr_ratio, 2),
            risk_pct=round(risk_pct * 100, 2),
            reward_pct=round(reward_pct * 100, 2),
        )
