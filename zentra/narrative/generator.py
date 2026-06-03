"""Narrative generator — assembles dynamic signal text from building blocks.

Per PRD §8.1-8.2: deterministic randomness, contextual block selection,
no static templates, no repeated messages.
"""

from __future__ import annotations

import hashlib
import random

import structlog

from zentra.config import SCORING, SignalResult, SignalStrength, SignalType, TICKER_NAMES
from zentra.narrative import blocks

log = structlog.get_logger()


class NarrativeGenerator:
    """Generates dynamic, contextual narrative text for signals."""

    def __init__(self, run_date: str) -> None:
        """Initialize with run date for deterministic randomness."""
        self._run_date = run_date

    def generate_buy(self, result: SignalResult) -> str:
        """Generate BUY signal narrative."""
        rng = self._make_rng(result.ticker)
        snap = result.indicator_snapshot
        parts: list[str] = []

        # 1. Opening hook
        if result.signal_strength == SignalStrength.STRONG:
            opening_pool = blocks.OPENING_STRONG
        elif result.signal_strength == SignalStrength.BORDERLINE:
            opening_pool = blocks.OPENING_BORDERLINE
        else:
            opening_pool = blocks.OPENING_NORMAL

        name = TICKER_NAMES.get(result.ticker, result.ticker)
        parts.append(rng.choice(opening_pool).format(ticker=f"${result.ticker} ({name})"))

        # 2. Trend block
        ema_fast = snap.get("ema_9", 0)
        ema_slow = snap.get("ema_21", 0)
        if ema_fast and ema_slow:
            if ema_fast > ema_slow:
                parts.append(rng.choice(blocks.TREND_UPTREND))
            elif ema_slow != 0 and abs(ema_fast - ema_slow) / ema_slow <= 0.02:
                parts.append(rng.choice(blocks.TREND_CROSSING))
            elif ema_fast < ema_slow:
                parts.append(rng.choice(blocks.TREND_NARROWING))

        # 3. Momentum block (RSI)
        rsi = snap.get("rsi_14", 0)
        if rsi:
            if rsi < 25:
                parts.append(rng.choice(blocks.RSI_EXTREMELY_OVERSOLD).format(rsi=rsi))
            elif rsi < 35:
                parts.append(rng.choice(blocks.RSI_OVERSOLD).format(rsi=rsi))
            elif rsi <= 55:
                parts.append(rng.choice(blocks.RSI_NEUTRAL_BULLISH).format(rsi=rsi))
            elif rsi <= 65:
                parts.append(rng.choice(blocks.RSI_MODERATE).format(rsi=rsi))

        # 4. Volume block
        vol_ratio = snap.get("volume_ratio", 0)
        if vol_ratio:
            if vol_ratio > 1.5:
                parts.append(rng.choice(blocks.VOLUME_HIGH).format(ratio=vol_ratio))
            elif vol_ratio >= 1.0:
                parts.append(rng.choice(blocks.VOLUME_NORMAL).format(ratio=vol_ratio))
            else:
                parts.append(rng.choice(blocks.VOLUME_LOW).format(ratio=vol_ratio))

        # 5. Setup block (Bollinger position)
        bb_pct = snap.get("bb_percent", 0.5)
        if bb_pct is not None:
            if bb_pct <= 0:
                parts.append(rng.choice(blocks.SETUP_BOUNCE_BBL))
            elif bb_pct < 0.5:
                parts.append(rng.choice(blocks.SETUP_LOWER_HALF))
            elif bb_pct < 1.0:
                parts.append(rng.choice(blocks.SETUP_UPPER_HALF))

        # 6. Caveat (wajib for borderline)
        if result.signal_strength == SignalStrength.BORDERLINE:
            parts.append(rng.choice(blocks.CAVEAT_BLOCKS))

        # Join into paragraphs (group every 2-3 sentences)
        narrative = self._join_paragraphs(parts)
        return narrative

    def generate_exit(self, result: SignalResult, active_signal: dict) -> str:
        """Generate EXIT signal narrative."""
        rng = self._make_rng(result.ticker)
        snap = result.indicator_snapshot
        parts: list[str] = []

        entry = active_signal.get("entry_price", 0)
        close = snap.get("close", 0)
        exit_reasons = result.exit_reasons or []

        # 1. Exit hook — pick based on primary reason
        primary = exit_reasons[0] if exit_reasons else "reversal"
        if "Target" in primary:
            parts.append(rng.choice(blocks.EXIT_HOOK_TP).format(ticker=f"${result.ticker}"))
        elif "Stop loss" in primary:
            parts.append(rng.choice(blocks.EXIT_HOOK_SL).format(ticker=f"${result.ticker}"))
        else:
            parts.append(rng.choice(blocks.EXIT_HOOK_REVERSAL).format(ticker=f"${result.ticker}"))

        # 2. Primary reason detail
        rsi = snap.get("rsi_14", 0)
        for reason in exit_reasons[:2]:
            if "RSI" in reason and rsi:
                parts.append(rng.choice(blocks.EXIT_REASON_RSI_OVERBOUGHT).format(rsi=rsi))
            elif "MACD" in reason:
                parts.append(rng.choice(blocks.EXIT_REASON_MACD_CROSS))
            elif "Bollinger" in reason:
                parts.append(rng.choice(blocks.EXIT_REASON_BBU_BREAKOUT))
            elif "score" in reason.lower():
                parts.append(rng.choice(blocks.EXIT_REASON_SCORE_DROP))

        # 3. Gain/loss estimate
        if entry and close:
            pct = (close - entry) / entry * 100
            if pct >= 0:
                parts.append(rng.choice(blocks.GAIN_LINE_PROFIT).format(pct=pct))
            else:
                parts.append(rng.choice(blocks.GAIN_LINE_LOSS).format(pct=pct))

        return self._join_paragraphs(parts)

    def generate_expired(self, ticker: str, days_active: int) -> str:
        """Generate expiry notification text."""
        rng = self._make_rng(ticker)
        return rng.choice(blocks.EXPIRED_SIGNAL).format(ticker=f"${ticker}", days=days_active)

    def _make_rng(self, ticker: str) -> random.Random:
        """Create a deterministic Random instance seeded by (run_date + ticker)."""
        seed_str = f"{self._run_date}:{ticker}"
        seed = int(hashlib.md5(seed_str.encode()).hexdigest(), 16)
        return random.Random(seed)

    def _join_paragraphs(self, parts: list[str]) -> str:
        """Join narrative parts into paragraphs, grouping 2-3 sentences each."""
        if not parts:
            return ""
        if len(parts) <= 3:
            return " ".join(parts)
        # Group into paragraphs of 2-3 sentences
        paragraphs: list[str] = []
        current: list[str] = []
        for i, part in enumerate(parts):
            current.append(part)
            if len(current) >= 3 or i == len(parts) - 1:
                paragraphs.append(" ".join(current))
                current = []
        return "\n\n".join(paragraphs)
