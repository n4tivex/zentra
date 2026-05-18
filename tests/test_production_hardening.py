from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from zentra.config import RunStatus, SignalResult, SignalStatus, SignalStrength, SignalType
from zentra.data.fetcher import FetchCoverage, MarketDataFetcher
from zentra.data.schema import validate_indicator_schema
from zentra.data.validator import DataValidator
from zentra.db.run_locks_repo import RunLocksRepo
from zentra.db.run_logs_repo import RunLogsRepo
from zentra.db.signals_repo import SignalsRepo
from zentra.exceptions import DataFetchError, DatabaseConflictError, DatabaseUpdateError
from zentra.orchestrator import ZENTRAOrchestrator
from zentra.telegram.formatter import format_buy_message, format_failure_message, format_rupiah


class TestRunLogsFailureSemantics:
    def test_update_run_failure_raises(self):
        client = MagicMock()
        client.table.return_value.update.return_value.eq.return_value.execute.side_effect = Exception("db down")
        repo = RunLogsRepo(client)

        with pytest.raises(DatabaseUpdateError):
            repo.update_run("run-1", status=RunStatus.FAILED)

    def test_update_run_persists_telemetry_fields(self):
        client = MagicMock()
        repo = RunLogsRepo(client)

        repo.update_run(
            "run-1",
            status=RunStatus.PARTIAL,
            fetched_count=10,
            cached_count=3,
            missing_count=2,
            failure_count=2,
            missing_tickers=["BBCA"],
            failed_fetch_tickers=["BMRI"],
            calendar_reason="official_holiday",
            data_readiness_status="ready",
            failure_category="partial_fetch",
            admin_alert_sent=True,
        )

        update = client.table.return_value.update.call_args.args[0]
        assert update["status"] == "PARTIAL"
        assert update["fetched_count"] == 10
        assert update["missing_tickers"] == ["BBCA"]
        assert update["admin_alert_sent"] is True


class TestRunLocks:
    def test_duplicate_run_lock_returns_none(self):
        client = MagicMock()
        client.table.return_value.insert.return_value.execute.side_effect = Exception(
            "duplicate key value violates unique constraint 23505"
        )
        repo = RunLocksRepo(client)

        assert repo.acquire(mode="morning", run_date="2026-05-18", slot="morning") is None

    def test_run_lock_build_key_is_slot_scoped(self):
        assert RunLocksRepo.build_key("closing", "2026-05-18", "16:45") == "closing:2026-05-18:16:45"


class TestSignalIdempotency:
    def test_insert_conflict_returns_existing_active_signal(self):
        existing = {"id": "sig-1", "ticker": "BBCA", "status": "ACTIVE", "signal_type": "BUY"}
        client = MagicMock()
        client.table.return_value.insert.return_value.execute.side_effect = Exception(
            "duplicate key value violates unique constraint 23505"
        )

        class Repo(SignalsRepo):
            def __init__(self, mock_client):
                super().__init__(mock_client)
                self.calls = 0

            def get_active_signal(self, ticker: str):
                self.calls += 1
                return None if self.calls == 1 else existing

        repo = Repo(client)
        signal = SignalResult(
            ticker="BBCA",
            signal_type=SignalType.BUY,
            score=80,
            confluence_count=4,
            signal_strength=SignalStrength.NORMAL,
        )

        assert repo.create_signal(signal, run_id="run-1") == existing

    def test_insert_conflict_without_existing_signal_raises_conflict_error(self):
        client = MagicMock()
        client.table.return_value.insert.return_value.execute.side_effect = Exception(
            "duplicate key value violates unique constraint 23505"
        )

        class Repo(SignalsRepo):
            def get_active_signal(self, ticker: str):
                return None

        repo = Repo(client)
        signal = SignalResult(
            ticker="BBCA",
            signal_type=SignalType.BUY,
            score=80,
            confluence_count=4,
            signal_strength=SignalStrength.NORMAL,
        )

        with pytest.raises(DatabaseConflictError):
            repo.create_signal(signal, run_id="run-1")

    def test_duplicate_close_is_idempotent_when_already_closed_to_target_status(self):
        client = MagicMock()
        client.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value.data = []

        class Repo(SignalsRepo):
            def _get_signal_by_id(self, signal_id: str):
                return {"id": signal_id, "status": SignalStatus.CLOSED_TP.value}

        repo = Repo(client)
        repo.close_signal("sig-1", SignalStatus.CLOSED_TP, exit_price=110, entry_price=100)

    def test_duplicate_close_detects_unexpected_zero_row_update(self):
        client = MagicMock()
        client.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value.data = []

        class Repo(SignalsRepo):
            def _get_signal_by_id(self, signal_id: str):
                return {"id": signal_id, "status": SignalStatus.EXPIRED.value}

        repo = Repo(client)
        with pytest.raises(DatabaseUpdateError):
            repo.close_signal("sig-1", SignalStatus.CLOSED_TP, exit_price=110, entry_price=100)

    def test_expiry_zero_row_update_is_idempotent(self):
        client = MagicMock()
        select_resp = MagicMock(data=[{"id": "sig-1", "created_at": "2026-01-01T00:00:00+00:00"}])
        update_resp = MagicMock(data=[])
        client.table.return_value.select.return_value.eq.return_value.lt.return_value.execute.return_value = select_resp
        client.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = update_resp
        repo = SignalsRepo(client)

        assert repo.expire_old_signals() == select_resp.data


