"""Small DB helpers shared by repository classes."""

from __future__ import annotations


def looks_like_unique_conflict(error: Exception) -> bool:
    text = str(error).lower()
    return (
        "23505" in text
        or "duplicate key" in text
        or "unique constraint" in text
        or "already exists" in text
    )
