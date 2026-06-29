"""Telegram MarkdownV2 formatting utilities.

Per PRD §8.3: escape_markdown_v2, format_rupiah, message formatters.
Production-grade signal formatting — no branding, no fluff.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

from zentra.config import SignalResult, SignalStrength, SignalStatus, TICKER_NAMES

WIB = timezone(timedelta(hours=7))


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


def _pct_str_human(value: float) -> str:
    """Format a percentage for signal_lines (compact)."""
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


def _format_wib(iso_str: str) -> str:
    """Format ISO timestamp to WIB date + time."""
    if not iso_str:
        return "N/A"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        wib = dt.astimezone(WIB)
        return wib.strftime("%d %b %Y \u00b7 %H:%M WIB")
    except (ValueError, TypeError):
        return iso_str


def _format_wib_date(iso_str: str) -> str:
    """Format ISO timestamp to WIB date only."""
    if not iso_str:
        return "N/A"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        wib = dt.astimezone(WIB)
        return wib.strftime("%d %b %Y")
    except (ValueError, TypeError):
        return iso_str


def _reason_label(reason: str | None) -> str:
    """Map classify reason to user-facing label."""
    labels = {
        "rsi_not_crossed": "RSI belum crossing 50, momentum belum terkonfirmasi",
        "macd_not_confirmed": "MACD belum golden cross, konfirmasi masih kurang",
        "watch_signal": "Skor di ambang WATCH tapi belum cukup untuk BUY",
    }
    return labels.get(reason or "", "Menunggu konfirmasi tambahan")


def _build_indicator_footer(snap: dict, confluence: int, score: int) -> str:
    """Build dynamic indicator snapshot footer line."""
    esc = escape_markdown_v2
    rsi = snap.get("rsi_14", 0)
    vol_ratio = snap.get("volume_ratio", 0)
    bb_pct = snap.get("bb_percent", 0)

    parts = []
    if rsi:
        parts.append(f"RSI {rsi:.0f}")
    if vol_ratio:
        parts.append(f"Vol {vol_ratio:.1f}x")
    if bb_pct is not None and bb_pct > 0:
        parts.append(f"BB% {bb_pct:.0%}")

    line = f"CF {confluence}/5 \u00b7 Skor {score}/100"
    if parts:
        line = f"{' \u00b7 '.join(parts)} \u00b7 {line}"

    return f"_📊 {esc(line)}_"


def format_buy_message(result: SignalResult) -> str:
    """Format a BUY signal — date, conviction, narrative, trading plan."""
    esc = escape_markdown_v2
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

    strength_tag = _strength_label(result.signal_strength)
    header = "🟢 *BUY SIGNAL*"
    if strength_tag:
        header += f" \u2014 {esc(strength_tag)}"

    if atr and result.entry_price:
        zone_low = int(result.entry_price - atr * 0.3)
        zone_high = int(result.entry_price + atr * 0.5)
        buy_zone_str = f"{esc(format_rupiah(zone_low))} \u2013 {esc(format_rupiah(zone_high))}"
    else:
        buy_zone_str = None

    lines = [
        header,
        f"*\\${esc(ticker)}* \u2014 {esc(name)}",
        "",
        f"📅 {esc(_format_wib(result.created_at))}" if result.created_at else None,
        f"⚠️ {esc('Akan expired otomatis jika tidak ada EXIT dalam 10 hari')}",
        "",
        esc(narrative),
        "",
        "\u2500\u2500\u2500 *Rencana Trading* \u2500\u2500\u2500",
        f"\u25b8 Entry: *{esc(entry)}*",
        f"\u25b8 Buy Zone: *{buy_zone_str}*" if buy_zone_str else None,
        f"\u25b8 Target: *{esc(tp)}* \\(\\+{esc(f'{reward_pct:.1f}')}%\\)",
        f"\u25b8 Stop Loss: *{esc(sl)}* \\(\\-{esc(f'{risk_pct:.1f}')}%\\)",
        f"\u25b8 Risk/Reward: *1:{esc(f'{rr:.1f}')}*",
        f"\u25b8 Estimasi hold: *{days_min}\u2013{days_max} hari*",
        "",
    ]

    lines.append(_build_indicator_footer(snap, confluence, score))

    return "\n".join(line for line in lines if line is not None)


def format_exit_message(result: SignalResult, active_signal: dict) -> str:
    """Format an EXIT signal — dates, P&L, reasons."""
    ticker = result.ticker
    name = TICKER_NAMES.get(ticker, ticker)
    narrative = result.narrative or ""
    active_signal = active_signal or {}
    snap = result.indicator_snapshot or {}
    close = snap.get("close", 0)
    entry = active_signal.get("entry_price", 0)
    exit_reasons = result.exit_reasons or []
    _ = result.reason or "Technical reversal"
    entry_created = active_signal.get("created_at", "")

    esc = escape_markdown_v2

    if entry and close:
        pct = (close - entry) / entry * 100
        if pct >= 0:
            emoji = "🟡"
            pct_str = f"\\+{esc(f'{pct:.1f}')}%"
        else:
            emoji = "🔴"
            pct_str = f"{esc(f'{pct:.1f}')}%"
    else:
        emoji = "🔴"
        pct = 0
        pct_str = "N/A"

    exit_type_map = {
        SignalStatus.CLOSED_TP: "TARGET TERCAPAI \u2705",
        SignalStatus.CLOSED_SL: "STOP LOSS \u274c",
        SignalStatus.CLOSED_EXIT_SIGNAL: "SINYAL EXIT",
    }
    exit_label = exit_type_map.get(result.exit_status, "EXIT")

    days_held = ""
    if entry_created and result.created_at:
        try:
            created = datetime.fromisoformat(entry_created.replace("Z", "+00:00"))
            exited = datetime.fromisoformat(result.created_at.replace("Z", "+00:00"))
            held = max(0, (exited - created).days)
            days_held = f"  \u00b7  {held} hari"
        except (ValueError, TypeError):
            pass

    lines = [
        f"{emoji} *EXIT \u2014 {esc(exit_label)}*",
        f"*\\${esc(ticker)}* \u2014 {esc(name)}",
        "",
        f"📅 Entry: {esc(_format_wib_date(entry_created))}" if entry_created else None,
        f"📅 Exit: {esc(_format_wib_date(result.created_at))}" if result.created_at else None,
        f"\u23f1 Hold: {esc(days_held)}" if days_held else None,
        "",
        esc(narrative),
        "",
        "\u2500\u2500\u2500 *Detail Exit* \u2500\u2500\u2500",
        f"\u25b8 Entry: *{esc(format_rupiah(entry))}*" if entry else None,
        f"\u25b8 Exit: *{esc(format_rupiah(close))}*" if close else None,
        f"\u25b8 P&L: *{pct_str}*",
        "",
    ]

    if len(exit_reasons) > 1:
        lines.append(f"_📋 Alasan: {esc(', '.join(exit_reasons[:3]))}_")
    elif exit_reasons:
        lines.append(f"_📋 Alasan: {esc(exit_reasons[0])}_")

    return "\n".join(line for line in lines if line is not None)


def format_watch_message(result: SignalResult) -> str:
    """Format a WATCH signal — date, indicators, reason, expiry."""
    esc = escape_markdown_v2
    ticker = result.ticker
    name = TICKER_NAMES.get(ticker, ticker)
    snap = result.indicator_snapshot or {}
    score = result.score
    confluence = result.confluence_count
    reason = result.reason

    rsi = snap.get("rsi_14", 0)
    vol_ratio = snap.get("volume_ratio", 0)
    details = []
    if rsi:
        details.append(f"RSI {rsi:.0f}")
    if vol_ratio:
        details.append(f"Vol {vol_ratio:.1f}x")
    detail_str = f" \u00b7 {' \u00b7 '.join(details)}" if details else ""

    lines = [
        f"\U0001f441 *WATCHLIST \u2014 \\${esc(ticker)}*",
        esc(name),
        "",
        f"📅 {esc(_format_wib(result.created_at))}" if result.created_at else None,
        f"📊 Skor {score}/100 \u00b7 CF {confluence}/5{esc(detail_str)}",
        "",
        f"📋 Status: WATCH \u2014 {esc(_reason_label(reason))}",
        f"⏰ Auto\\-expire: {esc(_format_wib(result.expires_at))}" if result.expires_at else None,
        "",
        f"_{esc('Belum cukup kuat untuk entry \u2014 pantau perkembangan')}_",
    ]
    return "\n".join(line for line in lines if line is not None)


def format_expired_message(record: dict) -> str:
    """Format an expired signal — type, dates, explanation."""
    esc = escape_markdown_v2
    ticker = record.get("ticker", "?")
    signal_type = record.get("signal_type", "BUY")
    created_at_str = record.get("created_at", "")
    name = TICKER_NAMES.get(ticker, ticker)

    days = 0
    if created_at_str:
        try:
            created = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            days = (datetime.now(tz=timezone.utc) - created).days
        except (ValueError, TypeError):
            pass

    if signal_type == "WATCH":
        explanation = "Sinyal WATCH ini expired karena masa berlaku 24 jam telah habis."
        next_step = "Saham akan di-scan ulang di sesi berikutnya."
    else:
        explanation = "Sinyal BUY ini expired karena tidak ada kondisi EXIT yang terpenuhi dalam masa berlakunya."
        next_step = "Cek harga terkini secara manual untuk evaluasi lebih lanjut."

    lines = [
        f"⏰ *EXPIRED \u2014 {esc(signal_type)} \\${esc(ticker)}*",
        esc(name),
        "",
        f"📅 Aktif: {esc(_format_wib_date(created_at_str))} \u00b7 {days} hari" if created_at_str else None,
        f"📋 {esc(explanation)}",
        "",
        f"_{esc(next_step)}_",
    ]
    return "\n".join(line for line in lines if line is not None)


def format_daily_summary(
    date_str: str,
    duration: float,
    total: int,
    success: int,
    failed: int,
    signal_lines: list[str],
    mode: str = "",
) -> str:
    """Format daily scan summary with results list."""
    esc = escape_markdown_v2
    signals = "\n".join(esc(s) for s in signal_lines) if signal_lines else "Tidak ada sinyal"
    mode_tag = f" {esc(mode.upper())}" if mode else ""

    status_line = f"\u2705 {success}/{total} ticker \u00b7 {esc(f'{duration:.1f}')} detik"
    if failed:
        status_line += f" \u00b7 \u26a0\ufe0f {failed} gagal"
    lines = [
        f"📊 *Daily Scan{esc(mode_tag)} \u2014 {esc(date_str)}*",
        "",
        status_line,
        "",
        signals,
    ]
    return "\n".join(line for line in lines if line is not None)


def format_failure_message(date_str: str, reason_code: str, detail: str = "") -> str:
    """Format a public failure message."""
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
        f"📊 *Daily Scan \u2014 {esc(date_str)}*",
        "",
        esc(label),
    ]
    if detail:
        lines.append(esc(detail))
    return "\n".join(lines)


def format_no_signal_message(date_str: str, mode: str = "") -> str:
    """Format no-signal message with date context."""
    esc = escape_markdown_v2
    mode_tag = f" {esc(mode.upper())}" if mode else ""
    return (
        f"📊 *Daily Scan{esc(mode_tag)} \u2014 {esc(date_str)}*\n\n"
        f"Tidak ada sinyal yang memenuhi kriteria hari ini\\.\n"
        f"Semua ticker di bawah ambang batas atau belum menunjukkan setup yang cukup kuat\\.\n\n"
        f"_{esc('Kadang tidak ada sinyal itu juga sinyal.')}_"
    )


def format_active_positions_message(
    date_str: str,
    positions: list[str],
    mode: str = "",
) -> str:
    """Format message showing active positions when no new signals."""
    esc = escape_markdown_v2
    mode_tag = f" {esc(mode.upper())}" if mode else ""
    positions_text = "\n".join(positions)
    return (
        f"📊 *Daily Scan{esc(mode_tag)} \u2014 {esc(date_str)}*\n\n"
        f"Tidak ada sinyal baru hari ini\\.\n\n"
        f"*📋 Posisi Aktif*\n{positions_text}\n\n"
        f"_{esc('Exit otomatis akan dikirim jika TP\\/SL tercapai atau sinyal exit terdeteksi.')}_"
    )


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
    """Format weekly performance summary."""
    esc = escape_markdown_v2

    lines = [
        f"📈 *Weekly Report \u2014 {esc(date_str)}*",
        "",
        "*Kinerja*",
        f"\u25b8 Win Rate: *{esc(f'{win_rate_pct:.1f}')}%* \\({wins}W / {losses}L\\)",
        f"\u25b8 Avg Return: *{esc(f'{avg_return_pct:+.2f}')}%* per trade",
        f"\u25b8 Total Closed: *{total_closed}* sinyal",
        "",
    ]

    if top_performers:
        lines.append("*Top Performers*")
        for idx, p in enumerate(top_performers[:5], 1):
            t = p["ticker"]
            ret = p["avg_return_pct"]
            icon = "✅" if ret >= 0 else "❌"
            lines.append(f"{idx}\\. {esc(t)} \u00b7 {esc(f'{ret:+.1f}')}% {icon}")
        lines.append("")

    lines.append(f"📡 Sinyal Aktif: *{active_count}* ticker")

    return "\n".join(lines)
