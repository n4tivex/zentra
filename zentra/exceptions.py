"""Custom exception hierarchy for ZENTRA.

All exceptions defined per PRD §14.1.
"""

from __future__ import annotations


class ZENTRABaseError(Exception):
    """Base class untuk semua ZENTRA exceptions."""


class DataFetchError(ZENTRABaseError):
    """Gagal fetch data dari yfinance (network, parsing, dll.)"""


class TickerNotFoundError(DataFetchError):
    """Ticker tidak ditemukan di Yahoo Finance."""


class InsufficientDataError(ZENTRABaseError):
    """Data tidak cukup untuk kalkulasi indikator (< 30 baris)."""


class StaleDataError(ZENTRABaseError):
    """Data terlalu lama (> 5 hari dari hari ini)."""


class DataIntegrityError(ZENTRABaseError):
    """Data mengandung nilai yang tidak logis (high < low, dll.)."""


class CalculationError(ZENTRABaseError):
    """Indikator menghasilkan NaN atau nilai tidak valid."""


class DatabaseError(ZENTRABaseError):
    """Error saat operasi Supabase."""

    category = "database"


class DatabaseInsertError(DatabaseError):
    """Supabase insert failure."""

    category = "db_insert"


class DatabaseUpdateError(DatabaseError):
    """Supabase update failure."""

    category = "db_update"


class DatabaseDeleteError(DatabaseError):
    """Supabase delete failure."""

    category = "db_delete"


class DatabaseConflictError(DatabaseError):
    """Supabase uniqueness or idempotency conflict."""

    category = "db_conflict"


class TelegramError(ZENTRABaseError):
    """Error saat kirim pesan ke Telegram."""


class ConfigurationError(ZENTRABaseError):
    """Konfigurasi tidak valid atau env var hilang."""
