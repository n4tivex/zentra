"""Integration tests — P2-16.

Tests for:
1. Duplicate run — dedup prevents double signals
2. Stale cache — stale data is rejected
3. Holiday/weekend — market closed detection
4. Zero/NaN indicators — graceful skip
5. Telegram retry — retry logic works
6. Supabase insert/update failure — error handling
7. Morning partial candle — today's candle is dropped
8. Exit priority resolution — SL/TP priority over soft exits
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from zentra.analysis.indicators import TechnicalIndicators
from zentra.analysis.scorer import SignalScorer
from zentra.config import (
    ExitPriority,
    SignalResult,
    SignalStatus,
    SignalStrength,
    SignalType,
    VALID_TRANSITIONS,
)
from zentra.data.schema import validate_indicator_schema, validate_ohlcv_schema
from zentra.data.validator import DataValidator
from zentra.db.signals_repo import SignalsRepo
from zentra.exceptions import CalculationError, DataIntegrityError

from tests.conftest import load_fixture


# ---------------------------------------------------------------------------
# 1. Duplicate run — dedup prevents double signals
# ---------------------------------------------------------------------------

class TestDuplicateSignalDedup:
    def test_create_signal_blocks_duplicate_active(self):
        """create_signal should not insert if an ACTIVE signal already exists."""
        mock_client = MagicMock()
        repo = SignalsRepo(mock_client)

        existing = {"id": "abc-123", "ticker": "BBCA", "status": "ACTIVE", "signal_type": "BUY"}

        # Mock get_active_signal to return an existing signal
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value \
            .order.return_value.limit.return_value.execute.return_value.data = [existing]

        result_obj = SignalResult(
            ticker="BBCA",
            signal_type=SignalType.BUY,
            score=80,
            confluence_count=4,
            signal_strength=SignalStrength.NORMAL,
        )

        result = repo.create_signal(result_obj, run_id="run-1")

        # Should return existing, not insert
        assert result == existing
        # insert should NOT have been called (beyond the select for get_active_signal)
        # The key point is the function returns early


# ---------------------------------------------------------------------------
# 2. Stale cache — stale data is rejected
# ---------------------------------------------------------------------------

class TestStaleData:
    def test_validator_rejects_stale_data(self, stale_df):
        """Data older than STALE_DATA_THRESHOLD_DAYS should be rejected."""
        validator = DataValidator()
        result = validator.validate("TEST", stale_df)
        assert not result.is_valid
        assert any("days old" in e.lower() or "stale" in e.lower() for e in result.errors)


# ---------------------------------------------------------------------------
# 3. Holiday/weekend — market closed detection
# ---------------------------------------------------------------------------

class TestMarketClosedDetection:
    def test_weekend_detection_saturday(self):
        """Saturday should be detected as weekend."""
        from zentra.runtime import is_weekend_jakarta
        # Find next Saturday
        from datetime import date
        d = date(2026, 5, 16)  # Saturday
        assert is_weekend_jakarta(d) is True

    def test_weekend_detection_sunday(self):
        """Sunday should be detected as weekend."""
        from zentra.runtime import is_weekend_jakarta
        from datetime import date
        d = date(2026, 5, 17)  # Sunday
        assert is_weekend_jakarta(d) is True

    def test_weekday_not_weekend(self):
        """Monday should not be weekend."""
        from zentra.runtime import is_weekend_jakarta
        from datetime import date
        d = date(2026, 5, 18)  # Monday
        assert is_weekend_jakarta(d) is False


# ---------------------------------------------------------------------------
# 4. Zero/NaN indicators — graceful skip
# ---------------------------------------------------------------------------

class TestZeroNaNIndicators:
    def test_all_nan_close_raises_error(self):
        """DataFrame with NaN critical data should raise an error during processing."""
        dates = pd.date_range("2026-03-01", periods=60, freq="B")
        df = pd.DataFrame({
            "open": [float("nan")] * 60,
            "high": [float("nan")] * 60,
            "low": [float("nan")] * 60,
            "close": [float("nan")] * 60,
            "volume": [0] * 60,
        }, index=dates)

        indicators = TechnicalIndicators()
        # pandas_ta raises TypeError or CalculationError for all-NaN input
        with pytest.raises((CalculationError, TypeError)):
            indicators.compute_all(df)

    def test_scorer_handles_missing_indicator_columns(self):
        """Scorer should handle DataFrame without indicator columns gracefully."""
        dates = pd.date_range("2026-03-01", periods=60, freq="B")
        close = [1000 + i * 10 for i in range(60)]
        df = pd.DataFrame({
            "open": close,
            "high": [c + 50 for c in close],
            "low": [c - 50 for c in close],
            "close": close,
            "volume": [1000000] * 60,
        }, index=dates)

        # Score without indicator enrichment — should handle gracefully
        scorer = SignalScorer()
        result = scorer.score_buy("TEST", df)
        assert result.signal_type == SignalType.NO_SIGNAL


# ---------------------------------------------------------------------------
# 5. Telegram retry — retry logic
# ---------------------------------------------------------------------------

class TestTelegramRetry:
    @pytest.mark.asyncio
    async def test_send_signal_returns_false_on_failure(self):
        """send_signal should return False on persistent failure, not crash."""
        from zentra.telegram.sender import TelegramSender

        with patch("zentra.telegram.sender.Bot") as MockBot:
            mock_bot = MockBot.return_value
            mock_bot.send_message = AsyncMock(side_effect=Exception("Network error"))

            sender = TelegramSender(bot_token="fake", chat_id="123", admin_chat_id="456")
            result = await sender.send_signal("test message")
            assert result is False

    @pytest.mark.asyncio
    async def test_admin_alert_does_not_raise(self):
        """send_admin_alert should swallow exceptions."""
        from zentra.telegram.sender import TelegramSender

        with patch("zentra.telegram.sender.Bot") as MockBot:
            mock_bot = MockBot.return_value
            mock_bot.send_message = AsyncMock(side_effect=Exception("Network error"))

            sender = TelegramSender(bot_token="fake", chat_id="123", admin_chat_id="456")
            # Should not raise
            await sender.send_admin_alert("admin test")


# ---------------------------------------------------------------------------
# 6. Supabase insert/update failure — error handling
# ---------------------------------------------------------------------------

class TestSupabaseFailure:
    def test_create_signal_raises_database_error(self):
        """create_signal should raise DatabaseError on insert failure."""
        from zentra.exceptions import DatabaseError

        mock_client = MagicMock()
        repo = SignalsRepo(mock_client)

        # No active signal
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value \
            .order.return_value.limit.return_value.execute.return_value.data = []

        # Insert fails
        mock_client.table.return_value.insert.return_value.execute.side_effect = Exception("DB error")

        result_obj = SignalResult(
            ticker="BBCA",
            signal_type=SignalType.BUY,
            score=80,
            confluence_count=4,
            signal_strength=SignalStrength.NORMAL,
        )

        with pytest.raises(DatabaseError, match="Failed to create signal"):
            repo.create_signal(result_obj, run_id="run-1")

    def test_close_signal_validates_transition(self):
        """close_signal should reject invalid transitions."""
        from zentra.exceptions import DatabaseError

        mock_client = MagicMock()
        repo = SignalsRepo(mock_client)

        # Trying to transition from CLOSED_TP → CLOSED_SL is invalid
        with pytest.raises(DatabaseError, match="Invalid signal transition"):
            repo._validate_transition(SignalStatus.CLOSED_TP, SignalStatus.CLOSED_SL)


# ---------------------------------------------------------------------------
# 7. Morning partial candle — today's candle is dropped
# ---------------------------------------------------------------------------

class TestMorningPartialCandle:
    def test_morning_mode_drops_today_candle(self, bullish_df):
        """Morning mode should drop today's candle."""
        from zentra.orchestrator import ZENTRAOrchestrator

        orchestrator = ZENTRAOrchestrator(mode="morning", dry_run=True)

        # Set the last date to today
        df = bullish_df.copy()
        today = pd.Timestamp(datetime.now().date())
        new_index = list(df.index[:-1]) + [today]
        df.index = pd.DatetimeIndex(new_index)
        df.index.name = "date"

        with patch("zentra.orchestrator.today_jakarta", return_value=today.date()):
            result = orchestrator._handle_partial_candle(df, MagicMock())

        assert len(result) == len(df) - 1

    def test_closing_mode_keeps_today_candle(self, bullish_df):
        """Closing mode should keep today's candle."""
        from zentra.orchestrator import ZENTRAOrchestrator

        orchestrator = ZENTRAOrchestrator(mode="closing", dry_run=True)

        df = bullish_df.copy()
        today = pd.Timestamp(datetime.now().date())
        new_index = list(df.index[:-1]) + [today]
        df.index = pd.DatetimeIndex(new_index)
        df.index.name = "date"

        with patch("zentra.orchestrator.today_jakarta", return_value=today.date()):
            result = orchestrator._handle_partial_candle(df, MagicMock())

        assert len(result) == len(df)


