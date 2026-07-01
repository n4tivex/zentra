"""ZENTRA Orchestrator — multi-module scan coordinator."""

# Re-export for test-patching compatibility (tests target zentra.orchestrator.<name>)
from zentra.config import validate_env  # noqa: F401
from zentra.db.client import get_client  # noqa: F401
from zentra.db.run_logs_repo import RunLogsRepo  # noqa: F401
from zentra.db.signals_repo import SignalsRepo  # noqa: F401
from zentra.market_calendar import MarketCalendar  # noqa: F401

# Side-effect imports: attach methods from sub-modules onto ZENTRAOrchestrator
from zentra.orchestrator import (
    notify,  # noqa: F401
    pipeline,  # noqa: F401
    scoring,  # noqa: F401
)
from zentra.orchestrator.core import ZENTRAOrchestrator
from zentra.runtime import today_jakarta  # noqa: F401
from zentra.telegram.sender import TelegramSender  # noqa: F401

__all__ = ["ZENTRAOrchestrator"]
