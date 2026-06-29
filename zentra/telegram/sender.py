"""Telegram sender — async message delivery with rate limiting and retry.

Per PRD §9.1: 1s delay between messages, 3x retry with exponential backoff.
"""

from __future__ import annotations

import asyncio

import structlog
from telegram import Bot
from telegram.error import NetworkError, RetryAfter
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

log = structlog.get_logger()


class TelegramSender:
    """Sends messages to Telegram with rate limiting and retry."""

    RATE_LIMIT_DELAY: float = 1.0  # seconds between messages

    def __init__(self, bot_token: str, chat_id: str, admin_chat_id: str | None = None) -> None:
        self._bot = Bot(token=bot_token)
        self._chat_id = chat_id
        self._admin_chat_id = admin_chat_id or chat_id

    async def send_signal(self, message: str) -> bool:
        """Send one signal message. Returns True on success, False on failure."""
        try:
            await self._send_with_retry(self._chat_id, message)
            return True
        except Exception as e:
            log.error("telegram_send_failed", error=str(e), chat_id=self._chat_id)
            return False

    async def send_batch(self, messages: list[str]) -> list[bool]:
        """Send batch of messages with rate limiting. Returns success list."""
        results: list[bool] = []
        for i, msg in enumerate(messages):
            success = await self.send_signal(msg)
            results.append(success)
            if i < len(messages) - 1:
                await asyncio.sleep(self.RATE_LIMIT_DELAY)
        return results

    async def send_admin_alert(self, message: str) -> bool:
        """Send alert to admin chat. Best-effort, does not raise."""
        try:
            await self._send_with_retry(self._admin_chat_id, message)
            return True
        except Exception as e:
            log.error("admin_alert_failed", error=str(e))
            return False

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=8),
        retry=retry_if_exception_type((NetworkError, OSError, ConnectionError, RetryAfter)),
        reraise=True,
    )
    async def _send_with_retry(self, chat_id: str, message: str) -> None:
        """Send a single message with retry logic."""
        try:
            await self._bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode="MarkdownV2",
            )
        except RetryAfter as e:
            log.warning("telegram_rate_limited", retry_after=e.retry_after)
            await asyncio.sleep(e.retry_after)
            raise
