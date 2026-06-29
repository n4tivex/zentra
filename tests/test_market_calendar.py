from __future__ import annotations

import json
from datetime import date

from zentra.market_calendar import MarketCalendar


class TestMarketCalendar:
    def test_known_2026_holiday_is_closed(self):
        calendar = MarketCalendar.from_env()
        assert calendar.is_closed(date(2026, 5, 14)) is True
        assert calendar.is_closed(date(2026, 5, 15)) is True

    def test_monday_after_long_holiday_is_open(self):
        calendar = MarketCalendar.from_env()
        assert calendar.is_closed(date(2026, 5, 18)) is False

    def test_previous_trading_day_skips_holiday_and_weekend(self):
        calendar = MarketCalendar.from_env()
        assert calendar.previous_trading_day(date(2026, 5, 18)) == date(2026, 5, 13)

    def test_expected_trade_day_matches_mode(self):
        calendar = MarketCalendar.from_env()
        assert calendar.expected_last_trade_day(date(2026, 5, 18), mode="morning") == date(2026, 5, 13)
        assert calendar.expected_last_trade_day(date(2026, 5, 18), mode="closing") == date(2026, 5, 18)

    def test_weekend_reason_code(self):
        calendar = MarketCalendar.from_env()
        assert calendar.closure_reason(date(2026, 5, 16)) == "weekend"

    def test_official_holiday_reason_code(self):
        calendar = MarketCalendar.from_env()
        assert calendar.closure_reason(date(2026, 5, 14)) == "official_holiday"

    def test_emergency_override_reason_code(self, monkeypatch):
        monkeypatch.setenv("IDX_MARKET_HOLIDAYS", "2026-05-18")
        calendar = MarketCalendar.from_env()
        assert calendar.closure_reason(date(2026, 5, 18)) == "calendar_override"

    def test_year_rollover_comes_from_json_file(self, tmp_path, monkeypatch):
        calendar_file = tmp_path / "calendar.json"
        calendar_file.write_text(
            json.dumps(
                {
                    "closures": [
                        {
                            "date": "2027-01-04",
                            "closure_type": "official_holiday",
                            "source_reference": "test",
                            "effective_year": 2027,
                            "updated_at": "2026-05-18T00:00:00+07:00",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("IDX_MARKET_CALENDAR_FILE", str(calendar_file))
        monkeypatch.delenv("IDX_MARKET_HOLIDAYS", raising=False)

        calendar = MarketCalendar.from_env()

        assert calendar.is_closed(date(2027, 1, 4)) is True
        assert calendar.closure_reason(date(2027, 1, 4)) == "official_holiday"

    def test_legacy_closed_dates_constructor_still_works(self):
        calendar = MarketCalendar(closed_dates={date(2026, 7, 1)})
        assert calendar.closure_reason(date(2026, 7, 1)) == "official_holiday"
