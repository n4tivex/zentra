"""Tests for Telegram formatter.

Per PRD §16.3: MarkdownV2 escaping, Rupiah format, required message elements.
"""

from __future__ import annotations

import pytest

from zentra.config import SignalResult, SignalStrength, SignalType
from zentra.telegram.formatter import (
    escape_markdown_v2,
    format_buy_message,
    format_daily_summary,
    format_exit_message,
    format_rupiah,
    format_watch_message,
)


class TestEscapeMarkdownV2:
    def test_escapes_special_chars(self):
        text = "Hello_World*Test[1](2)~`>#+-=|{}.!"
        result = escape_markdown_v2(text)
        assert "\\_" in result
        assert "\\*" in result
        assert "\\[" in result
        assert "\\(" in result
        assert "\\~" in result
        assert "\\`" in result
        assert "\\>" in result
        assert "\\#" in result
        assert "\\+" in result
        assert "\\-" in result
        assert "\\=" in result
        assert "\\|" in result
        assert "\\{" in result
        assert "\\}" in result
        assert "\\." in result
        assert "\\!" in result

    def test_normal_text_unchanged(self):
        text = "Hello World 123"
        assert escape_markdown_v2(text) == text

    def test_empty_string(self):
        assert escape_markdown_v2("") == ""


class TestFormatRupiah:
    def test_basic_format(self):
        assert format_rupiah(1250) == "Rp 1.250"

    def test_large_number(self):
        assert format_rupiah(1000000) == "Rp 1.000.000"

    def test_small_number(self):
        assert format_rupiah(50) == "Rp 50"

    def test_float_rounds(self):
        assert format_rupiah(1250.7) == "Rp 1.251"

    def test_zero(self):
        assert format_rupiah(0) == "Rp 0"


class TestFormatBuyMessage:
    def test_contains_required_elements(self):
        result = SignalResult(
            ticker="BBCA",
            signal_type=SignalType.BUY,
            score=78,
            confluence_count=4,
            entry_price=9500,
            stop_loss=8900,
            take_profit=10500,
            risk_pct=6.3,
            reward_pct=10.5,
            rr_ratio=1.67,
            signal_strength=SignalStrength.NORMAL,
            narrative="Test narrative here",
            indicator_snapshot={"atr_14": 150, "close": 9500},
        )
        msg = format_buy_message(result)

        # Required elements per PRD §8.3
        assert "BUY SIGNAL" in msg
        assert "BBCA" in msg
        assert "Entry" in msg
        assert "Target" in msg
        assert "Stop Loss" in msg
        assert "Estimasi hold" in msg
        assert "Skor" in msg
        assert "78/100" in msg

    def test_contains_rupiah_format(self):
        result = SignalResult(
            ticker="BMRI",
            signal_type=SignalType.BUY,
            score=72,
            confluence_count=3,
            entry_price=5250,
            stop_loss=4900,
            take_profit=5800,
            risk_pct=6.7,
            reward_pct=10.5,
            rr_ratio=1.57,
            signal_strength=SignalStrength.BORDERLINE,
            narrative="Test",
            indicator_snapshot={"atr_14": 100, "close": 5250},
        )
        msg = format_buy_message(result)
        assert "Rp" in msg


class TestFormatExitMessage:
    def test_exit_contains_required_elements(self):
        result = SignalResult(
            ticker="BBRI",
            signal_type=SignalType.EXIT,
            score=35,
            confluence_count=2,
            signal_strength=SignalStrength.STRONG,
            reason="RSI overbought",
            exit_reasons=["RSI overbought", "MACD bearish cross"],
            narrative="Exit narrative",
            indicator_snapshot={"close": 5000, "rsi_14": 72},
        )
        active = {"entry_price": 4500, "take_profit": 5500, "stop_loss": 4200}
        msg = format_exit_message(result, active)

        assert "EXIT" in msg
        assert "BBRI" in msg
        assert "Alasan" in msg


class TestFormatWatchMessage:
    def test_watch_contains_required_elements(self):
        result = SignalResult(
            ticker="PTRO",
            signal_type=SignalType.WATCH,
            score=62,
            confluence_count=2,
            signal_strength=SignalStrength.NORMAL,
            reason="Approaching threshold",
        )
        msg = format_watch_message(result)
        assert "WATCHLIST" in msg
        assert "PTRO" in msg
        assert "62/100" in msg


class TestFormatDailySummary:
    def test_summary_format(self):
        msg = format_daily_summary(
            date_str="2026-05-04",
            duration=45.3,
            total=20,
            success=18,
            failed=2,
            signal_lines=["🟢 BUY BBCA (skor: 82)", "🟢 BUY BMRI (skor: 75)", "🔴 EXIT BBRI"],
        )
        assert "Daily Scan" in msg
        assert "2026" in msg
        assert "20 ticker" in msg
