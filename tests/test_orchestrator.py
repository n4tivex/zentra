"""Tests for ScanOrchestrator data readiness."""

from __future__ import annotations

import pandas as pd

from zentra.orchestrator import ZENTRAOrchestrator


class TestDataReadiness:
    def test_latest_trade_date_warning(self, capsys):
        """All empty DataFrames should emit an all_data_empty warning."""
        orch = ZENTRAOrchestrator(dry_run=True)
        all_data = {"TICKER": pd.DataFrame()}
        result = orch._latest_trade_date(all_data)
        assert result is None
        captured = capsys.readouterr()
        assert "all_data_empty" in captured.out
