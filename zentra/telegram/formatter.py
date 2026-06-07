"""Telegram MarkdownV2 formatting utilities.

Per PRD §8.3: escape_markdown_v2, format_rupiah, message formatters.
Production-grade signal formatting — no branding, no fluff.
"""

from __future__ import annotations

import re
from datetime import datetime

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


def format_rupiah(amount: int | float | None) -> str:
    """Format number as Indonesian Rupiah (Rp 1.250)."""
    if amount is None:
        return "N/A"
    num = int(round(amount))
    formatted = f"{num:,}".replace(",", ".")
    return f"Rp {formatted}"


def _pct_str(value: float) -> str:
    """Format a percentage value with sign."""
    if value >= 0:
        return f"+{value:.1f}%"
    return f"{value:.1f}%"


def _strength_label(strength: SignalStrength) -> str:
    """Map signal strength to a concise label."""
    if strength == SignalStrength.STRONG:
        return "HIGH CONVICTION"
    elif strength == SignalStrength.BORDERLINE:
        return "BORDERLINE"
    return ""


def format_buy_message(result: SignalResult) -> str:
    """Format a BUY signal as Telegram MarkdownV2 message.

    Dynamic layout — sections adapt based on available data.
    """
    ticker = result.ticker
    name = TICKER_NAMES.get(ticker, ticker)
    narrative = result.narrative or ""
    snap = result.indicator_snapshot or {}

    entry = format_rupiah(result.entry_price) if result.entry_price else "N/A"
    tp = format_rupiah(result.take_profit) if result.take_profit else "N/A"
    sl = format_rupiah(result.stop_loss) if result.stop_loss else "N/A"
    reward_pct = result.reward_pct or 0
    risk_pct = result.risk_pct or 0
    rr = result.rr_ratio or 0
    score = result.score
    confluence = result.confluence_count

    # Dynamic hold estimate from ATR
    atr = snap.get("atr_14", 0)
    close = snap.get("close", 0)
    if atr and close and result.take_profit:
        tp_distance = abs(result.take_profit - close)
        days_min = max(3, int(tp_distance / atr * 0.7))
        days_max = min(10, int(tp_distance / atr * 1.5))
        if days_max <= days_min:
            days_max = days_min + 2
    else:
        days_min, days_max = 3, 7

    esc = escape_markdown_v2

    # Build header
    strength_tag = _strength_label(result.signal_strength)
    header = "🟢 *BUY SIGNAL*"
    if strength_tag:
        header += f" — {esc(strength_tag)}"

    # Calculate buy zone based on ATR (volatility-adjusted entry window)
    if atr and result.entry_price:
        zone_low = int(result.entry_price - atr * 0.3)
        zone_high = int(result.entry_price + atr * 0.5)
        buy_zone_str = f"{esc(format_rupiah(zone_low))} – {esc(format_rupiah(zone_high))}"
    else:
        buy_zone_str = None

    lines = [
        header,
        f"*${esc(ticker)}* — {esc(name)}",
        "",
        esc(narrative),
        "",
        "─── *Rencana Trading* ───",
        f"▸ Entry: *{esc(entry)}*",
        f"▸ Buy Zone: *{buy_zone_str}*" if buy_zone_str else None,
        f"▸ Target: *{esc(tp)}* \\(\\+{esc(f'{reward_pct:.1f}')}%\\)",
        f"▸ Stop Loss: *{esc(sl)}* \\(\\-{esc(f'{risk_pct:.1f}')}%\\)",
        f"▸ Risk/Reward: *1:{esc(f'{rr:.1f}')}*",
        f"▸ Estimasi hold: *{days_min}–{days_max} hari*",
        "",
    ]

    # Dynamic indicator snapshot
    rsi = snap.get("rsi_14", 0)
    vol_ratio = snap.get("volume_ratio", 0)
    bb_pct = snap.get("bb_percent", 0)

    indicator_parts = []
    if rsi:
        indicator_parts.append(f"RSI {rsi:.0f}")
    if vol_ratio:
        indicator_parts.append(f"Vol {vol_ratio:.1f}x")
    if bb_pct is not None and bb_pct > 0:
        indicator_parts.append(f"BB% {bb_pct:.0%}")

    if indicator_parts:
        lines.append(f"_📊 {esc(' · '.join(indicator_parts))} · Confluence {confluence}/5 · Skor {score}/100_")
    else:
        lines.append(f"_📊 Confluence {confluence}/5 · Skor {score}/100_")

    return "\n".join(line for line in lines if line is not None)


