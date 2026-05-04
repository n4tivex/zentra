"""Telegram MarkdownV2 formatting utilities.

Per PRD §8.3: escape_markdown_v2, format_rupiah, message formatters.
"""

from __future__ import annotations

import re

from zentra.config import SignalResult, SignalStrength, TICKER_NAMES


def escape_markdown_v2(text: str) -> str:
    """Escape special MarkdownV2 characters with backslash."""
    special = r"_*[]()~`>#+-=|{}.!"
    result = []
    for ch in text:
        if ch in special:
            result.append(f"\\{ch}")
        else:
            result.append(ch)
    return "".join(result)


def format_rupiah(amount: int | float) -> str:
    """Format number as Indonesian Rupiah (Rp 1.250)."""
    num = int(round(amount))
    formatted = f"{num:,}".replace(",", ".")
    return f"Rp {formatted}"


def format_buy_message(result: SignalResult) -> str:
    """Format a BUY signal as Telegram MarkdownV2 message per PRD §8.3."""
    ticker = result.ticker
    name = TICKER_NAMES.get(ticker, ticker)
    narrative = result.narrative or ""

    entry = format_rupiah(result.entry_price) if result.entry_price else "N/A"
    tp = format_rupiah(result.take_profit) if result.take_profit else "N/A"
    sl = format_rupiah(result.stop_loss) if result.stop_loss else "N/A"
    reward_pct = result.reward_pct or 0
    risk_pct = result.risk_pct or 0
    rr = result.rr_ratio or 0
    score = result.score

    # Estimate hold days from ATR
    atr = result.indicator_snapshot.get("atr_14", 0)
    close = result.indicator_snapshot.get("close", 0)
    if atr and close and result.take_profit:
        tp_distance = abs(result.take_profit - close)
        days_min = max(3, int(tp_distance / atr * 0.7))
        days_max = min(10, int(tp_distance / atr * 1.5))
        if days_max <= days_min:
            days_max = days_min + 2
    else:
        days_min, days_max = 3, 7

    esc = escape_markdown_v2

    lines = [
        "🟢 *ZENTRA — BUY SIGNAL*",
        f"*${esc(ticker)}* · {esc(name)}",
        "",
        esc(narrative),
        "",
        f"📌 Entry sekitar *{esc(entry)}*",
        f"🎯 Target *{esc(tp)}* \\(\\+{esc(f'{reward_pct:.1f}')}%\\)",
        f"🛑 Stop loss *{esc(sl)}* \\(\\-{esc(f'{risk_pct:.1f}')}%\\)",
        f"⏱ Estimasi hold *{days_min}–{days_max} hari*",
        "",
        f"_Skor: {score}/100 · Risk/reward: 1:{esc(f'{rr:.1f}')}_",
    ]
    return "\n".join(lines)


def format_exit_message(result: SignalResult, active_signal: dict) -> str:
    """Format an EXIT signal as Telegram MarkdownV2 message per PRD §8.3."""
    ticker = result.ticker
    narrative = result.narrative or ""
    close = result.indicator_snapshot.get("close", 0)
    entry = active_signal.get("entry_price", 0)
    primary_reason = result.reason or "Technical reversal"

    esc = escape_markdown_v2

    # Gain/loss line
    if entry and close:
        pct = (close - entry) / entry * 100
        current = format_rupiah(close)
        if pct >= 0:
            gain_line = f"📈 Profit: *\\+{esc(f'{pct:.1f}')}%* dari entry {esc(format_rupiah(entry))}"
        else:
            gain_line = f"📉 Loss: *{esc(f'{pct:.1f}')}%* dari entry {esc(format_rupiah(entry))}"
    else:
        current = "N/A"
        gain_line = ""

    strength_emoji = "🔴🔴" if result.signal_strength == SignalStrength.STRONG else "🔴"

    lines = [
        f"{strength_emoji} *ZENTRA — EXIT SIGNAL*",
        f"*${esc(ticker)}*",
        "",
        esc(narrative),
        "",
        f"📌 Exit di sekitar *{esc(format_rupiah(close) if close else 'N/A')}*",
        gain_line,
        "",
        f"_Alasan utama: {esc(primary_reason)}_",
    ]
    return "\n".join(line for line in lines if line is not None)


def format_watch_message(result: SignalResult) -> str:
    """Format a WATCH alert for admin per PRD §8.3."""
    ticker = result.ticker
    reason = result.reason or "Approaching threshold"
    score = result.score
    esc = escape_markdown_v2

    lines = [
        "👁 *ZENTRA — WATCHLIST UPDATE*",
        f"*${esc(ticker)}* masuk pantauan",
        "",
        esc(reason),
        "",
        f"_Skor: {score}/100 — belum cukup kuat untuk entry_",
    ]
    return "\n".join(lines)


def format_daily_summary(
    date_str: str,
    duration: float,
    total: int,
    success: int,
    failed: int,
    signal_lines: list[str],
) -> str:
    """Format daily summary message per PRD §9.3."""
    esc = escape_markdown_v2
    signals = "\n".join(esc(s) for s in signal_lines) if signal_lines else "Tidak ada sinyal"

    lines = [
        f"📊 *ZENTRA Daily Scan — {esc(date_str)}*",
        "",
        f"Scan selesai dalam {esc(f'{duration:.1f}')} detik",
        f"{total} ticker dianalisis · {success} berhasil · {failed} gagal",
        "",
        "Sinyal hari ini:",
        signals,
        "",
        "_ZENTRA v1\\.0 · IDX Swing Engine_",
    ]
    return "\n".join(lines)
