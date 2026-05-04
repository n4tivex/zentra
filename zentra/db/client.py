"""Supabase client singleton.

Uses service_role key for backend access (bypasses RLS).
"""

from __future__ import annotations

import os

from supabase import Client, create_client

_client: Client | None = None


def get_client() -> Client:
    """Return a singleton Supabase client instance."""
    global _client
    if _client is None:
        url = os.getenv("SUPABASE_URL", "")
        key = os.getenv("SUPABASE_SERVICE_KEY", "")
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
        _client = create_client(url, key)
    return _client


def reset_client() -> None:
    """Reset the client (for testing)."""
    global _client
    _client = None