def format_exit_message(result: SignalResult, active_signal: dict) -> str:
    """Format an EXIT signal as Telegram MarkdownV2 message.

    Dynamic P&L calculation and reason formatting.
    """
    ticker = result.ticker
    name = TICKER_NAMES.get(ticker, ticker)
    narrative = result.narrative or ""
    active_signal = active_signal or {}
    snap = result.indicator_snapshot or {}
    close = snap.get("close", 0)
    entry = active_signal.get("entry_price", 0)
    exit_reasons = result.exit_reasons or []
    primary_reason = result.reason or "Technical reversal"

    esc = escape_markdown_v2

    # Determine header icon based on outcome
    if entry and close:
        pct = (close - entry) / entry * 100
        if pct >= 0:
            emoji = "🟡"
            pct_str = f"\\+{esc(f'{pct:.1f}')}%"
            outcome = "PROFIT"
        else:
            emoji = "🔴"
            pct_str = f"{esc(f'{pct:.1f}')}%"
            outcome = "LOSS"
    else:
        emoji = "🔴"
        pct = 0
        pct_str = "N/A"
        outcome = "EXIT"

    # Determine exit type label
    from zentra.config import SignalStatus
    exit_type_map = {
        SignalStatus.CLOSED_TP: "TARGET TERCAPAI ✅",
        SignalStatus.CLOSED_SL: "STOP LOSS ❌",
        SignalStatus.CLOSED_EXIT_SIGNAL: "SINYAL EXIT",
    }
    exit_label = exit_type_map.get(result.exit_status, "EXIT")

    # Calculate days held
    created_str = active_signal.get("created_at", "")
    days_held = ""
    if created_str:
        try:
            created = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
            held = (datetime.now(tz=created.tzinfo) - created).days
            days_held = f" · {held} hari"
        except (ValueError, TypeError):
            pass

    lines = [
        f"{emoji} *EXIT — {esc(exit_label)}*",
        f"*${esc(ticker)}* — {esc(name)}",
        "",
        esc(narrative),
        "",
        "─── *Detail Exit* ───",
        f"▸ Entry: *{esc(format_rupiah(entry))}*" if entry else None,
        f"▸ Exit: *{esc(format_rupiah(close))}*" if close else None,
        f"▸ P&L: *{pct_str}*{esc(days_held)}",
        "",
    ]

    # Reasons list (dynamic)
    if len(exit_reasons) > 1:
        lines.append(f"_Alasan: {esc(', '.join(exit_reasons[:3]))}_")
    elif exit_reasons:
        lines.append(f"_Alasan: {esc(exit_reasons[0])}_")

    return "\n".join(line for line in lines if line is not None)


def format_watch_message(result: SignalResult) -> str:
    """Format a WATCH alert for admin — concise info-only."""
    ticker = result.ticker
    name = TICKER_NAMES.get(ticker, ticker)
    score = result.score
    confluence = result.confluence_count
    snap = result.indicator_snapshot or {}
    esc = escape_markdown_v2

    # Compact indicator line
    rsi = snap.get("rsi_14", 0)
    vol_ratio = snap.get("volume_ratio", 0)
    details = []
    if rsi:
        details.append(f"RSI {rsi:.0f}")
    if vol_ratio:
        details.append(f"Vol {vol_ratio:.1f}x")
    detail_str = f" · {' · '.join(details)}" if details else ""

    lines = [
        f"👁 *WATCHLIST* — ${esc(ticker)}",
        f"{esc(name)} · Skor {score}/100 · Confluence {confluence}/5{esc(detail_str)}",
        f"_Belum cukup kuat untuk entry — pantau perkembangan_",
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
    """Format daily summary message."""
    esc = escape_markdown_v2
    signals = "\n".join(esc(s) for s in signal_lines) if signal_lines else "Tidak ada sinyal"

    lines = [
        f"📊 *Daily Scan — {esc(date_str)}*",
        "",
        f"{total} ticker dianalisis · {success} berhasil · {failed} gagal",
        f"Durasi: {esc(f'{duration:.1f}')} detik",
        "",
        signals,
    ]
    return "\n".join(lines)


def format_failure_message(date_str: str, reason_code: str, detail: str = "") -> str:
    """Format a public failure message without implying the wrong root cause."""
    esc = escape_markdown_v2
    reason_labels = {
        "market_data_pending": "Data pasar belum final",
        "provider_stale": "Data provider stale",
        "data_provider_error": "Fetch data gagal",
        "partial_fetch": "Coverage data tidak lengkap",
        "db_write": "Penyimpanan hasil gagal",
    }
    label = reason_labels.get(reason_code, "Scan gagal")
    lines = [
        f"📊 *Daily Scan — {esc(date_str)}*",
        "",
        esc(label),
    ]
    if detail:
        lines.append(esc(detail))
    return "\n".join(lines)


def format_weekly_performance_summary(
    date_str: str,
    total_closed: int,
    wins: int,
    losses: int,
    win_rate_pct: float,
    avg_return_pct: float,
    top_performers: list[dict],
    active_count: int,
) -> str:
    """Format weekly performance summary message."""
    esc = escape_markdown_v2

    lines = [
        f"📈 *Weekly Performance*",
        f"\\({esc(date_str)}\\)",
        "",
        f"*Win Rate*: {esc(f'{win_rate_pct:.1f}')}% \\({wins}W / {losses}L\\)",
        f"*Avg Return*: {esc(f'{avg_return_pct:+.2f}')}% per trade",
        "",
    ]

    if top_performers:
        lines.append("*Top Performers*:")
        for idx, p in enumerate(top_performers[:5], 1):
            t = p["ticker"]
            wr = p["win_rate_pct"]
            ret = p["avg_return_pct"]
            lines.append(f"{idx}\\. {esc(t)}: {esc(f'{wr:.0f}')}% WR \\({esc(f'{ret:+.1f}')}%\\)")
        lines.append("")

    lines.append(f"*Sinyal Aktif*: {active_count} ticker")

    return "\n".join(lines)
