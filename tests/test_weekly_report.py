"""Regression tests for run_weekly_report() — Fix 1 guard.

Ensures RunStatus.COMPLETED → RunStatus.SUCCESS fix stays in place,
covering both code paths of run_weekly_report().
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from zentra.config import RunStatus
from zentra.orchestrator import ZENTRAOrchestrator


def _make_closed_signal(ticker: str, exit_pct: float, days_ago: int = 1, status: str = "CLOSED_TP") -> dict:
    closed_at = (datetime.now(tz=timezone.utc) - timedelta(days=days_ago)).isoformat()
    return {
        "ticker": ticker,
        "status": status,
        "entry_price": 1000,
        "close_price": int(1000 * (1 + exit_pct / 100)),
        "exit_pct": exit_pct,
        "closed_at": closed_at,
        "created_at": (datetime.now(tz=timezone.utc) - timedelta(days=days_ago + 5)).isoformat(),
    }


@pytest.mark.asyncio
class TestRunWeeklyReport:
    """Test both branches of run_weekly_report()."""

    async def _run_test(self, mock_run_logs, mock_signals, mock_sender):
        """Execute run_weekly_report under full mock context."""
        with (
            patch("zentra.orchestrator.MarketCalendar.from_env") as mock_cal,
            patch("zentra.orchestrator.validate_env"),
            patch("zentra.orchestrator.get_client"),
            patch("zentra.orchestrator.RunLogsRepo", return_value=mock_run_logs),
            patch("zentra.orchestrator.SignalsRepo", return_value=mock_signals),
            patch("zentra.orchestrator.TelegramSender") as mock_sender_cls,
        ):
            mock_cal.return_value = MagicMock()
            mock_sender_cls.return_value = mock_sender
            orch = ZENTRAOrchestrator(mode="weekly", dry_run=False)
            return await orch.run_weekly_report()

    async def test_no_closed_signals(self):
        """No closed signals → early return True, status=SUCCESS."""
        mock_run_logs = MagicMock()
        mock_run_logs.create_run.return_value = "test-run-id"
        mock_signals = MagicMock()
        mock_signals.get_all_closed_signals.return_value = []
        mock_signals.get_active_signals_count.return_value = 5

        result = await self._run_test(mock_run_logs, mock_signals, AsyncMock())

        assert result is True
        mock_run_logs.update_run.assert_called_once()
        kwargs = mock_run_logs.update_run.call_args[1]
        assert kwargs["status"] == RunStatus.SUCCESS

    async def test_with_closed_signals_success(self):
        """Closed signals present, send succeeds → status=SUCCESS."""
        mock_run_logs = MagicMock()
        mock_run_logs.create_run.return_value = "test-run-id"
        mock_signals = MagicMock()
        mock_signals.get_all_closed_signals.return_value = [
            _make_closed_signal("BBCA", 5.2),
            _make_closed_signal("BMRI", -2.1, status="CLOSED_SL"),
            _make_closed_signal("TLKM", 3.0),
        ]
        mock_signals.get_active_signals_count.return_value = 5
        mock_sender = AsyncMock()
        mock_sender.send_signal.return_value = True

        result = await self._run_test(mock_run_logs, mock_signals, mock_sender)

        assert result is True
        mock_run_logs.update_run.assert_called_once()
        kwargs = mock_run_logs.update_run.call_args[1]
        assert kwargs["status"] == RunStatus.SUCCESS
        mock_sender.send_signal.assert_awaited_once()

    async def test_with_closed_signals_send_failed(self):
        """Closed signals present, send fails → status=FAILED."""
        mock_run_logs = MagicMock()
        mock_run_logs.create_run.return_value = "test-run-id"
        mock_signals = MagicMock()
        mock_signals.get_all_closed_signals.return_value = [
            _make_closed_signal("BBCA", 5.2),
        ]
        mock_signals.get_active_signals_count.return_value = 5
        mock_sender = AsyncMock()
        mock_sender.send_signal.return_value = False

        result = await self._run_test(mock_run_logs, mock_signals, mock_sender)

        assert result is False
        mock_run_logs.update_run.assert_called_once()
        kwargs = mock_run_logs.update_run.call_args[1]
        assert kwargs["status"] == RunStatus.FAILED
        mock_sender.send_signal.assert_awaited_once()