class TestFetchCoverage:
    def test_full_fetch_success_tracks_fetched_tickers(self, bullish_df):
        raw = pd.concat({"BBCA.JK": bullish_df, "BMRI.JK": bullish_df}, axis=1)
        fetcher = MarketDataFetcher()
        with patch.object(fetcher, "_fetch_from_yahoo", return_value=raw):
            result = fetcher.fetch_all_with_coverage(["BBCA", "BMRI"])

        assert set(result.data) == {"BBCA", "BMRI"}
        assert result.coverage.fetched_tickers == ["BBCA", "BMRI"]
        assert result.coverage.is_partial is False

    def test_partial_fetch_tracks_missing_ticker(self, bullish_df):
        class Cache:
            def get_cached_data(self, ticker):
                return bullish_df if ticker == "BBCA" else None

        raw = pd.concat({"BMRI.JK": bullish_df}, axis=1)
        fetcher = MarketDataFetcher(ohlcv_repo=Cache())
        with patch.object(fetcher, "_fetch_from_yahoo", return_value=raw):
            result = fetcher.fetch_all_with_coverage(["BBCA", "BMRI", "BBRI"])

        assert set(result.data) == {"BBCA", "BMRI"}
        assert result.coverage.cached_tickers == ["BBCA"]
        assert result.coverage.fetched_tickers == ["BMRI"]
        assert result.coverage.missing_tickers == ["BBRI"]
        assert result.coverage.is_partial is True

    def test_cache_fallback_after_provider_failure_reports_partial(self, bullish_df):
        class Cache:
            def get_cached_data(self, ticker):
                return bullish_df if ticker == "BBCA" else None

        fetcher = MarketDataFetcher(ohlcv_repo=Cache())
        with patch.object(fetcher, "_fetch_from_yahoo", side_effect=Exception("provider down")):
            result = fetcher.fetch_all_with_coverage(["BBCA", "BMRI"])

        assert list(result.data) == ["BBCA"]
        assert result.coverage.provider_error == "provider down"
        assert result.coverage.missing_tickers == ["BMRI"]

    def test_all_fetch_failed_raises(self):
        fetcher = MarketDataFetcher()
        with patch.object(fetcher, "_fetch_from_yahoo", side_effect=Exception("provider down")):
            with pytest.raises(DataFetchError):
                fetcher.fetch_all_with_coverage(["BBCA"])

    def test_empty_response_is_tracked_as_failed_ticker(self):
        fetcher = MarketDataFetcher()
        with patch.object(fetcher, "_fetch_from_yahoo", return_value=pd.DataFrame()):
            with pytest.raises(DataFetchError):
                fetcher.fetch_all_with_coverage(["BBCA"])

        assert fetcher.last_coverage.empty_tickers == ["BBCA"]
        assert fetcher.last_coverage.missing_tickers == ["BBCA"]


