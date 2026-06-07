"""Narrative text blocks — all template variants for dynamic signal messages.

Per PRD §8.2: minimum 3 variants per condition, Bahasa Indonesia informal tapi profesional.
Blocks are separated from logic for maintainability.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# BUY Signal blocks
# ---------------------------------------------------------------------------

# 1. Opening hooks — based on setup quality
OPENING_STRONG: list[str] = [
    "{ticker} menunjukkan setup yang sangat menarik hari ini. Hampir semua indikator utama menunjuk ke arah yang sama — confluence kuat yang tidak sering terlihat.",
    "Setup teknikal {ticker} sedang di zona premium. Ketika trend, momentum, dan volume semua selaras seperti ini, biasanya peluangnya cukup meyakinkan.",
    "Kalau kamu cari setup yang solid, {ticker} hari ini layak diperhatikan serius. Semua lampu teknikal nyala hijau.",
]

OPENING_NORMAL: list[str] = [
    "{ticker} mulai menunjukkan tanda-tanda menarik dari sisi teknikal. Setup belum sempurna, tapi fondasi arahnya sudah mulai terbentuk.",
    "Ada potensi yang mulai muncul di {ticker}. Beberapa indikator mulai berbicara, dan arahnya cukup konsisten.",
    "{ticker} membentuk pola yang cukup konstruktif. Bukan setup terbaik sepanjang tahun, tapi cukup solid untuk dicermati.",
]

OPENING_BORDERLINE: list[str] = [
    "{ticker} masuk radar hari ini, meskipun setup-nya belum sepenuhnya ideal. Ada beberapa indikator yang mendukung, tapi perlu selektif.",
    "Setup {ticker} cukup menarik tapi belum sempurna — masih ada satu-dua faktor yang belum sepenuhnya mendukung.",
    "{ticker} menunjukkan potensi, tapi dengan catatan: setup ini borderline. Hanya untuk yang siap dengan manajemen risiko ketat.",
]

# 2. Trend blocks — EMA condition
TREND_UPTREND: list[str] = [
    "Dari sisi tren, EMA9 sudah berada di atas EMA21 — ini konfirmasi uptrend yang cukup reliable.",
    "Trend-nya sudah bullish: EMA9 di atas EMA21, artinya pembeli masih dominan di timeframe pendek.",
    "EMA9 vs EMA21 menunjukkan tren naik yang terkonfirmasi. Secara teknikal, ini landasan yang solid untuk entry.",
]

TREND_CROSSING: list[str] = [
    "Yang menarik, EMA9 baru saja mendekati crossing point dengan EMA21 — ini bisa jadi awal perubahan tren yang signifikan.",
    "EMA9 dan EMA21 hampir berpotongan. Golden cross potensial ini sering jadi turning point buat pergerakan harga.",
    "Perhatikan EMA9 yang mulai mengejar EMA21. Crossing masih belum terjadi, tapi gap-nya sudah sangat tipis.",
]

TREND_NARROWING: list[str] = [
    "Tren memang masih downtrend secara teknis (EMA9 di bawah EMA21), tapi yang menarik: gap-nya mulai menyempit.",
    "EMA9 masih di bawah EMA21, tapi jarak keduanya mulai mengecil — sinyal awal bahwa seller mulai kehilangan dominasi.",
    "Secara tren belum bullish, tapi ada progress: gap EMA semakin kecil dari hari sebelumnya.",
]

TREND_DOWNTREND: list[str] = [
    "Tren masih bearish — EMA9 masih di bawah EMA21 dan belum ada tanda reversal yang kuat.",
    "Dari sisi tren, EMA masih menunjukkan dominasi seller. Ini yang membatasi skor keseluruhan.",
    "Tren harga masih ke bawah berdasarkan EMA. Ini jadi faktor pengurang dalam analisis.",
]

# 3. Momentum blocks — RSI condition
RSI_OVERSOLD: list[str] = [
    "RSI di {rsi:.0f} — sudah masuk zona oversold yang cukup dalam, artinya tekanan jual mulai habis.",
    "Dengan RSI di {rsi:.0f}, saham ini sudah cukup 'dihajar' oleh seller. Biasanya dari zona ini harga mulai cari keseimbangan baru.",
    "RSI menyentuh {rsi:.0f} — belum banyak yang mau masuk karena masih terlihat 'jatuh', tapi justru di sini setup-nya mulai terbentuk.",
]

RSI_NEUTRAL_BULLISH: list[str] = [
    "RSI di {rsi:.0f}, belum overbought sama sekali — masih ada ruang yang lumayan buat gerak ke atas.",
    "Dari sisi momentum, RSI {rsi:.0f} menunjukkan kondisi yang sehat: tidak terlalu panas, tidak terlalu dingin.",
    "RSI masih nyaman di {rsi:.0f}, jadi secara momentum belum ada tanda-tanda kelelahan.",
]

RSI_MODERATE: list[str] = [
    "RSI di {rsi:.0f} — momentum masih kuat meskipun sudah mulai mendekati area yang perlu diwaspadai.",
    "Dengan RSI di {rsi:.0f}, momentum saat ini cukup kencang. Masih ada ruang naik, tapi perlu dipantau.",
    "RSI {rsi:.0f} menunjukkan buyer masih punya tenaga. Belum overbought, tapi sudah di zona yang lebih aktif.",
]

RSI_EXTREMELY_OVERSOLD: list[str] = [
    "RSI di {rsi:.0f} — sangat oversold. Ini territory yang berisiko tinggi, tapi potensi bounce juga besar.",
    "Dengan RSI serendah {rsi:.0f}, ini sudah extreme oversold. High risk, tapi kadang justru di sinilah opportunity tersembunyi.",
    "RSI {rsi:.0f} sudah di zona extreme. Perlu extra hati-hati, tapi secara statistik bounce dari sini lumayan probable.",
]

# 4. Volume blocks
VOLUME_HIGH: list[str] = [
    "Volume hari ini {ratio:.1f}x dari rata-rata 5 hari — ada partisipasi yang jelas di balik pergerakan ini.",
    "Yang penting: volume konfirmasi ada. Hari ini {ratio:.1f}x di atas rata-rata, artinya gerakan ini bukan sekadar noise.",
    "Volume melonjak ke {ratio:.1f}x rata-rata. Kalau ada satu hal yang bikin teknikal lebih terpercaya, itu volume yang mendukung.",
]

VOLUME_NORMAL: list[str] = [
    "Volume hari ini masih di kisaran normal ({ratio:.1f}x rata-rata). Tidak terlalu ramai, tapi setidaknya ada aktivitas.",
    "Dari sisi volume, belum ada lonjakan signifikan ({ratio:.1f}x rata-rata). Konfirmasi volume masih ditunggu.",
    "Volume di level rata-rata ({ratio:.1f}x). Bukan yang paling ideal, tapi cukup untuk validasi minimal.",
]

VOLUME_LOW: list[str] = [
    "Satu kelemahan: volume masih sepi ({ratio:.1f}x rata-rata). Tanpa volume yang mendukung, breakout bisa saja gagal.",
    "Volume masih di bawah rata-rata ({ratio:.1f}x). Ini jadi catatan — pergerakan tanpa volume sering kali tidak sustain.",
    "Kurangnya volume ({ratio:.1f}x rata-rata) jadi faktor yang membatasi conviction di setup ini.",
]

# 5. Setup blocks — Bollinger Band position
SETUP_BOUNCE_BBL: list[str] = [
    "Harga baru saja menyentuh lower Bollinger Band — secara historis, ini sering jadi area bounce terutama kalau didukung indikator lain.",
    "Price action menunjukkan harga di sekitar lower Bollinger Band. Ini area value buy buat swing trader.",
    "Posisi harga di dekat lower band memberi cushion natural. Setup ini biasanya punya risk/reward yang favorable.",
]

SETUP_LOWER_HALF: list[str] = [
    "Harga masih di separuh bawah Bollinger Band, yang berarti masih ada potensi untuk bergerak ke mean.",
    "Posisi harga di antara lower band dan middle band — secara statistik, ini zona dengan upside potential.",
    "Harga belum kembali ke middle band, sehingga masih ada ruang untuk mean reversion ke atas.",
]

SETUP_UPPER_HALF: list[str] = [
    "Harga sudah di separuh atas Bollinger Band. Setup masih valid, tapi upside-nya lebih terbatas.",
    "Posisi di upper half Bollinger Band. Bukan yang paling ideal untuk entry, tapi trend bisa saja meneruskan.",
    "Harga di area upper half BB — masih bisa lanjut naik, tapi awareness terhadap resistance perlu ditingkatkan.",
]

# 6. Caveat blocks (wajib untuk borderline signals)
CAVEAT_BLOCKS: list[str] = [
    "⚠️ _Setup ini borderline — pastikan position sizing konservatif dan stop loss disiplin._",
    "⚠️ _Ini bukan setup grade A. Hanya masuk kalau kamu nyaman dengan risikonya._",
    "⚠️ _Skor di ambang batas — pertimbangkan untuk tunggu konfirmasi tambahan sebelum entry._",
]


# ---------------------------------------------------------------------------
# EXIT Signal blocks
# ---------------------------------------------------------------------------

EXIT_HOOK_TP: list[str] = [
    "Target tercapai! {ticker} sudah sampai di area take profit yang ditentukan.",
    "Saatnya harvest — {ticker} berhasil mencapai target harga yang ditetapkan saat entry.",
    "Good news: {ticker} hit target. Disiplin di take profit sama pentingnya dengan entry yang bagus.",
]

EXIT_HOOK_SL: list[str] = [
    "Stop loss triggered untuk {ticker}. Keputusan yang tepat — preserving capital lebih penting dari ego.",
    "{ticker} menyentuh stop loss. Ini bukan kegagalan — ini manajemen risiko yang bekerja sesuai rencana.",
    "Cut loss di {ticker}. Kadang pasar memang tidak bergerak sesuai ekspektasi, dan itu normal.",
]

EXIT_HOOK_REVERSAL: list[str] = [
    "Kondisi teknikal {ticker} sudah berubah. Beberapa indikator mulai menunjukkan tanda-tanda reversal.",
    "{ticker} menunjukkan sinyal pelemahan. Setup yang tadinya konstruktif mulai kehilangan momentum.",
    "Waktunya evaluasi {ticker} — indikator teknikal mulai mengirim sinyal bahwa trend mungkin berubah arah.",
]

EXIT_REASON_RSI_OVERBOUGHT: list[str] = [
    "RSI sudah di {rsi:.0f} — zona overbought. Biasanya dari sini ada koreksi atau minimal konsolidasi.",
    "Dengan RSI di {rsi:.0f}, buyer sudah cukup 'panas'. Potensi profit-taking dari level ini cukup tinggi.",
    "RSI {rsi:.0f} sudah overbought. Ini bukan jaminan turun, tapi secara probabilitas, risk jadi lebih tinggi.",
]

EXIT_REASON_MACD_CROSS: list[str] = [
    "MACD baru saja cross ke bawah signal line — ini sinyal teknikal klasik bahwa momentum mulai berbalik.",
    "Bearish crossover di MACD. Seller mulai ambil alih kendali momentum dari buyer.",
    "MACD crossover ke negatif hari ini. Secara historis, ini sering mendahului koreksi harga.",
]

EXIT_REASON_BBU_BREAKOUT: list[str] = [
    "Harga sudah di atas upper Bollinger Band — secara statistik, ini area overbought yang sering diikuti pullback.",
    "Price action menembus upper BB. Meskipun bisa saja lanjut, ini sinyal untuk waspada terhadap koreksi.",
    "Harga di atas upper Bollinger Band menunjukkan stretch yang mungkin tidak sustainable.",
]

EXIT_REASON_SCORE_DROP: list[str] = [
    "Overall setup score turun drastis — fondasi teknikal yang mendukung entry sudah melemah.",
    "Skor teknikal sudah di bawah ambang batas. Setup yang tadinya menarik sekarang sudah kehilangan daya tarik.",
    "Mayoritas indikator yang tadinya mendukung sekarang sudah berbalik atau netral.",
]

GAIN_LINE_PROFIT: list[str] = [
    "📈 Estimasi profit: *+{pct:.1f}%* dari entry",
    "📈 Dari harga entry, posisi ini masih hijau *+{pct:.1f}%*",
    "📈 Unrealized gain sekitar *+{pct:.1f}%*",
]

GAIN_LINE_LOSS: list[str] = [
    "📉 Estimasi kerugian: *{pct:.1f}%* dari entry",
    "📉 Posisi saat ini merah *{pct:.1f}%* dari entry",
    "📉 Unrealized loss sekitar *{pct:.1f}%*",
]

# ---------------------------------------------------------------------------
# Daily summary / System messages
# ---------------------------------------------------------------------------

NO_SIGNAL_MESSAGES: list[str] = [
    "📊 *Daily Scan*\n\nScan selesai \\— tidak ada sinyal yang memenuhi kriteria hari ini\\. Semua ticker di bawah ambang batas atau belum menunjukkan setup yang cukup kuat\\.\n\n_Kadang tidak ada sinyal itu juga sinyal\\._",
    "📊 *Daily Scan*\n\nHari ini tidak ada setup yang cukup meyakinkan dari 20 ticker yang dipantau\\. Patience is a virtue\\.\n\n_No signal today \\— we wait for better setups\\._",
    "📊 *Daily Scan*\n\nSemua ticker dicek, tapi belum ada yang memenuhi standar untuk sinyal hari ini\\. Better to miss a trade than force one\\.\n\n_Stand by mode\\._",
]

MARKET_CLOSED_WEEKEND: str = "📊 Pasar tutup hari ini \\(weekend\\)\\. Tidak ada scan\\."

MARKET_CLOSED_HOLIDAY: str = "📊 Pasar tutup hari ini berdasarkan kalender market resmi\\. Tidak ada scan\\."

EXPIRED_SIGNAL: list[str] = [
    "⏰ Sinyal {ticker} sudah aktif lebih dari {days} hari tanpa EXIT trigger. Sinyal otomatis di-expire. Cek harga terkini secara manual.",
    "⏰ {ticker} expired setelah {days} hari aktif. Tidak ada kondisi EXIT yang terpenuhi dalam periode tersebut. Posisi perlu di-review manual.",
    "⏰ Auto-expire untuk {ticker} — sudah {days} hari tanpa trigger. Posisi ini butuh evaluasi manual.",
]
