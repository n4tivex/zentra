"""Market calendar helpers for BEI/IDX trading days.

Weekend detection is explicit in code. Holiday and special closure dates are
loaded from a versioned JSON source so yearly updates do not require code
changes. `IDX_MARKET_HOLIDAYS` remains an emergency override only.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog

from zentra.runtime import today_jakarta

log = structlog.get_logger()

BUNDLED_CALENDAR_PATH = Path(__file__).with_name("market_calendar.json")
VALID_REASON_CODES = {
    "weekend",
    "official_holiday",
    "market_data_pending",
    "provider_stale",
    "calendar_override",
}


@dataclass(frozen=True)
class MarketClosure:
    date: date
    closure_type: str
    source_reference: str
    effective_year: int
    updated_at: str
    description: str = ""


@dataclass(frozen=True)
class MarketStatus:
    is_open: bool
    reason_code: str | None = None
    trade_date: date | None = None


def _coerce_date(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(value, "%Y-%m-%d").date()


def _parse_extra_closed_dates(raw: str) -> set[date]:
    dates: set[date] = set()
    for part in raw.split(","):
        item = part.strip()
        if not item:
            continue
        try:
            dates.add(_coerce_date(item))
        except ValueError:
            log.warning("market_calendar_override_invalid", value=item)
    return dates


def _load_calendar_payload(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except FileNotFoundError as e:
        raise ValueError(f"Market calendar file not found: {path}") from e
    except json.JSONDecodeError as e:
        raise ValueError(f"Market calendar file is invalid JSON: {path}") from e

    if not isinstance(payload, dict):
        raise ValueError("Market calendar payload must be a JSON object")
    closures = payload.get("closures")
    if not isinstance(closures, list):
        raise ValueError("Market calendar payload must include a closures list")
    return payload


def _closure_from_record(record: dict[str, Any]) -> MarketClosure:
    closed_date = _coerce_date(str(record["date"]))
    closure_type = str(record.get("closure_type") or "official_holiday")
    if closure_type not in {"official_holiday", "calendar_override"}:
        closure_type = "official_holiday"

    effective_year = int(record.get("effective_year") or closed_date.year)
    return MarketClosure(
        date=closed_date,
        closure_type=closure_type,
        source_reference=str(record.get("source_reference") or "versioned calendar"),
        effective_year=effective_year,
        updated_at=str(record.get("updated_at") or ""),
        description=str(record.get("description") or ""),
    )


@dataclass(frozen=True, init=False)
class MarketCalendar:
    """Explicit BEI/IDX trading calendar."""

    closures: dict[date, MarketClosure]
    override_dates: frozenset[date] = frozenset()
    source_path: Path | None = None

    def __init__(
        self,
        closures: dict[date, MarketClosure] | set[date] | frozenset[date] | None = None,
        override_dates: set[date] | frozenset[date] | None = None,
        source_path: Path | None = None,
        closed_dates: set[date] | frozenset[date] | None = None,
    ) -> None:
        raw_closures = closures if closures is not None else closed_dates or {}
        if isinstance(raw_closures, dict):
            closure_map = raw_closures
        else:
            closure_map = {
                closed_date: MarketClosure(
                    date=closed_date,
                    closure_type="official_holiday",
                    source_reference="legacy closed_dates",
                    effective_year=closed_date.year,
                    updated_at="",
                )
                for closed_date in raw_closures
            }
        object.__setattr__(self, "closures", closure_map)
        object.__setattr__(self, "override_dates", frozenset(override_dates or set()))
        object.__setattr__(self, "source_path", source_path)

    @classmethod
    def from_env(cls) -> "MarketCalendar":
        calendar_path = Path(os.getenv("IDX_MARKET_CALENDAR_FILE", str(BUNDLED_CALENDAR_PATH)))
        extra = _parse_extra_closed_dates(os.getenv("IDX_MARKET_HOLIDAYS", ""))
        calendar = cls.from_file(calendar_path, override_dates=extra)
        if extra:
            log.warning(
                "market_calendar_override_loaded",
                count=len(extra),
                dates=sorted(d.isoformat() for d in extra),
            )
        return calendar

    @classmethod
    def from_file(cls, path: Path | str, override_dates: set[date] | None = None) -> "MarketCalendar":
        resolved = Path(path)
        payload = _load_calendar_payload(resolved)
        return cls.from_records(
            payload["closures"],
            override_dates=override_dates,
            source_path=resolved,
        )

    @classmethod
    def from_records(
        cls,
        records: list[dict[str, Any]],
        *,
        override_dates: set[date] | None = None,
        source_path: Path | None = None,
    ) -> "MarketCalendar":
        closures: dict[date, MarketClosure] = {}
        for record in records:
            closure = _closure_from_record(record)
            closures[closure.date] = closure
        return cls(
            closures=closures,
            override_dates=frozenset(override_dates or set()),
            source_path=source_path,
        )

    @property
    def closed_dates(self) -> frozenset[date]:
        """Compatibility view for older callers/tests."""
        return frozenset(set(self.closures) | set(self.override_dates))

    def is_weekend(self, value: date | datetime | None = None) -> bool:
        value = today_jakarta() if value is None else value
        value = _coerce_date(value)
        return value.weekday() >= 5

    def is_closed(self, value: date | datetime | None = None) -> bool:
        return self.closure_reason(value) is not None

    def closure_reason(self, value: date | datetime | None = None) -> str | None:
        value = today_jakarta() if value is None else value
        value = _coerce_date(value)
        if self.is_weekend(value):
            return "weekend"
        if value in self.override_dates:
            return "calendar_override"
        if value in self.closures:
            return "official_holiday"
        return None

    def status_for(self, value: date | datetime | None = None) -> MarketStatus:
        value = today_jakarta() if value is None else value
        value = _coerce_date(value)
        reason = self.closure_reason(value)
        return MarketStatus(is_open=reason is None, reason_code=reason, trade_date=value)

    def previous_trading_day(self, value: date | datetime | None = None) -> date:
        value = today_jakarta() if value is None else value
        value = _coerce_date(value)

        candidate = value - timedelta(days=1)
        while self.is_closed(candidate):
            candidate -= timedelta(days=1)
        return candidate

    def expected_last_trade_day(
        self,
        value: date | datetime | None = None,
        mode: str = "morning",
    ) -> date:
        """Return the trading day whose candle should be available for the mode."""
        value = today_jakarta() if value is None else value
        value = _coerce_date(value)
        if mode in {"closing", "midday"}:
            return value
        return self.previous_trading_day(value)


def _bundled_2026_closed_dates() -> frozenset[date]:
    payload = _load_calendar_payload(BUNDLED_CALENDAR_PATH)
    records = payload["closures"]
    return frozenset(
        _coerce_date(str(r["date"]))
        for r in records
        if int(r.get("effective_year") or _coerce_date(str(r["date"])).year) == 2026
    )


DEFAULT_CLOSED_DATES_2026 = _bundled_2026_closed_dates()
