"""Signal scoring engine — weighted multi-indicator scoring and classification.

Per PRD §7: scoring matrix, confluence check, EXIT detection, signal classification.
"""

from __future__ import annotations

import pandas as pd
import structlog

from zentra.analysis.risk import RiskCalculator
from zentra.config import (
    SCORING,
    ExitPriority,
    SignalResult,
    SignalStatus,
    SignalStrength,
    SignalType,
)

log = structlog.get_logger()


class SignalScorer:
    """Scores a ticker's technical setup and classifies the signal."""

    def __init__(self) -> None:
        self.risk_calc = RiskCalculator()

    @staticmethod
    def _is_valid_number(value: object) -> bool:
        return value is not None and not pd.isna(value)

    def score_buy(self, ticker: str, df: pd.DataFrame, is_exit_check: bool = False) -> SignalResult:
        """Score a ticker for BUY signal potential.

        Gating hierarchy (P1-12):
        1. RR ratio < MIN_RR_RATIO → hard gate → NO_SIGNAL (no matter the score)
        2. close < EMA20 → scoring penalty (-30 pts, only for non-exit checks)
        3. confluence < MIN_CONFLUENCE → qualifying gate → demote to WATCH or NO_SIGNAL
        4. score >= BUY_THRESHOLD + confluence >= MIN_CONFLUENCE → BUY
        5. score >= WATCH_THRESHOLD + confluence >= MIN_CONFLUENCE_WATCH → WATCH
        """
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) >= 2 else last

        scores: dict[str, int] = {}

        ema20 = last.get("EMA_20")
        ema50 = last.get("EMA_50")
        if self._is_valid_number(ema20) and self._is_valid_number(ema50) and float(ema50) != 0:
            ema20 = float(ema20)
            ema50 = float(ema50)
            ema_gap_pct = (ema20 - ema50) / ema50
            prev_ema20 = prev.get("EMA_20")
            prev_ema50 = prev.get("EMA_50")

            if ema20 > ema50:
                scores["ema"] = 25
            elif abs(ema_gap_pct) <= 0.02:
                if self._is_valid_number(prev_ema20) and self._is_valid_number(prev_ema50) and float(prev_ema20) < float(prev_ema50):
                    scores["ema"] = 15
                else:
                    scores["ema"] = 15
            else:
                if self._is_valid_number(prev_ema20) and self._is_valid_number(prev_ema50):
                    prev_gap = abs(float(prev_ema20) - float(prev_ema50))
                    curr_gap = abs(ema20 - ema50)
                    scores["ema"] = 5 if curr_gap < prev_gap else 0
                else:
                    scores["ema"] = 0
        else:
            scores["ema"] = 0

        macd = last.get("MACD_12_26_9")
        macd_signal = last.get("MACDs_12_26_9")
        macd_hist = last.get("MACDh_12_26_9")
        prev_macd = prev.get("MACD_12_26_9")
        prev_signal = prev.get("MACDs_12_26_9")

        if self._is_valid_number(macd) and self._is_valid_number(macd_signal):
            macd = float(macd)
            macd_signal = float(macd_signal)
            macd_hist_val = float(macd_hist) if self._is_valid_number(macd_hist) else 0.0
            prev_macd_val = float(prev_macd) if self._is_valid_number(prev_macd) else 0.0
            prev_signal_val = float(prev_signal) if self._is_valid_number(prev_signal) else 0.0
            crossover_today = (macd > macd_signal) and (prev_macd_val <= prev_signal_val)
            if crossover_today:
                scores["macd"] = 20
            elif macd_hist_val > 0:
                prev_hist = float(prev.get("MACDh_12_26_9", 0) or 0)
                scores["macd"] = 12 if macd_hist_val > prev_hist else 8
            elif macd_hist_val < 0:
                prev_hist = float(prev.get("MACDh_12_26_9", 0) or 0)
                scores["macd"] = 5 if abs(macd_hist_val) < abs(prev_hist) else 0
            else:
                scores["macd"] = 0
        else:
            scores["macd"] = 0

        rsi = last.get("RSI_14")
        if self._is_valid_number(rsi):
            rsi = float(rsi)
            if 35 <= rsi <= 55:
                scores["rsi"] = 20
            elif 55 < rsi <= 65:
                scores["rsi"] = 12
            elif 25 <= rsi < 35:
                scores["rsi"] = 8
            elif rsi < 25:
                scores["rsi"] = 3
            else:
                scores["rsi"] = 0
        else:
            scores["rsi"] = 0
            rsi = 0.0

        close = last.get("close")
        bbl = last.get("BBL_20_2.0_2.0")
        bbm = last.get("BBM_20_2.0_2.0")
        bbu = last.get("BBU_20_2.0_2.0")
        if all(self._is_valid_number(v) for v in (close, bbl, bbm, bbu)):
            close_f = float(close)
            bbl_f = float(bbl)
            bbm_f = float(bbm)
            bbu_f = float(bbu)
            if close_f <= bbl_f:
                scores["bb"] = 15
            elif close_f < bbm_f:
                scores["bb"] = 10
            elif close_f < bbu_f:
                scores["bb"] = 5
            else:
                scores["bb"] = 2
        else:
            scores["bb"] = 0
            close_f = 0.0
            bbl_f = bbm_f = bbu_f = 0.0

        volume = last.get("volume")
        vol_sma = last.get("VOL_SMA_20")
        if self._is_valid_number(volume) and self._is_valid_number(vol_sma) and float(vol_sma) > 0:
            volume_f = float(volume)
            vol_sma_f = float(vol_sma)
            volume_ratio = volume_f / vol_sma_f
            if volume_ratio > 1.5:
                scores["volume"] = 15
            elif volume_ratio >= 1.0:
                scores["volume"] = 8
            else:
                scores["volume"] = 0
        else:
            scores["volume"] = 0
            volume_ratio = 0.0
            volume_f = 0.0

        atr = last.get("ATRr_14")
        risk_levels = None
        if self._is_valid_number(close) and self._is_valid_number(atr) and float(atr) > 0:
            close_val = float(close)
            atr_val = float(atr)
            risk_levels = self.risk_calc.calculate(close_val, atr_val)
            scores["atr"] = 5 if risk_levels.risk_reward_ratio >= SCORING.MIN_RR_RATIO else 0
        else:
            scores["atr"] = 0

        total_score = sum(scores.values())
        if not is_exit_check and self._is_valid_number(close) and self._is_valid_number(ema20):
            if float(close) < float(ema20):
                total_score -= 30

        confluence_count = sum(1 for key in ["ema", "macd", "rsi", "bb", "volume"] if scores.get(key, 0) > 0)

        snapshot = {
            "ema_20": round(float(ema20), 2) if self._is_valid_number(ema20) else 0,
            "ema_50": round(float(ema50), 2) if self._is_valid_number(ema50) else 0,
            "rsi_14": round(float(rsi), 2) if self._is_valid_number(rsi) else 0,
            "macd": round(float(macd), 4) if self._is_valid_number(macd) else 0,
            "macd_signal": round(float(macd_signal), 4) if self._is_valid_number(macd_signal) else 0,
            "macd_histogram": round(float(macd_hist), 4) if self._is_valid_number(macd_hist) else 0,
            "bb_lower": round(float(bbl_f), 2) if self._is_valid_number(bbl) else 0,
            "bb_upper": round(float(bbu_f), 2) if self._is_valid_number(bbu) else 0,
            "bb_percent": round(float(last.get("BBP_20_2.0_2.0", 0)), 4) if self._is_valid_number(last.get("BBP_20_2.0_2.0")) else 0,
            "atr_14": round(float(atr), 2) if self._is_valid_number(atr) else 0,
            "obv": int(last.get("OBV", 0) or 0),
            "volume_ratio": round(float(volume_ratio), 2) if volume_ratio else 0,
            "close": round(float(close_f), 2) if self._is_valid_number(close) else 0,
            "volume": int(volume_f) if volume_f else 0,
        }

        signal_type, signal_strength, reason = self._classify(total_score, confluence_count, risk_levels)
        result = SignalResult(
            ticker=ticker,
            signal_type=signal_type,
            score=total_score,
            confluence_count=confluence_count,
            indicator_snapshot=snapshot,
            reason=reason,
            signal_strength=signal_strength,
        )

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
        """Check if an active signal should be exited.

        Exit priority (P0-5 — deterministic, not string matching):
        1. Stop loss hit → CLOSED_SL (highest priority)
        2. Take profit hit → CLOSED_TP
        3. Hard technical exits (RSI overbought) → CLOSED_EXIT_SIGNAL
        4. Soft technical exits (MACD cross, score drop) → CLOSED_EXIT_SIGNAL
        """
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) >= 2 else last

        close = float(last.get("close", 0) or 0)
        rsi = float(last.get("RSI_14", 50) or 50)
        macd = float(last.get("MACD_12_26_9", 0) or 0)
        macd_signal = float(last.get("MACDs_12_26_9", 0) or 0)
        prev_macd = float(prev.get("MACD_12_26_9", 0) or 0)
        prev_signal = float(prev.get("MACDs_12_26_9", 0) or 0)
        bbu = float(last.get("BBU_20_2.0_2.0", 0) or 0)

        tp = float(active_signal.get("take_profit", 0) or 0)
        sl = float(active_signal.get("stop_loss", 0) or 0)
        entry = float(active_signal.get("entry_price", 0) or 0)

        # Collect reasons with explicit priority tags
        prioritized: list[tuple[ExitPriority, str]] = []

        if sl and close <= sl:
            prioritized.append((ExitPriority.STOP_LOSS, "Stop loss hit"))
        if tp and close >= tp:
            prioritized.append((ExitPriority.TAKE_PROFIT, "Target price reached"))
        if rsi >= 70:
            prioritized.append((ExitPriority.HARD_EXIT, "RSI overbought"))

        if (macd < macd_signal) and (prev_macd >= prev_signal):
            prioritized.append((ExitPriority.SOFT_EXIT, "MACD bearish crossover"))
        if bbu and close > bbu:
            prioritized.append((ExitPriority.SOFT_EXIT, "Price above upper Bollinger Band"))

        buy_result = self.score_buy(ticker, df, is_exit_check=True)
        if buy_result.score < SCORING.EXIT_SCORE_THRESHOLD:
            prioritized.append((ExitPriority.SOFT_EXIT, "Setup score dropped below threshold"))

        if not prioritized:
            return None

        # Sort by priority (lower = higher priority)
        prioritized.sort(key=lambda x: x[0].value)
        exit_reasons = [reason for _, reason in prioritized]
        top_priority = prioritized[0][0]

        # Determine exit_status from top priority reason
        if top_priority == ExitPriority.STOP_LOSS:
            exit_status = SignalStatus.CLOSED_SL
        elif top_priority == ExitPriority.TAKE_PROFIT:
            exit_status = SignalStatus.CLOSED_TP
        else:
            exit_status = SignalStatus.CLOSED_EXIT_SIGNAL

        has_hard = any(p.value <= ExitPriority.HARD_EXIT.value for p, _ in prioritized)
        total_triggers = len(prioritized)
        if has_hard:
            strength = SignalStrength.STRONG if total_triggers >= 2 else SignalStrength.NORMAL
        else:
            strength = SignalStrength.STRONG if total_triggers >= 2 else SignalStrength.NORMAL

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
            exit_status=exit_status,
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
        if risk_levels is not None:
            rr = getattr(risk_levels, "risk_reward_ratio", 0)
            if rr < SCORING.MIN_RR_RATIO:
                return SignalType.NO_SIGNAL, SignalStrength.NORMAL, "risk_reward_below_minimum"

        if score >= SCORING.BUY_THRESHOLD and confluence_count >= SCORING.MIN_CONFLUENCE:
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
