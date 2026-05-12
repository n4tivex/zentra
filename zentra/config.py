"""ZENTRA configuration — constants, enums, data structures.

All thresholds, ticker lists, and type definitions per PRD §4, §7, §8.4, §15.2.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from zentra.exceptions import ConfigurationError


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SignalType(str, Enum):
    BUY = "BUY"
    EXIT = "EXIT"
    WATCH = "WATCH"
    NO_SIGNAL = "NO_SIGNAL"


class SignalStrength(str, Enum):
    STRONG = "STRONG"
    NORMAL = "NORMAL"
    BORDERLINE = "BORDERLINE"


class SignalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED_TP = "CLOSED_TP"
    CLOSED_SL = "CLOSED_SL"
    CLOSED_EXIT_SIGNAL = "CLOSED_EXIT_SIGNAL"
    EXPIRED = "EXPIRED"


class RunMode(str, Enum):
    MORNING = "morning"
    CLOSING = "closing"
    MANUAL = "manual"


class RunStatus(str, Enum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class ExitPriority(int, Enum):
    """Deterministic exit priority — lower value = higher priority."""
    STOP_LOSS = 1
    TAKE_PROFIT = 2
    HARD_EXIT = 3      # RSI overbought, etc.
    SOFT_EXIT = 4      # MACD crossover, score drop, etc.


# ---------------------------------------------------------------------------
# Signal lifecycle state machine (P1-13)
# ---------------------------------------------------------------------------

VALID_TRANSITIONS: dict[SignalStatus, tuple[SignalStatus, ...]] = {
    SignalStatus.ACTIVE: (
        SignalStatus.CLOSED_TP,
        SignalStatus.CLOSED_SL,
        SignalStatus.CLOSED_EXIT_SIGNAL,
        SignalStatus.EXPIRED,
    ),
    SignalStatus.CLOSED_TP: (),
    SignalStatus.CLOSED_SL: (),
    SignalStatus.CLOSED_EXIT_SIGNAL: (),
    SignalStatus.EXPIRED: (),
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    is_valid: bool
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    cleaned_df: Any | None = None


@dataclass
class RiskLevels:
    entry: int
    stop_loss: int
    take_profit: int
    risk_reward_ratio: float
    risk_pct: float
    reward_pct: float


@dataclass
class SignalResult:
    ticker: str
    signal_type: SignalType
    score: int
    confluence_count: int
    entry_price: Optional[int] = None
    stop_loss: Optional[int] = None
    take_profit: Optional[int] = None
    risk_pct: Optional[float] = None
    reward_pct: Optional[float] = None
    rr_ratio: Optional[float] = None
    narrative: Optional[str] = None
    indicator_snapshot: dict = field(default_factory=dict)
    reason: Optional[str] = None
    signal_strength: SignalStrength = SignalStrength.NORMAL
    exit_reasons: list[str] = field(default_factory=list)
    exit_status: Optional[SignalStatus] = None


# ---------------------------------------------------------------------------
# Frozen config dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ScoringConfig:
    BUY_THRESHOLD: int = 55
    WATCH_THRESHOLD: int = 45
    MIN_CONFLUENCE: int = 3
    MIN_CONFLUENCE_WATCH: int = 2
    MIN_RR_RATIO: float = 1.5
    MAX_SL_PCT: float = 0.08
    SL_ATR_MULTIPLIER: float = 1.5
    TP_ATR_MULTIPLIER: float = 2.5
    SIGNAL_EXPIRY_DAYS: int = 10
    EXIT_SCORE_THRESHOLD: int = 40
    MIN_HOLD_DAYS_BEFORE_EXIT: int = 1


@dataclass(frozen=True)
class DataConfig:
    LOOKBACK_DAYS: int = 90
    MIN_TRADING_DAYS: int = 30
    STALE_DATA_THRESHOLD_DAYS: int = 14
    FETCH_RETRY_ATTEMPTS: int = 3
    OHLCV_RETENTION_DAYS: int = 90


SCORING = ScoringConfig()
DATA = DataConfig()

# ---------------------------------------------------------------------------
# Ticker list (fixed, hardcoded per PRD §1)
# ---------------------------------------------------------------------------

TICKERS: tuple[str, ...] = (
    "BBCA", "BMRI", "BBRI", "NCKL", "RMKE",
    "BREN", "CBDK", "PTRO", "BRPT", "BUMI",
    "DEWA", "BRMS", "ENRG", "AMMN", "OASA",
    "ADMR", "RAJA", "SIMP", "GZCO", "PGEO",
)

# ---------------------------------------------------------------------------
# Ticker name mapping (PRD §8.4)
# ---------------------------------------------------------------------------

TICKER_NAMES: dict[str, str] = {
    "BBCA": "Bank Central Asia",
    "BMRI": "Bank Mandiri",
    "BBRI": "Bank Rakyat Indonesia",
    "NCKL": "Trimegah Bangun Persada",
    "RMKE": "Richmore Global (RMKE)",
    "BREN": "Barito Renewables Energy",
    "CBDK": "Cipta Bintang Djaya Karya",
    "PTRO": "Petrosea",
    "BRPT": "Barito Pacific",
    "BUMI": "Bumi Resources",
    "DEWA": "Darma Henwa",
    "BRMS": "Bumi Resources Minerals",
    "ENRG": "Energi Mega Persada",
    "AMMN": "Amman Mineral Internasional",
    "OASA": "Oakwood Semesta",
    "ADMR": "Adaro Minerals Indonesia",
    "RAJA": "Rukun Raharja",
    "SIMP": "Salim Ivomas Pratama",
    "GZCO": "Gozco Plantations",
    "PGEO": "Pertamina Geothermal Energy",
}


# ---------------------------------------------------------------------------
# DataFrame schema contracts (P1-10)
# ---------------------------------------------------------------------------

OHLCV_REQUIRED_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "volume")

INDICATOR_REQUIRED_COLUMNS: tuple[str, ...] = (
    "EMA_20", "EMA_50",
    "MACD_12_26_9", "MACDh_12_26_9", "MACDs_12_26_9",
    "RSI_14",
    "BBL_20_2.0_2.0", "BBM_20_2.0_2.0", "BBU_20_2.0_2.0",
    "ATRr_14",
    "VOL_SMA_20",
)


# ---------------------------------------------------------------------------
# Environment helpers (P2-20)
# ---------------------------------------------------------------------------

REQUIRED_ENV_VARS: list[str] = [
    "SUPABASE_URL",
    "SUPABASE_SERVICE_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "TELEGRAM_ADMIN_CHAT_ID",
]


def validate_env(mode: str | None = None) -> None:
    """Validate that all required environment variables are set.

    Args:
        mode: Optional run mode. When provided, also validates mode-specific vars.

    Raises:
        ConfigurationError: If any required env var is missing.
    """
    missing = [var for var in REQUIRED_ENV_VARS if not os.getenv(var)]
    if missing:
        raise ConfigurationError(
            f"Missing required env vars: {', '.join(missing)}. "
            f"Set them in .env or as environment variables."
        )

    # Validate values are not just whitespace
    empty = [
        var for var in REQUIRED_ENV_VARS
        if os.getenv(var, "").strip() == "" and var not in missing
    ]
    if empty:
        raise ConfigurationError(
            f"Env vars set but empty: {', '.join(empty)}"
        )


def get_env(name: str, default: str = "") -> str:
    """Get environment variable value."""
    return os.getenv(name, default)
