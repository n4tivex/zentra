"""Validate the versioned IDX market calendar source."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CALENDAR = ROOT / "zentra" / "market_calendar.json"


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def validate_calendar(path: Path, *, require_next_year: bool = False) -> list[str]:
    errors: list[str] = []
    payload = json.loads(path.read_text(encoding="utf-8"))
    closures = payload.get("closures")
    if not isinstance(closures, list):
        return ["calendar payload must contain a closures list"]

    seen: set[tuple[str, str]] = set()
    years: set[int] = set()
    for idx, record in enumerate(closures):
        prefix = f"closures[{idx}]"
        for key in ("date", "closure_type", "source_reference", "effective_year", "updated_at"):
            if not record.get(key):
                errors.append(f"{prefix} missing {key}")
        try:
            closed_date = _parse_date(str(record.get("date", "")))
        except ValueError:
            errors.append(f"{prefix} has invalid date")
            continue
        effective_year = int(record.get("effective_year", closed_date.year))
        years.add(effective_year)
        if effective_year != closed_date.year:
            errors.append(f"{prefix} effective_year does not match date year")
        key = (str(payload.get("market", "IDX")), closed_date.isoformat())
        if key in seen:
            errors.append(f"{prefix} duplicates {closed_date.isoformat()}")
        seen.add(key)

    current_year = datetime.now().year
    if current_year not in years:
        errors.append(f"calendar missing current year {current_year}")
    if require_next_year and current_year + 1 not in years:
        errors.append(f"calendar missing next year {current_year + 1}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate IDX market calendar JSON")
    parser.add_argument("--calendar", type=Path, default=DEFAULT_CALENDAR)
    parser.add_argument("--require-next-year", action="store_true")
    args = parser.parse_args()

    errors = validate_calendar(args.calendar, require_next_year=args.require_next_year)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"Calendar OK: {args.calendar}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