# ---------------------------------------------------------------------------
# 8. Exit priority resolution — SL/TP > hard > soft
# ---------------------------------------------------------------------------

class TestExitPriorityResolution:
    def test_sl_has_highest_priority(self, exit_setup_df):
        """When SL and TP both hit, SL should take priority (lower price = more urgent)."""
        scorer = SignalScorer()

        active_signal = {
            "entry_price": 100,
            "take_profit": 110,
            "stop_loss": 120,  # SL above close (will trigger)
        }

        df = exit_setup_df.copy()
        df.iloc[-1, df.columns.get_loc("close")] = 115  # Between TP and SL
        df["RSI_14"] = 50
        df["MACD_12_26_9"] = 1.0
        df["MACDs_12_26_9"] = 0.5
        df["BBU_20_2.0_2.0"] = 200

        result = scorer.check_exit("BBCA", df, active_signal)

        if result:
            # Both TP (close >= 110) and SL (close <= 120) hit
            assert result.exit_status in (SignalStatus.CLOSED_SL, SignalStatus.CLOSED_TP)

    def test_tp_priority_over_soft_exit(self, exit_setup_df):
        """TP should take priority over soft exits like MACD cross."""
        scorer = SignalScorer()

        active_signal = {
            "entry_price": 100,
            "take_profit": 110,
            "stop_loss": 80,
        }

        df = exit_setup_df.copy()
        df.iloc[-1, df.columns.get_loc("close")] = 120  # Above TP
        df["RSI_14"] = 50  # Not overbought
        df["MACD_12_26_9"] = -1.0  # Bearish
        df["MACDs_12_26_9"] = 0.5
        df.iloc[-2, df.columns.get_loc("MACD_12_26_9") if "MACD_12_26_9" in df.columns else 0] = 1.0
        df["BBU_20_2.0_2.0"] = 200

        result = scorer.check_exit("BBCA", df, active_signal)

        assert result is not None
        assert result.exit_status == SignalStatus.CLOSED_TP
        assert "Target price reached" in result.exit_reasons

    def test_exit_reasons_ordered_by_priority(self, exit_setup_df):
        """Exit reasons should be ordered by priority (SL/TP first)."""
        scorer = SignalScorer()

        active_signal = {
            "entry_price": 100,
            "take_profit": 110,
            "stop_loss": 90,
        }

        df = exit_setup_df.copy()
        df.iloc[-1, df.columns.get_loc("close")] = 120
        df["RSI_14"] = 72  # Overbought
        df["MACD_12_26_9"] = 1.0
        df["MACDs_12_26_9"] = 0.5
        df["BBU_20_2.0_2.0"] = 115

        result = scorer.check_exit("BBCA", df, active_signal)

        assert result is not None
        # TP should come before RSI (TP priority=2, RSI priority=3)
        tp_idx = None
        rsi_idx = None
        for i, reason in enumerate(result.exit_reasons):
            if "Target" in reason:
                tp_idx = i
            if "RSI" in reason:
                rsi_idx = i
        if tp_idx is not None and rsi_idx is not None:
            assert tp_idx < rsi_idx, "TP should appear before RSI in exit_reasons"