class TestReadinessAndValidation:
    def test_closing_previous_trading_day_is_market_data_pending(self, bullish_df):
        orchestrator = ZENTRAOrchestrator(mode="closing", dry_run=True)
        df = bullish_df.copy()
        df.index = pd.date_range("2026-03-23", periods=len(df), freq="B")
        df.index = df.index[:-1].append(pd.DatetimeIndex(["2026-05-13"]))

        with patch("zentra.orchestrator.today_jakarta", return_value=date(2026, 5, 18)):
            status, latest, expected = orchestrator._data_readiness_status({"BBCA": df})

        assert status == "market_data_pending"
        assert latest == date(2026, 5, 13)
        assert expected == date(2026, 5, 18)

    def test_morning_older_than_expected_is_provider_stale(self, bullish_df):
        orchestrator = ZENTRAOrchestrator(mode="morning", dry_run=True)
        df = bullish_df.copy()
        df.index = pd.date_range(end="2026-05-12", periods=len(df), freq="B")

        with patch("zentra.orchestrator.today_jakarta", return_value=date(2026, 5, 18)):
            status, latest, expected = orchestrator._data_readiness_status({"BBCA": df})

        assert status == "provider_stale"
        assert latest == date(2026, 5, 12)
        assert expected == date(2026, 5, 13)

    def test_final_status_mapping(self):
        full = FetchCoverage(requested_tickers=["A", "B"], fetched_tickers=["A", "B"])
        partial = FetchCoverage(
            requested_tickers=["A", "B", "C", "D", "E"],
            fetched_tickers=["A", "B", "C", "D"],
            missing_tickers=["E"],
            failed_tickers=["E"],
        )
        broken = FetchCoverage(
            requested_tickers=["A", "B", "C", "D", "E"],
            fetched_tickers=["A", "B"],
            missing_tickers=["C", "D", "E"],
            failed_tickers=["C", "D", "E"],
        )

        assert ZENTRAOrchestrator._classify_run_status(
            failed_count=0,
            coverage=full,
            telegram_failed=0,
            persistence_failures=[],
        ) == "SUCCESS"
        assert ZENTRAOrchestrator._classify_run_status(
            failed_count=0,
            coverage=partial,
            telegram_failed=0,
            persistence_failures=[],
        ) == "PARTIAL"
        assert ZENTRAOrchestrator._classify_run_status(
            failed_count=0,
            coverage=broken,
            telegram_failed=0,
            persistence_failures=[],
        ) == "FAILED"
        assert ZENTRAOrchestrator._classify_run_status(
            failed_count=0,
            coverage=full,
            telegram_failed=1,
            persistence_failures=[],
        ) == "PARTIAL"

    def test_indicator_schema_rejects_nan_last_row(self, bullish_df):
        df = bullish_df.copy()
        for column in (
            "EMA_20",
            "EMA_50",
            "MACD_12_26_9",
            "MACDh_12_26_9",
            "MACDs_12_26_9",
            "RSI_14",
            "BBL_20_2.0_2.0",
            "BBM_20_2.0_2.0",
            "BBU_20_2.0_2.0",
            "ATRr_14",
            "VOL_SMA_20",
        ):
            df[column] = 1.0
        df.iloc[-1, df.columns.get_loc("RSI_14")] = float("nan")

        with pytest.raises(Exception, match="invalid last-row values"):
            validate_indicator_schema(df, "BBCA")

    def test_validator_expected_last_date_is_explicit(self, bullish_df):
        df = bullish_df.copy()
        df.index = pd.date_range(end="2026-05-12", periods=len(df), freq="B")

        result = DataValidator().validate("BBCA", df, expected_last_date=date(2026, 5, 13))

        assert not result.is_valid
        assert any("expected trading day" in error for error in result.errors)


class TestTelegramSafety:
    def test_missing_rupiah_value_formats_as_na(self):
        assert format_rupiah(None) == "N/A"

    def test_buy_message_handles_missing_snapshot(self):
        result = SignalResult(
            ticker="BBCA",
            signal_type=SignalType.BUY,
            score=70,
            confluence_count=3,
            signal_strength=SignalStrength.NORMAL,
            indicator_snapshot=None,
        )

        assert "BUY SIGNAL" in format_buy_message(result)

    def test_failure_message_does_not_call_provider_delay_a_holiday(self):
        msg = format_failure_message("2026-05-18", "market_data_pending", "latest=2026-05-13")
        assert "Data pasar belum final" in msg
        assert "libur" not in msg.lower()

    @pytest.mark.asyncio
    async def test_admin_alert_returns_false_on_failure(self):
        from zentra.telegram.sender import TelegramSender

        with patch("zentra.telegram.sender.Bot") as mock_bot:
            mock_bot.return_value.send_message = AsyncMock(side_effect=Exception("bad token"))
            sender = TelegramSender("token", "chat", "admin")

            assert await sender.send_admin_alert("test") is False
