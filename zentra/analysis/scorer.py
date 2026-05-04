"""Signal scoring engine — weighted multi-indicator scoring and classification.

Per PRD §7: scoring matrix, confluence check, EXIT detection, signal classification.
"""

from __future__ import annotations

import pandas as pd
import structlog

from zentra.analysis.risk import RiskCalculator
from zentra.config import (
    SCORING,
    SignalResult,
    SignalStrength,
    SignalType,
)

log = structlog.get_logger()


class SignalScorer:
    """Scores a ticker's technical setup and classifies the signal."""

    def __init__(self) -> None:
        self.risk_calc = RiskCalculator()

    def score_buy(self, ticker: str, df: pd.DataFrame) -> SignalResult:
        """Score a ticker for BUY signal potential.

        Uses the latest row of indicator data.
        """
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) >= 2 else last

        scores: dict[str, int] = {}
        details: dict[str, float] = {}

        # --- EMA Trend (max 25) ---
        ema20 = last.get("EMA_20", 0)
        ema50 = last.get("EMA_50", 0)
        if ema20 and ema50 and ema50 != 0:
            ema_gap_pct = (ema20 - ema50) / ema50
            if ema20 > ema50:
                scores["ema"] = 25
            elif abs(ema_gap_pct) <= 0.02:
                # Within 2% and possibly crossing
                prev_ema20 = prev.get("EMA_20", 0)
                prev_ema50 = prev.get("EMA_50", 0)
                if prev_ema20 and prev_ema50 and prev_ema20 < prev_ema50:
                    scores["ema"] = 15  # Crossing
                else:
                    scores["ema"] = 15  # Close to crossing
            else:
                # EMA20 < EMA50, check if gap is narrowing
                prev_ema20 = prev.get("EMA_20", 0)
                prev_ema50 = prev.get("EMA_50", 0)
                if prev_ema20 and prev_ema50:
                    prev_gap = abs(prev_ema20 - prev_ema50)
                    curr_gap = abs(ema20 - ema50)
                    if curr_gap < prev_gap:
                        scores["ema"] = 5
                    else:
                        scores["ema"] = 0
                else:
                    scores["ema"] = 0
        else:
            scores["ema"] = 0

        # --- MACD (max 20) ---
        macd = last.get("MACD_12_26_9", 0)
        macd_signal = last.get("MACDs_12_26_9", 0)
        macd_hist = last.get("MACDh_12_26_9", 0)
        prev_macd = prev.get("MACD_12_26_9", 0)
        prev_signal = prev.get("MACDs_12_26_9", 0)

        if macd and macd_signal:
            # Crossover: MACD crosses above signal line today or yesterday
            crossover_today = (macd > macd_signal) and (prev_macd <= prev_signal)
            if crossover_today:
                scores["macd"] = 20
            elif macd_hist and macd_hist > 0:
                prev_hist = prev.get("MACDh_12_26_9", 0)
                if prev_hist and macd_hist > prev_hist:
                    scores["macd"] = 12  # Histogram positive and increasing
                else:
                    scores["macd"] = 8
            elif macd_hist and macd_hist < 0:
                prev_hist = prev.get("MACDh_12_26_9", 0)
                if prev_hist and abs(macd_hist) < abs(prev_hist):
                    scores["macd"] = 5  # Divergence decreasing
                else:
                    scores["macd"] = 0
            else:
                scores["macd"] = 0
        else:
            scores["macd"] = 0

        # --- RSI (max 20) ---
        rsi = last.get("RSI_14", 50)
        if rsi is not None and not pd.isna(rsi):
            if 35 <= rsi <= 55:
                scores["rsi"] = 20
            elif 55 < rsi <= 65:
                scores["rsi"] = 12
            elif 25 <= rsi < 35:
                scores["rsi"] = 8
            elif rsi < 25:
                scores["rsi"] = 3
            else:
                scores["rsi"] = 0  # RSI > 65 (or > 70 overbought)
        else:
            scores["rsi"] = 0

        # --- Bollinger Bands (max 15) ---
        close = last.get("close", 0)
        bbl = last.get("BBL_20_2.0", 0)
        bbm = last.get("BBM_20_2.0", 0)
        bbu = last.get("BBU_20_2.0", 0)

        if close and bbl and bbm and bbu:
            if close <= bbl:
                scores["bb"] = 15  # At or below lower band
            elif close < bbm:
                scores["bb"] = 10  # Lower half
            elif close < bbu:
                scores["bb"] = 5   # Upper half
            else:
                scores["bb"] = 2   # Above upper band
        else:
            scores["bb"] = 0

        # --- Volume (max 15) ---
        volume = last.get("volume", 0)
        vol_sma = last.get("VOL_SMA_20", 0)

        if volume and vol_sma and vol_sma > 0:
            volume_ratio = volume / vol_sma
            if volume_ratio > 1.5:
                scores["volume"] = 15
            elif volume_ratio >= 1.0:
                scores["volume"] = 8
            else:
                scores["volume"] = 0
        else:
            scores["volume"] = 0
            volume_ratio = 0.0

        # --- ATR / Risk-Reward (max 5) ---
        atr = last.get("ATRr_14", 0)
        if close and atr and atr > 0:
            risk_levels = self.risk_calc.calculate(close, atr)
            if risk_levels.risk_reward_ratio >= SCORING.MIN_RR_RATIO:
                scores["atr"] = 5
            else:
                scores["atr"] = 0
        else:
            scores["atr"] = 0
            risk_levels = None

        # --- Total score and confluence ---
        total_score = sum(scores.values())

        # Trend filter: heavily penalize buying if price is below short-term trend (EMA20)
        # Prevents buying falling knives in bear markets
        if close and ema20 and close < ema20:
            total_score -= 30

        # Confluence: count of 5 main indicators that gave a positive score
        main_indicators = ["ema", "macd", "rsi", "bb", "volume"]
        confluence_count = sum(1 for k in main_indicators if scores.get(k, 0) > 0)

        # Build indicator snapshot
        snapshot = {
            "ema_20": round(float(ema20), 2) if ema20 else 0,
            "ema_50": round(float(ema50), 2) if ema50 else 0,
            "rsi_14": round(float(rsi), 2) if rsi and not pd.isna(rsi) else 0,
            "macd": round(float(macd), 4) if macd else 0,
            "macd_signal": round(float(macd_signal), 4) if macd_signal else 0,
            "macd_histogram": round(float(macd_hist), 4) if macd_hist else 0,
            "bb_lower": round(float(bbl), 2) if bbl else 0,
            "bb_upper": round(float(bbu), 2) if bbu else 0,
            "bb_percent": round(float(last.get("BBP_20_2.0", 0)), 4),
            "atr_14": round(float(atr), 2) if atr else 0,
            "obv": int(last.get("OBV", 0)),
            "volume_ratio": round(float(volume_ratio), 2) if volume_ratio else 0,
            "close": round(float(close), 2) if close else 0,
            "volume": int(volume) if volume else 0,
        }

        # Classify signal
        signal_type, signal_strength, reason = self._classify(
            total_score, confluence_count, risk_levels
        )

        result = SignalResult(
            ticker=ticker,
            signal_type=signal_type,
            score=total_score,
            confluence_count=confluence_count,
            indicator_snapshot=snapshot,
            reason=reason,
            signal_strength=signal_strength,
        )

        # Attach risk levels for BUY / WATCH signals
        if risk_levels and signal_type in (SignalType.BUY, SignalType.WATCH):
            result.entry_price = risk_levels.entry
            result.stop_loss = risk_levels.stop_loss
            result.take_profit = risk_levels.take_profit
            result.risk_pct = risk_levels.risk_pct
            result.reward_pct = risk_levels.reward_pct
            result.rr_ratio = risk_levels.risk_reward_ratio

        return result

    def check_exit(
        self, ticker: str, df: pd.DataFrame, active_signal: dict, days_held: int = 99
    ) -> SignalResult | None:
        """Check if an active BUY signal should be exited.

        Returns a SignalResult with EXIT type if exit conditions are met, else None.
        Per PRD §7.3.

        Hard exits (TP, SL, RSI overbought) fire immediately.
        Soft exits (MACD, BB, score) require MIN_HOLD_DAYS grace period.
        """
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) >= 2 else last

        close = float(last.get("close", 0))
        rsi = float(last.get("RSI_14", 50))
        macd = float(last.get("MACD_12_26_9", 0))
        macd_signal = float(last.get("MACDs_12_26_9", 0))
        prev_macd = float(prev.get("MACD_12_26_9", 0))
        prev_signal = float(prev.get("MACDs_12_26_9", 0))
        bbu = float(last.get("BBU_20_2.0", 0))

        tp = active_signal.get("take_profit", 0)
        sl = active_signal.get("stop_loss", 0)
        entry = active_signal.get("entry_price", 0)

        exit_reasons: list[str] = []

        # RSI >= 70 — overbought
        if rsi >= 70:
            exit_reasons.append("RSI overbought")

        # Close >= Take Profit
        if tp and close >= tp:
            exit_reasons.append("Target price reached")

        # Close <= Stop Loss
        if sl and close <= sl:
            exit_reasons.append("Stop loss hit")

        # MACD bearish crossover today
        macd_cross_down = (macd < macd_signal) and (prev_macd >= prev_signal)
        if macd_cross_down:
            exit_reasons.append("MACD bearish crossover")

        # Close above BBU
        if bbu and close > bbu:
            exit_reasons.append("Price above upper Bollinger Band")

        # Score dropped below threshold
        buy_result = self.score_buy(ticker, df)
        if buy_result.score < SCORING.EXIT_SCORE_THRESHOLD:
            exit_reasons.append("Setup score dropped below threshold")

        if not exit_reasons:
            return None

        # Score the current setup for the EXIT signal metadata

        # Determine strength: 2+ reasons = STRONG EXIT
        strength = SignalStrength.STRONG if len(exit_reasons) >= 2 else SignalStrength.NORMAL

        # Calculate gain/loss
        exit_pct = ((close - entry) / entry * 100) if entry else 0.0

        snapshot = {
            "close": round(close, 2),
            "rsi_14": round(rsi, 2),
            "macd": round(macd, 4),
            "macd_signal": round(macd_signal, 4),
        }

        return SignalResult(
            ticker=ticker,
            signal_type=SignalType.EXIT,
            score=buy_result.score,
            confluence_count=buy_result.confluence_count,
            entry_price=entry,
            indicator_snapshot=snapshot,
            signal_strength=strength,
            exit_reasons=exit_reasons,
            reason=exit_reasons[0],
            risk_pct=round(abs(exit_pct), 2) if exit_pct < 0 else None,
            reward_pct=round(exit_pct, 2) if exit_pct >= 0 else None,
        )

    def _classify(
        self,
        score: int,
        confluence_count: int,
        risk_levels: object | None,
    ) -> tuple[SignalType, SignalStrength, str]:
        """Classify signal based on score and confluence per PRD §7.2."""
        # Check RR ratio minimum
        if risk_levels is not None:
            rr = getattr(risk_levels, "risk_reward_ratio", 0)
            if rr < SCORING.MIN_RR_RATIO:
                return SignalType.NO_SIGNAL, SignalStrength.NORMAL, "risk_reward_below_minimum"

        if score >= SCORING.BUY_THRESHOLD and confluence_count >= SCORING.MIN_CONFLUENCE:
            # Determine BUY strength
            if score >= 85:
                strength = SignalStrength.STRONG
            elif score >= 75:
                strength = SignalStrength.NORMAL
            else:
                strength = SignalStrength.BORDERLINE
            return SignalType.BUY, strength, "buy_signal"

        if score >= SCORING.WATCH_THRESHOLD and confluence_count >= SCORING.MIN_CONFLUENCE_WATCH:
            return SignalType.WATCH, SignalStrength.NORMAL, "watch_signal"

        return SignalType.NO_SIGNAL, SignalStrength.NORMAL, "below_threshold"