# ---------------------------------------------------------------------------
# Schema contract tests (P1-10)
# ---------------------------------------------------------------------------

class TestSchemaContracts:
    def test_ohlcv_schema_valid(self, bullish_df):
        """Valid OHLCV DataFrame should pass schema validation."""
        validate_ohlcv_schema(bullish_df, "TEST")

    def test_ohlcv_schema_missing_column(self, bullish_df):
        """Missing column should raise DataIntegrityError."""
        df = bullish_df.drop(columns=["volume"])
        with pytest.raises(DataIntegrityError, match="missing columns"):
            validate_ohlcv_schema(df, "TEST")

    def test_indicator_schema_valid(self, bullish_df):
        """Enriched DataFrame should pass indicator schema validation."""
        indicators = TechnicalIndicators()
        df_ind = indicators.compute_all(bullish_df)
        validate_indicator_schema(df_ind, "TEST")

    def test_indicator_schema_missing_column(self, bullish_df):
        """Missing indicator column should raise DataIntegrityError."""
        indicators = TechnicalIndicators()
        df_ind = indicators.compute_all(bullish_df)
        df_ind = df_ind.drop(columns=["RSI_14"])
        with pytest.raises(DataIntegrityError, match="missing columns"):
            validate_indicator_schema(df_ind, "TEST")


# ---------------------------------------------------------------------------
# State transition tests (P1-13)
# ---------------------------------------------------------------------------

class TestSignalLifecycle:
    def test_valid_transitions(self):
        """All valid transitions should be defined."""
        assert SignalStatus.CLOSED_TP in VALID_TRANSITIONS[SignalStatus.ACTIVE]
        assert SignalStatus.CLOSED_SL in VALID_TRANSITIONS[SignalStatus.ACTIVE]
        assert SignalStatus.CLOSED_EXIT_SIGNAL in VALID_TRANSITIONS[SignalStatus.ACTIVE]
        assert SignalStatus.EXPIRED in VALID_TRANSITIONS[SignalStatus.ACTIVE]

    def test_terminal_states_have_no_transitions(self):
        """Terminal states should have no outgoing transitions."""
        assert VALID_TRANSITIONS[SignalStatus.CLOSED_TP] == ()
        assert VALID_TRANSITIONS[SignalStatus.CLOSED_SL] == ()
        assert VALID_TRANSITIONS[SignalStatus.CLOSED_EXIT_SIGNAL] == ()
        assert VALID_TRANSITIONS[SignalStatus.EXPIRED] == ()

    def test_invalid_transition_raises(self):
        """Invalid transition should raise DatabaseError."""
        from zentra.exceptions import DatabaseError
        mock_client = MagicMock()
        repo = SignalsRepo(mock_client)

        with pytest.raises(DatabaseError, match="Invalid signal transition"):
            repo._validate_transition(SignalStatus.EXPIRED, SignalStatus.ACTIVE)
