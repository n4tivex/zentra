"""Tests for NarrativeGenerator.

Per PRD §16.3: no unresolved placeholders, all required elements present,
MarkdownV2 escaping correct.
"""

from __future__ import annotations

import pytest

from zentra.config import SignalResult, SignalStrength, SignalType
from zentra.narrative.generator import NarrativeGenerator


@pytest.fixture
def generator():
    return NarrativeGenerator(run_date="2026-05-04")


def make_buy_result(
    ticker: str = "BBCA",
    score: int = 75,
    strength: SignalStrength = SignalStrength.NORMAL,
) -> SignalResult:
    return SignalResult(
        ticker=ticker,
        signal_type=SignalType.BUY,
        score=score,
        confluence_count=4,
        entry_price=9500,
        stop_loss=8900,
        take_profit=10500,
        risk_pct=6.3,
        reward_pct=10.5,
        rr_ratio=1.67,
        signal_strength=strength,
        indicator_snapshot={
            "ema_20": 9400.5,
            "ema_50": 9200.3,
            "rsi_14": 45.2,
            "macd": 15.3,
            "macd_signal": 10.1,
            "macd_histogram": 5.2,
            "bb_lower": 9000.0,
            "bb_upper": 9800.0,
            "bb_percent": 0.35,
            "atr_14": 150.0,
            "obv": 12345678,
            "volume_ratio": 1.6,
            "close": 9500.0,
            "volume": 8000000,
        },
    )


def make_exit_result(ticker: str = "BBCA") -> SignalResult:
    return SignalResult(
        ticker=ticker,
        signal_type=SignalType.EXIT,
        score=35,
        confluence_count=2,
        entry_price=9000,
        signal_strength=SignalStrength.NORMAL,
        exit_reasons=["RSI overbought", "MACD bearish crossover"],
        reason="RSI overbought",
        indicator_snapshot={
            "close": 9800.0,
            "rsi_14": 72.5,
            "macd": -5.2,
            "macd_signal": 2.1,
        },
    )


class TestNarrativeGenerator:
    def test_buy_narrative_no_raw_placeholders(self, generator):
        """Output must not contain unresolved {placeholders}."""
        result = make_buy_result()
        narrative = generator.generate_buy(result)
        assert "{rsi" not in narrative
        assert "{ticker" not in narrative
        assert "{ratio" not in narrative
        assert "{pct" not in narrative

    def test_buy_narrative_not_empty(self, generator):
        """BUY narrative must produce text."""
        result = make_buy_result()
        narrative = generator.generate_buy(result)
        assert len(narrative) > 50

    def test_buy_narrative_mentions_ticker(self, generator):
        """Narrative should mention the ticker."""
        result = make_buy_result(ticker="BMRI")
        narrative = generator.generate_buy(result)
        assert "BMRI" in narrative

    def test_buy_narrative_deterministic(self, generator):
        """Same inputs on same date should produce identical output."""
        result = make_buy_result()
        n1 = generator.generate_buy(result)
        n2 = generator.generate_buy(result)
        assert n1 == n2

    def test_different_tickers_different_narratives(self, generator):
        """Different tickers should produce different narratives."""
        r1 = make_buy_result(ticker="BBCA")
        r2 = make_buy_result(ticker="BMRI")
        n1 = generator.generate_buy(r1)
        n2 = generator.generate_buy(r2)
        # They might overlap in structure but should differ in content
        assert n1 != n2

    def test_borderline_includes_caveat(self, generator):
        """Borderline signal must include caveat warning."""
        result = make_buy_result(score=71, strength=SignalStrength.BORDERLINE)
        narrative = generator.generate_buy(result)
        assert "⚠️" in narrative or "borderline" in narrative.lower() or "hati" in narrative.lower()

    def test_exit_narrative_no_raw_placeholders(self, generator):
        """EXIT narrative must not contain unresolved placeholders."""
        result = make_exit_result()
        active = {"entry_price": 9000, "take_profit": 10000, "stop_loss": 8500}
        narrative = generator.generate_exit(result, active)
        assert "{rsi" not in narrative
        assert "{ticker" not in narrative
        assert "{pct" not in narrative

    def test_exit_narrative_mentions_reason(self, generator):
        """EXIT narrative should reference exit reasons."""
        result = make_exit_result()
        active = {"entry_price": 9000}
        narrative = generator.generate_exit(result, active)
        # Should mention RSI or overbought or MACD
        assert any(
            term in narrative.lower()
            for term in ["rsi", "overbought", "macd", "momentum"]
        )

    def test_expired_narrative(self, generator):
        """Expired signal notification."""
        text = generator.generate_expired("BBRI", 12)
        assert "BBRI" in text
        assert "12" in text
