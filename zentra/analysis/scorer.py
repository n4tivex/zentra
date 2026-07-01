"""Signal scoring engine - weighted multi-indicator scoring and classification."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

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

        BUY is gated by RSI crossing up through 50, with MACD as confirmation.
        The remaining indicators rank and explain the setup, but cannot create
        a BUY without the RSI crossing gate.
        """
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) >= 2 else last

        scores: dict[str, int] = {}

        ema_fast = last.get("EMA_9")
        ema_slow = last.get("EMA_21")
        if self._is_valid_number(ema_fast) and self._is_valid_number(ema_slow) and float(ema_slow) != 0:
            ema_fast = float(ema_fast)
            ema_slow = float(ema_slow)
            ema_gap_pct = (ema_fast - ema_slow) / ema_slow
            prev_ema_fast = prev.get("EMA_9")
            prev_ema_slow = prev.get("EMA_21")

            if ema_fast > ema_slow:
                scores["ema"] = 15
            elif abs(ema_gap_pct) <= 0.02:
                if self._is_valid_number(prev_ema_fast) and self._is_valid_number(prev_ema_slow) and float(prev_ema_fast) < float(prev_ema_slow):
                    scores["ema"] = 10
                else:
                    scores["ema"] = 8
            else:
                if self._is_valid_number(prev_ema_fast) and self._is_valid_number(prev_ema_slow):
                    prev_gap = abs(float(prev_ema_fast) - float(prev_ema_slow))
                    curr_gap = abs(ema_fast - ema_slow)
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

        macd_confirmed = False
        macd_crossed_up = False
        macd_hist_val = 0.0
        if self._is_valid_number(macd) and self._is_valid_number(macd_signal):
            macd = float(macd)
            macd_signal = float(macd_signal)
            macd_hist_val = float(macd_hist) if self._is_valid_number(macd_hist) else macd - macd_signal
            prev_macd_val = float(prev_macd) if self._is_valid_number(prev_macd) else 0.0
            prev_signal_val = float(prev_signal) if self._is_valid_number(prev_signal) else 0.0
            prev_hist = float(prev.get("MACDh_12_26_9", 0) or 0)
            macd_confirmed = macd >= macd_signal and macd_hist_val >= 0
            macd_crossed_up = macd_confirmed and prev_macd_val <= prev_signal_val

            if macd_crossed_up:
                scores["macd"] = 20
            elif macd_confirmed:
                scores["macd"] = 15
            elif macd_hist_val < 0 and abs(macd_hist_val) < abs(prev_hist):
                scores["macd"] = 5
            else:
                scores["macd"] = 0
        else:
            scores["macd"] = 0

        rsi = last.get("RSI_14")
        prev_rsi = prev.get("RSI_14")
        rsi_crossed_up = False
        if self._is_valid_number(rsi):
            rsi = float(rsi)
            prev_rsi_val = float(prev_rsi) if self._is_valid_number(prev_rsi) else rsi
            rsi_crossed_up = prev_rsi_val <= 50 < rsi <= 65

            if rsi_crossed_up:
                scores["rsi"] = 35
            elif 45 <= rsi <= 65:
                scores["rsi"] = 25
            elif 35 <= rsi < 45:
                scores["rsi"] = 15
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
                scores["bb"] = 10
            elif close_f < bbm_f:
                scores["bb"] = 7
            elif close_f < bbu_f:
                scores["bb"] = 5
            else:
                scores["bb"] = 2
        else:
            scores["bb"] = 0
            close_f = 0.0
            bbl_f = bbm_f = bbu_f = 0.0

        volume = last.get("volume")
        vol_sma = last.get("VOL_SMA_5")
        if self._is_valid_number(volume) and self._is_valid_number(vol_sma) and float(vol_sma) > 0:
            volume_f = float(volume)
            vol_sma_f = float(vol_sma)
            volume_ratio = volume_f / vol_sma_f
            if volume_ratio > 1.5:
                scores["volume"] = 10
            elif volume_ratio >= 1.0:
                scores["volume"] = 5
            else:
                scores["volume"] = 0
        else:
            scores["volume"] = 0
            volume_ratio = 0.0
            volume_f = 0.0
            vol_sma_f = 0.0

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
        if not is_exit_check and self._is_valid_number(close) and self._is_valid_number(ema_fast) and float(close) < float(ema_fast):
            total_score -= 20

        confluence_count = sum(1 for key in ["ema", "macd", "rsi", "bb", "volume"] if scores.get(key, 0) > 0)

        snapshot = {
            "ema_9": round(float(ema_fast), 2) if self._is_valid_number(ema_fast) else 0,
            "ema_21": round(float(ema_slow), 2) if self._is_valid_number(ema_slow) else 0,
            "rsi_14": round(float(rsi), 2) if self._is_valid_number(rsi) else 0,
            "rsi_crossed_up": rsi_crossed_up,
            "macd": round(float(macd), 4) if self._is_valid_number(macd) else 0,
            "macd_signal": round(float(macd_signal), 4) if self._is_valid_number(macd_signal) else 0,
            "macd_histogram": round(float(macd_hist_val), 4),
            "macd_confirmed": macd_confirmed,
            "macd_crossed_up": macd_crossed_up,
            "bb_lower": round(float(bbl_f), 2) if self._is_valid_number(bbl) else 0,
            "bb_upper": round(float(bbu_f), 2) if self._is_valid_number(bbu) else 0,
            "bb_percent": round(float(last.get("BBP_20_2.0_2.0", 0)), 4) if self._is_valid_number(last.get("BBP_20_2.0_2.0")) else 0,
            "atr_14": round(float(atr), 2) if self._is_valid_number(atr) else 0,
            "obv": int(last.get("OBV", 0) or 0),
            "volume_ratio": round(float(volume_ratio), 2) if volume_ratio else 0,
            "volume_sma_5": round(float(vol_sma_f), 2) if vol_sma_f else 0,
            "close": round(float(close_f), 2) if self._is_valid_number(close) else 0,
            "volume": int(volume_f) if volume_f else 0,
        }

        signal_type, signal_strength, reason = self._classify(
            total_score,
            confluence_count,
            risk_levels,
            rsi_crossed_up=rsi_crossed_up,
            macd_confirmed=macd_confirmed,
        )
        now = datetime.now(tz=UTC)
        result = SignalResult(
            ticker=ticker,
            signal_type=signal_type,
            score=total_score,
            confluence_count=confluence_count,
            indicator_snapshot=snapshot,
            reason=reason,
            signal_strength=signal_strength,
            created_at=now.isoformat(),
        )

        if signal_type == SignalType.BUY:
            result.expires_at = (now + timedelta(days=SCORING.SIGNAL_EXPIRY_DAYS)).isoformat()
        elif signal_type == SignalType.WATCH:
            result.expires_at = (now + timedelta(days=1)).isoformat()

        if risk_levels and signal_type in (SignalType.BUY, SignalType.WATCH):
            result.entry_price = risk_levels.entry
            result.stop_loss = risk_levels.stop_loss
            result.take_profit = risk_levels.take_profit
            result.risk_pct = risk_levels.risk_pct
            result.reward_pct = risk_levels.reward_pct
            result.rr_ratio = risk_levels.risk_reward_ratio

        return result

    def check_exit(self, ticker: str, df: pd.DataFrame, active_signal: dict, days_held: int = 99) -> SignalResult | None:
        """Check if an active signal should be exited."""
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) >= 2 else last

        close = float(last.get("close", 0) or 0)
        sl = float(active_signal.get("stop_loss", 0) or 0)

        if days_held < SCORING.MIN_HOLD_DAYS_BEFORE_EXIT:
            if sl and close <= sl:
                pass
            else:
                return None

        rsi = float(last.get("RSI_14", 50) or 50)
        macd = float(last.get("MACD_12_26_9", 0) or 0)
        macd_signal = float(last.get("MACDs_12_26_9", 0) or 0)
        prev_macd = float(prev.get("MACD_12_26_9", 0) or 0)
        prev_signal = float(prev.get("MACDs_12_26_9", 0) or 0)
        bbu = float(last.get("BBU_20_2.0_2.0", 0) or 0)

        tp = float(active_signal.get("take_profit", 0) or 0)
        sl = float(active_signal.get("stop_loss", 0) or 0)
        entry = float(active_signal.get("entry_price", 0) or 0)

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

        prioritized.sort(key=lambda x: x[0].value)
        exit_reasons = [reason for _, reason in prioritized]
        top_priority = prioritized[0][0]

        if top_priority == ExitPriority.STOP_LOSS:
            exit_status = SignalStatus.CLOSED_SL
        elif top_priority == ExitPriority.TAKE_PROFIT:
            exit_status = SignalStatus.CLOSED_TP
        else:
            exit_status = SignalStatus.CLOSED_EXIT_SIGNAL

        has_hard = any(p.value <= ExitPriority.HARD_EXIT.value for p, _ in prioritized)
        total_triggers = len(prioritized)
        strength = SignalStrength.STRONG if has_hard or total_triggers >= 2 else SignalStrength.NORMAL

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
            created_at=datetime.now(tz=UTC).isoformat(),
        )

    def _classify(
        self,
        score: int,
        confluence_count: int,
        risk_levels: object | None,
        *,
        rsi_crossed_up: bool,
        macd_confirmed: bool,
    ) -> tuple[SignalType, SignalStrength, str]:
        if risk_levels is not None:
            rr = getattr(risk_levels, "risk_reward_ratio", 0)
            if rr < SCORING.MIN_RR_RATIO:
                return SignalType.NO_SIGNAL, SignalStrength.NORMAL, "risk_reward_below_minimum"

        if not rsi_crossed_up:
            if score >= SCORING.WATCH_THRESHOLD and confluence_count >= SCORING.MIN_CONFLUENCE_WATCH:
                return SignalType.WATCH, SignalStrength.NORMAL, "rsi_not_crossed"
            return SignalType.NO_SIGNAL, SignalStrength.NORMAL, "rsi_not_crossed"

        if not macd_confirmed:
            if score >= SCORING.WATCH_THRESHOLD and confluence_count >= SCORING.MIN_CONFLUENCE_WATCH:
                return SignalType.WATCH, SignalStrength.NORMAL, "macd_not_confirmed"
            return SignalType.NO_SIGNAL, SignalStrength.NORMAL, "macd_not_confirmed"

        if score >= SCORING.BUY_THRESHOLD and confluence_count >= SCORING.MIN_CONFLUENCE:
            if score >= 85:
                strength = SignalStrength.STRONG
            elif score >= 75:
                strength = SignalStrength.NORMAL
            else:
                strength = SignalStrength.BORDERLINE
            return SignalType.BUY, strength, "rsi_cross_buy"

        if score >= SCORING.WATCH_THRESHOLD and confluence_count >= SCORING.MIN_CONFLUENCE_WATCH:
            return SignalType.WATCH, SignalStrength.NORMAL, "watch_signal"

        return SignalType.NO_SIGNAL, SignalStrength.NORMAL, "below_threshold"
