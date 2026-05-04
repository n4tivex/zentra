# ZENTRA — Product Requirements Document
**Version:** 1.0.0  
**Status:** Production  
**Target Exchange:** Bursa Efek Indonesia (IDX)  
**Strategy:** Swing Trading (T+2 settlement, hold 3–10 hari)  
**Author:** Internal  
**Last Updated:** 2026-05-04

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Goals & Non-Goals](#2-goals--non-goals)
3. [System Architecture](#3-system-architecture)
4. [Tech Stack & Rationale](#4-tech-stack--rationale)
5. [Data Layer](#5-data-layer)
6. [Analysis Engine](#6-analysis-engine)
7. [Signal Scoring System](#7-signal-scoring-system)
8. [Narrative Generator (NLG)](#8-narrative-generator-nlg)
9. [Telegram Delivery](#9-telegram-delivery)
10. [Database Schema (Supabase)](#10-database-schema-supabase)
11. [Scheduler & Orchestration](#11-scheduler--orchestration)
12. [Security Requirements](#12-security-requirements)
13. [Performance Requirements](#13-performance-requirements)
14. [Error Handling & Edge Cases](#14-error-handling--edge-cases)
15. [Code Quality Standards](#15-code-quality-standards)
16. [Testing Requirements](#16-testing-requirements)
17. [Deployment Guide](#17-deployment-guide)
18. [Monitoring & Observability](#18-monitoring--observability)
19. [Future Roadmap](#19-future-roadmap)
20. [Glossary](#20-glossary)

---

## 1. Project Overview

ZENTRA adalah automated equity signal engine yang dirancang untuk pasar saham Indonesia (IDX). ZENTRA menganalisis 20 ticker secara harian menggunakan multi-indicator technical analysis, menghasilkan sinyal BUY/EXIT yang dikirim ke Telegram dengan narasi yang informatif, kontekstual, dan tidak terasa seperti bot template.

ZENTRA bukan trading bot — ia tidak melakukan order eksekusi. ZENTRA adalah decision-support system: mengolah data, menghasilkan sinyal tervalidasi, dan menyampaikannya ke user dalam format yang actionable dan mudah dipahami.

**Nama Engine:** ZENTRA  
**Deployment:** GitHub Actions (zero-cost, serverless)  
**Database:** Supabase (PostgreSQL, free tier)  
**Notification:** Telegram Bot API  
**Data Source:** yfinance (Yahoo Finance, IDX suffix `.JK`)

### Ticker List (Fixed)

```
BBCA, BMRI, BBRI, NCKL, RMKE, BREN, CBDK, PTRO, BRPT,
BUMI, DEWA, BRMS, ENRG, AMMN, OASA, ADMR, RAJA, SIMP, GZCO, PGEO
```

Ticker list bersifat **fixed dan hardcoded di config**. Tidak ada dynamic ticker management di v1.0.

---

## 2. Goals & Non-Goals

### Goals

- Menghasilkan sinyal swing trading IDX yang akurat berdasarkan multi-indicator confluence, bukan single-indicator trigger
- Mengirimkan sinyal BUY dan EXIT ke Telegram dengan narasi dinamis yang menjelaskan reasoning di balik setiap sinyal
- Mencegah sinyal duplikat — satu ticker hanya bisa punya satu open signal dalam satu waktu
- Menyimpan seluruh riwayat sinyal dan performa ke Supabase untuk evaluasi berkelanjutan
- Berjalan sepenuhnya tanpa biaya (zero cost), tanpa credit card, tanpa server berbayar
- Tahan terhadap kegagalan data parsial — satu ticker gagal tidak boleh menghentikan analisis ticker lain

### Non-Goals

- Eksekusi order otomatis ke broker (ZENTRA tidak terintegrasi dengan API broker apapun)
- Scalp trading atau intraday signal
- Analisis fundamental (P/E ratio, laporan keuangan, dll.)
- Support untuk saham di luar daftar 20 ticker yang sudah ditentukan
- Machine learning atau AI-based signal generation (v1.0 menggunakan rule-based system)
- Web dashboard atau UI berbasis browser (v1.0 hanya Telegram)
- Multi-exchange support (hanya IDX)

---

## 3. System Architecture

### High-Level Flow

```
[GitHub Actions Cron]
        │
        ▼
[main.py entrypoint]
        │
        ├──► [Data Layer]
        │       ├── Fetch OHLCV dari yfinance (.JK suffix)
        │       ├── Validate data completeness
        │       ├── Check cache di Supabase (skip fetch jika data hari ini sudah ada)
        │       └── Persist raw OHLCV ke Supabase (ohlcv_cache)
        │
        ├──► [Analysis Engine]  (per ticker, isolated)
        │       ├── Trend indicators   : EMA(20), EMA(50), MACD(12,26,9)
        │       ├── Momentum indicators: RSI(14), Stochastic RSI(14,3,3)
        │       ├── Volatility         : Bollinger Bands(20,2), ATR(14)
        │       └── Volume             : OBV, Volume SMA(20), Volume ratio
        │
        ├──► [Signal Scoring Engine]
        │       ├── Weighted multi-indicator scoring (0–100)
        │       ├── Confluence check (minimum N indicators harus agree)
        │       ├── Dedup check via Supabase (ada open signal untuk ticker ini?)
        │       ├── Risk/reward calculation via ATR
        │       └── Classify: BUY | WATCH | NO_SIGNAL | EXIT
        │
        ├──► [Narrative Generator]
        │       ├── Assemble dynamic signal text dari kondisi aktual
        │       ├── Generate entry price, SL, TP dalam format Rupiah
        │       └── Format Telegram message (MarkdownV2)
        │
        ├──► [Telegram Sender]
        │       ├── Rate-limited delivery (1 detik antar pesan)
        │       ├── Retry logic (3x dengan exponential backoff)
        │       └── Error logging ke Supabase jika semua retry gagal
        │
        └──► [Supabase Persistence]
                ├── Upsert sinyal baru ke tabel signals
                ├── Update status sinyal lama jika EXIT terdeteksi
                └── Log run metadata ke tabel run_logs
```

### Isolation Principle

Setiap ticker diproses secara independen. Kegagalan pada satu ticker (data error, calculation error, dll.) harus di-catch di level per-ticker dan tidak boleh propagate ke ticker lain. Pattern yang digunakan:

```python
results = []
for ticker in TICKERS:
    try:
        result = process_ticker(ticker)
        results.append(result)
    except TickerProcessingError as e:
        log_ticker_error(ticker, e)
        continue
```

---

## 4. Tech Stack & Rationale

| Komponen | Tool | Versi | Alasan |
|---|---|---|---|
| Bahasa | Python | 3.11+ | Ekosistem data terlengkap, async support via asyncio |
| Data market | yfinance | >=0.2.40 | IDX support via `.JK` suffix, zero cost, no API key |
| Technical analysis | pandas-ta | >=0.3.14b | 130+ indikator, no TA-Lib compile dependency, pure Python |
| DataFrame | pandas | >=2.0 | Standard, mature, performa cukup untuk 20 ticker |
| Database client | supabase-py | >=2.0 | Official Python client, async support |
| Telegram | python-telegram-bot | >=20.0 | Async, maintained, retry built-in |
| Retry logic | tenacity | >=8.0 | Decorator-based retry dengan exponential backoff |
| Scheduler | GitHub Actions | - | Zero cost, 2000 menit/bulan gratis, cron support |
| Secrets | GitHub Secrets + env vars | - | Tidak ada secret di codebase |
| Logging | structlog | >=24.0 | Structured JSON logs untuk observability |
| Testing | pytest + pytest-asyncio | - | Standard, mock-friendly |
| Linting | ruff + black | - | Fast, opinionated, zero config |
| Type checking | mypy | - | Strict mode untuk production code |


## 5. Data Layer

### 5.1 Fetcher (`zentra/data/fetcher.py`)

**Tanggung jawab:** Mengambil data OHLCV dari yfinance untuk semua 20 ticker.

**Spesifikasi:**

- Fetch data untuk **60 hari kalender terakhir** (bukan trading days). Ini memberikan sekitar 40 trading days, cukup untuk semua indikator yang dibutuhkan.
- Gunakan `yf.download()` dengan parameter `group_by='ticker'` untuk batch download semua ticker sekaligus dalam satu HTTP request, bukan 20 request terpisah.
- Suffix `.JK` harus di-append otomatis di fetcher, bukan di config. Config menyimpan ticker tanpa suffix (BBCA, bukan BBCA.JK).
- Setiap kolom OHLCV harus divalidasi tipe data setelah fetch: Open/High/Low/Close harus float64, Volume harus int64.
- Timestamp index harus di-normalize ke timezone-naive UTC date (bukan datetime dengan timezone).

**Interface:**

```python
class MarketDataFetcher:
    def fetch_all(self, tickers: list[str], days: int = 60) -> dict[str, pd.DataFrame]:
        """
        Returns dict of ticker -> OHLCV DataFrame.
        DataFrame columns: open, high, low, close, volume (lowercase).
        DataFrame index: DatetimeIndex, timezone-naive, UTC.
        Raises: DataFetchError jika semua ticker gagal.
        Partial failures (beberapa ticker gagal) tidak raise exception —
        hanya return dict dengan ticker yang berhasil.
        """

    def fetch_single(self, ticker: str, days: int = 60) -> pd.DataFrame:
        """
        Fetch satu ticker. Raise TickerNotFoundError jika ticker tidak valid.
        Raise DataFetchError untuk network/parsing errors.
        """
```

**Cache logic:**

Sebelum fetch dari yfinance, cek Supabase apakah data untuk hari ini (tanggal run) sudah ada di `ohlcv_cache`. Jika ada dan lengkap (ada 60 baris), gunakan data dari cache. Ini menghindari redundant network call jika workflow di-trigger dua kali dalam satu hari.

**Retry logic:**

```python
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((ConnectionError, TimeoutError)),
    reraise=True
)
def _fetch_from_yahoo(self, tickers_jk: list[str], period: str) -> pd.DataFrame:
    ...
```

### 5.2 Validator (`zentra/data/validator.py`)

**Tanggung jawab:** Memastikan data yang masuk ke analysis engine adalah data yang valid dan dapat dipercaya.

**Validasi yang harus dilakukan:**

| Check | Aksi jika gagal |
|---|---|
| DataFrame tidak kosong | Raise `InsufficientDataError` |
| Minimum 30 baris data (30 trading days) | Raise `InsufficientDataError` |
| Tidak ada NaN di kolom close, volume | Drop baris NaN, cek ulang jumlah baris |
| Tanggal data terbaru adalah T atau T-1 | Log warning "data mungkin stale", tetap proses |
| Tanggal data terbaru lebih dari 5 hari lalu | Raise `StaleDataError` |
| Close price > 0 (tidak negatif atau zero) | Raise `DataIntegrityError` |
| Volume >= 0 | Set volume negatif ke 0, log warning |
| Tidak ada gap lebih dari 7 hari kalender di antara baris | Log warning (gap bisa karena libur panjang) |
| High >= Low untuk setiap baris | Raise `DataIntegrityError` |
| High >= Close dan High >= Open | Raise `DataIntegrityError` |
| Low <= Close dan Low <= Open | Raise `DataIntegrityError` |

**Holiday detection:**

IDX punya kalender libur nasional yang tidak selalu hari Sabtu/Minggu. Validator tidak perlu tahu daftar libur — cukup gunakan logic: jika gap antara dua baris adalah <= 4 hari kalender, itu dianggap normal (weekend + 1-2 hari libur nasional). Jika gap > 4 hari kalender tanpa penjelasan, log warning tapi tetap proses.

**Interface:**

```python
class DataValidator:
    def validate(self, ticker: str, df: pd.DataFrame) -> ValidationResult:
        """
        Returns ValidationResult(is_valid: bool, warnings: list[str], errors: list[str]).
        Tidak raise exception — caller yang memutuskan apakah lanjut atau skip.
        """
```

### 5.3 Market Status Check

Sebelum run analysis, engine harus cek apakah hari ini adalah hari trading IDX. Logic:

1. Cek apakah hari ini adalah hari kerja (Senin-Jumat). Jika Sabtu/Minggu, kirim Telegram message: `"ZENTRA: Pasar tutup hari ini (weekend). Tidak ada scan."` lalu exit gracefully.
2. Fetch sample data untuk satu ticker (BBCA.JK) dengan period 1 hari. Jika data terakhir bukan hari ini atau kemarin, kemungkinan besar hari ini libur nasional. Log info dan kirim notifikasi ke Telegram.
3. Untuk mode `morning` (pre-market), gunakan data closing kemarin. Untuk mode `closing` (post-market), gunakan data closing hari ini.

---

## 6. Analysis Engine

### 6.1 Indicators (`zentra/analysis/indicators.py`)

Semua indikator dihitung menggunakan `pandas-ta`. Tidak ada custom indicator calculation dari scratch — gunakan library yang sudah tested.

**Indikator yang dihitung:**

```python
class TechnicalIndicators:
    """
    Semua metode menerima DataFrame OHLCV standar dan
    mengembalikan DataFrame yang sama dengan kolom tambahan.
    """

    def compute_all(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Hitung semua indikator sekaligus dan return DataFrame
        dengan semua kolom indikator yang dibutuhkan.
        Tidak ada side effects — return DataFrame baru.
        """
        df = df.copy()  # PENTING: jangan mutate input

        # Trend
        df.ta.ema(length=20, append=True)       # kolom: EMA_20
        df.ta.ema(length=50, append=True)       # kolom: EMA_50
        df.ta.macd(fast=12, slow=26, signal=9, append=True)
        # kolom: MACD_12_26_9, MACDh_12_26_9 (histogram), MACDs_12_26_9 (signal)

        # Momentum
        df.ta.rsi(length=14, append=True)       # kolom: RSI_14
        df.ta.stochrsi(length=14, rsi_length=14, k=3, d=3, append=True)
        # kolom: STOCHRSIk_14_14_3_3, STOCHRSId_14_14_3_3

        # Volatility
        df.ta.bbands(length=20, std=2, append=True)
        # kolom: BBL_20_2.0, BBM_20_2.0, BBU_20_2.0, BBB_20_2.0, BBP_20_2.0
        df.ta.atr(length=14, append=True)       # kolom: ATRr_14

        # Volume
        df.ta.obv(append=True)                  # kolom: OBV
        # Volume SMA manual karena pandas-ta tidak punya volume SMA langsung
        df['VOL_SMA_20'] = df['volume'].rolling(window=20).mean()

        return df
```

**Catatan penting:**
- `pandas-ta` bisa mengembalikan NaN untuk baris-baris pertama karena window belum penuh. Ini normal. Scorer harus mengambil nilai dari baris **terbaru** (`df.iloc[-1]`) yang seharusnya sudah memiliki nilai valid jika data >= 30 baris.
- Jika kolom kritis (RSI, MACD, EMA) masih NaN di baris terakhir meskipun data sudah >= 30 baris, ini adalah `CalculationError` dan ticker harus di-skip.

### 6.2 Risk Calculator (`zentra/analysis/risk.py`)

**Tanggung jawab:** Menghitung entry, stop loss, dan target price berdasarkan ATR.

```python
class RiskCalculator:
    SL_MULTIPLIER = 1.5   # Stop loss = entry - (1.5 x ATR)
    TP_MULTIPLIER = 2.5   # Take profit = entry + (2.5 x ATR)
    MIN_RR_RATIO = 1.5    # Risk/reward minimum. Di bawah ini, sinyal tidak dikirim.
    MAX_SL_PCT = 0.08     # Stop loss tidak boleh lebih dari 8% dari entry

    def calculate(
        self,
        entry_price: float,
        atr: float,
        direction: str = "BUY"
    ) -> RiskLevels:
        """
        Returns RiskLevels(
            entry: float,
            stop_loss: float,
            take_profit: float,
            risk_reward_ratio: float,
            risk_pct: float,
            reward_pct: float
        )
        """
```

**Aturan:**
- Entry price = closing price hari terakhir yang tersedia.
- ATR diambil dari baris terakhir `ATRr_14`.
- Stop loss tidak boleh lebih dari **8%** di bawah entry (hardcoded cap). Jika ATR terlalu besar dan SL > 8%, kurangi SL multiplier sampai maksimal 8%, bukan reject sinyal.
- Risk/reward ratio harus >= `MIN_RR_RATIO`. Jika tidak, sinyal tidak eligible untuk dikirim.
- Harga entry, SL, dan TP di-round ke integer terdekat (satuan Rupiah).

---

## 7. Signal Scoring System

### 7.1 Scorer (`zentra/analysis/scorer.py`)

**Prinsip dasar:** ZENTRA tidak mengirim sinyal hanya karena satu indikator menyarankan beli. Sinyal harus berupa **confluence** — beberapa indikator yang independent saling mengkonfirmasi arah yang sama. Semakin banyak indikator yang agree, semakin tinggi skor.

**Scoring matrix:**

| Indikator | Bobot Max | Kondisi Bullish (BUY) | Nilai |
|---|---|---|---|
| EMA Trend | 25 | EMA20 > EMA50 (uptrend confirmed) | 25 |
| | | EMA20 mendekati EMA50 (dalam 2%) dan crossing | 15 |
| | | EMA20 < EMA50 tapi gap menyempit hari ini | 5 |
| MACD | 20 | MACD line cross di atas signal line (crossover hari ini atau kemarin) | 20 |
| | | MACD histogram positif dan meningkat (tapi belum crossover) | 12 |
| | | MACD histogram negatif tapi mendekati 0 (divergence berkurang) | 5 |
| RSI | 20 | RSI antara 35–55 (tidak overbought, ada ruang naik) | 20 |
| | | RSI antara 55–65 (momentum kuat, masih okay) | 12 |
| | | RSI antara 25–35 (oversold, potential reversal) | 8 |
| | | RSI di atas 70 (overbought) | 0 |
| | | RSI di bawah 25 (extremely oversold, risky) | 3 |
| Bollinger Band | 15 | Close di bawah BBL atau bounce dari BBL | 15 |
| | | Close antara BBL dan BBM (lower half) | 10 |
| | | Close antara BBM dan BBU (upper half) | 5 |
| | | Close di atas BBU (breakout atau overbought) | 2 |
| Volume | 15 | Volume hari ini > 1.5x rata-rata 20 hari | 15 |
| | | Volume hari ini antara 1.0x–1.5x rata-rata | 8 |
| | | Volume hari ini < 1.0x rata-rata (sepi) | 0 |
| ATR | 5 | ATR cukup untuk risk/reward >= 1.5 | 5 |
| | | ATR terlalu kecil (risk/reward < 1.5) | 0 |

**Total maksimum: 100 poin**

### 7.2 Signal Classification

```
Skor >= 70 AND confluence_count >= 3  -->  BUY signal (kirim ke Telegram)
Skor 55–69 AND confluence_count >= 2  -->  WATCH (simpan ke DB, tidak dikirim ke Telegram)
Skor < 55 atau confluence_count < 2   -->  NO_SIGNAL (skip)
```

**`confluence_count`** adalah jumlah dari 5 indikator utama (EMA, MACD, RSI, Bollinger, Volume) yang memberikan nilai positif (> 0 untuk kondisi bullish). Minimum 3 dari 5 harus bullish untuk BUY signal.

### 7.3 EXIT Signal Detection

EXIT signal digenerate ketika **salah satu** kondisi berikut terpenuhi untuk ticker yang memiliki open BUY signal:

| Kondisi | Trigger |
|---|---|
| RSI >= 70 | Overbought — potensi reversal |
| Close >= Take Profit price | Target tercapai — lock profit |
| Close <= Stop Loss price | Stop loss hit — cut loss |
| MACD crossover ke negatif (hari ini) | Trend balik arah |
| Close di atas BBU (upper band) | Overbought territory |
| Skor BUY turun di bawah 40 | Setup memburuk |

EXIT signal tidak memerlukan skor minimum. Jika **2 atau lebih** kondisi EXIT terpenuhi, ini adalah **STRONG EXIT**. Jika hanya 1, ini adalah **EXIT**.

### 7.4 Deduplication Logic

Sebelum mengirim sinyal BUY, cek ke Supabase:

```python
existing = supabase.table("signals").select("id").eq("ticker", ticker).eq("status", "ACTIVE").execute()
if existing.data:
    # Sudah ada open signal untuk ticker ini, skip BUY baru
    return SignalResult(type=SignalType.NO_SIGNAL, reason="duplicate_active_signal")
```

Satu ticker hanya boleh punya **satu ACTIVE signal** dalam satu waktu.

### 7.5 Signal Expiry

Sinyal ACTIVE yang sudah lebih dari **10 hari kalender** tanpa EXIT signal otomatis akan di-mark sebagai `EXPIRED` oleh orchestrator. Admin di-notify via Telegram bahwa sinyal expired dan harga perlu dicek manual.

---

## 8. Narrative Generator (NLG)

### 8.1 Prinsip NLG (`zentra/narrative/generator.py`)

Tujuan NLG adalah menghasilkan teks sinyal yang:
- Terasa ditulis oleh manusia, bukan bot template
- Menjelaskan reasoning di balik sinyal, bukan hanya angka
- Dinamis — kalimat yang dipilih bergantung pada kondisi aktual indikator
- Menggunakan bahasa Indonesia informal tapi profesional

**DILARANG:**
- Template statis dengan placeholder sederhana (seperti `"RSI saat ini adalah {rsi}"`)
- Kalimat yang sama persis untuk setiap sinyal
- Bullet point panjang tanpa narasi
- Bahasa terlalu formal atau terlalu seperti press release

**HARUS:**
- Kalimat pembuka yang bervariasi dan kontekstual
- Penjelasan mengapa setup ini menarik, bukan hanya apa yang terjadi
- Angka-angka teknikal disebutkan tapi dalam konteks, bukan sebagai dump data
- Estimasi hold time berdasarkan ATR dan target distance

### 8.2 Narrative Building Blocks (`zentra/narrative/blocks.py`)

NLG bekerja dengan cara memilih dan merangkai **blok kalimat** berdasarkan kondisi aktual. Setiap kondisi punya **minimum 3 varian** untuk menghindari repetisi.

Gunakan `random.choice()` dengan seed deterministik berbasis `(tanggal_run + ticker)` sehingga jika workflow di-retry pada hari yang sama, narasi yang dihasilkan identik.

**Blok-blok yang wajib ada:**

1. **Opening hook** — kalimat pertama merangkum situasi keseluruhan. Pilihan berdasarkan overall setup quality (strong/moderate/borderline).
2. **Trend block** — kondisi EMA dan arah tren saat ini.
3. **Momentum block** — kondisi RSI dan MACD, dengan nilai aktual disebutkan secara natural.
4. **Volume block** — konfirmasi atau ketiadaan konfirmasi volume.
5. **Setup block** — kenapa entry point ini menarik secara teknikal.
6. **Caveat block** — satu kalimat disclaimer ringan tentang risiko. Wajib untuk sinyal borderline (skor 70–74).

**Contoh varian blok RSI:**

```python
RSI_OVERSOLD_BLOCKS = [
    "RSI di {rsi:.0f} — sudah masuk zona oversold yang cukup dalam, artinya tekanan jual mulai habis.",
    "Dengan RSI di {rsi:.0f}, saham ini sudah cukup 'dihajar' oleh seller. Biasanya dari zona ini harga mulai cari keseimbangan baru.",
    "RSI menyentuh {rsi:.0f} — belum banyak yang mau masuk karena masih terlihat 'jatuh', tapi justru di sini setup-nya mulai terbentuk.",
]

RSI_NEUTRAL_BULLISH_BLOCKS = [
    "RSI di {rsi:.0f}, belum overbought sama sekali — masih ada ruang yang lumayan buat gerak ke atas.",
    "Dari sisi momentum, RSI {rsi:.0f} menunjukkan kondisi yang sehat: tidak terlalu panas, tidak terlalu dingin.",
    "RSI masih nyaman di {rsi:.0f}, jadi secara momentum belum ada tanda-tanda kelelahan.",
]
```

**Blok-blok yang wajib ada untuk EXIT:**

1. **Exit hook** — kenapa ini saat yang tepat untuk keluar.
2. **Primary reason** — kondisi utama yang men-trigger EXIT, ditulis dengan konteks.
3. **Secondary conditions** — jika ada kondisi tambahan yang mendukung exit.
4. **Gain/loss estimate** — estimasi hasil jika keluar sekarang vs. harga entry di database.

### 8.3 Output Format (Telegram MarkdownV2)

**BUY Signal:**

```
🟢 *ZENTRA — BUY SIGNAL*
*$TICKER* · Nama Emiten

{narrative_paragraph_1}

{narrative_paragraph_2_optional}

📌 Entry sekitar *Rp {entry_price:,}*
🎯 Target *Rp {take_profit:,}* \(+{reward_pct:.1f}%\)
🛑 Stop loss *Rp {stop_loss:,}* \(-{risk_pct:.1f}%\)
⏱ Estimasi hold *{hold_days_min}–{hold_days_max} hari*

_Skor: {score}/100 · Risk/reward: 1:{rr_ratio:.1f}_
```

**EXIT Signal:**

```
🔴 *ZENTRA — EXIT SIGNAL*
*$TICKER*

{exit_narrative}

📌 Exit di sekitar *Rp {current_price:,}*
{gain_loss_line}

_Alasan utama: {primary_exit_reason}_
```

**WATCH Alert (hanya ke admin/private chat, tidak ke channel utama):**

```
👁 *ZENTRA — WATCHLIST UPDATE*
*$TICKER* masuk pantauan

{brief_reason}

_Skor: {score}/100 — belum cukup kuat untuk entry_
```

**Aturan formatting:**
- Semua angka Rupiah menggunakan format `Rp 1.250` (titik sebagai separator ribuan, bukan koma). Gunakan locale Indonesia atau format manual.
- Semua karakter spesial MarkdownV2 (`_`, `*`, `[`, `]`, `(`, `)`, `~`, `` ` ``, `>`, `#`, `+`, `-`, `=`, `|`, `{`, `}`, `.`, `!`) harus di-escape dengan backslash sebelum dikirim.
- Buat helper function `escape_markdown_v2(text: str) -> str` di `zentra/telegram/formatter.py`.

### 8.4 Ticker Name Mapping

```python
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
```

---

## 9. Telegram Delivery

### 9.1 Sender (`zentra/telegram/sender.py`)

**Spesifikasi:**

- Gunakan `python-telegram-bot` v20+ dengan async interface
- Satu `Bot` instance per run, bukan per pesan
- Rate limiting: 1 detik delay antar pesan untuk menghindari Telegram 429 error
- Retry: 3 kali dengan exponential backoff (2s, 4s, 8s) untuk error 429 atau 5xx
- Jika semua 3 retry gagal, log error ke Supabase dan lanjut ke sinyal berikutnya — jangan crash

**Interface:**

```python
class TelegramSender:
    def __init__(self, bot_token: str, chat_id: str):
        ...

    async def send_signal(self, message: str) -> bool:
        """
        Kirim satu sinyal. Returns True jika berhasil, False jika gagal setelah retry.
        Tidak raise exception ke caller.
        """

    async def send_batch(self, messages: list[str]) -> list[bool]:
        """
        Kirim batch messages dengan rate limiting.
        Returns list of success/failure per message.
        """

    async def send_admin_alert(self, message: str) -> None:
        """
        Kirim alert ke admin (bisa chat_id berbeda atau sama).
        Untuk: run errors, stale data warnings, system issues.
        """
```

**Penting:** `chat_id` bisa berupa channel ID (format: `-100xxxxxxxxxx`) atau user ID. Nilai ini harus dari environment variable, bukan hardcoded.

### 9.2 Message Ordering

Urutan pesan yang dikirim dalam satu run:

1. STRONG EXIT signal (tertinggi prioritas)
2. Normal EXIT signal
3. BUY signal (diurutkan berdasarkan skor, tertinggi dahulu)
4. Daily summary (jika ada >= 3 sinyal hari itu)
5. "Tidak ada sinyal hari ini" jika tidak ada BUY atau EXIT yang ditemukan

### 9.3 Daily Summary (kirim jika >= 3 sinyal)

```
📊 *ZENTRA Daily Scan — {tanggal}*

Scan selesai dalam {duration:.1f} detik
{jumlah} ticker dianalisis · {berhasil} berhasil · {gagal} gagal

Sinyal hari ini:
{daftar_sinyal}

_ZENTRA v1.0 · IDX Swing Engine_
```

---

## 10. Database Schema (Supabase)

### 10.1 Tabel `signals`

```sql
CREATE TABLE signals (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticker              TEXT NOT NULL,
    signal_type         TEXT NOT NULL CHECK (signal_type IN ('BUY', 'EXIT', 'WATCH')),
    signal_strength     TEXT NOT NULL CHECK (signal_strength IN ('STRONG', 'NORMAL', 'BORDERLINE')),
    score               INTEGER NOT NULL CHECK (score BETWEEN 0 AND 100),
    confluence_count    INTEGER NOT NULL,
    entry_price         INTEGER,
    stop_loss           INTEGER,
    take_profit         INTEGER,
    risk_pct            NUMERIC(5,2),
    reward_pct          NUMERIC(5,2),
    rr_ratio            NUMERIC(4,2),
    narrative_text      TEXT NOT NULL,
    indicator_snapshot  JSONB NOT NULL DEFAULT '{}',
    status              TEXT NOT NULL DEFAULT 'ACTIVE'
                        CHECK (status IN ('ACTIVE', 'CLOSED_TP', 'CLOSED_SL', 'CLOSED_EXIT_SIGNAL', 'EXPIRED')),
    exit_price          INTEGER,
    exit_pct            NUMERIC(5,2),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at           TIMESTAMPTZ,
    run_id              UUID REFERENCES run_logs(id)
);

CREATE INDEX idx_signals_ticker_status ON signals(ticker, status);
CREATE INDEX idx_signals_created_at ON signals(created_at DESC);
CREATE INDEX idx_signals_status ON signals(status);
CREATE INDEX idx_signals_run_id ON signals(run_id);
```

**`indicator_snapshot` JSONB schema:**

```json
{
  "ema_20": 3150.5,
  "ema_50": 3080.2,
  "rsi_14": 42.3,
  "macd": 12.4,
  "macd_signal": 8.1,
  "macd_histogram": 4.3,
  "bb_lower": 2980.0,
  "bb_upper": 3320.0,
  "bb_percent": 0.42,
  "atr_14": 89.5,
  "obv": 12345678,
  "volume_ratio": 1.6,
  "close": 3150.0,
  "volume": 45678000
}
```

### 10.2 Tabel `ohlcv_cache`

```sql
CREATE TABLE ohlcv_cache (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticker      TEXT NOT NULL,
    trade_date  DATE NOT NULL,
    open        NUMERIC(12,2) NOT NULL,
    high        NUMERIC(12,2) NOT NULL,
    low         NUMERIC(12,2) NOT NULL,
    close       NUMERIC(12,2) NOT NULL,
    volume      BIGINT NOT NULL,
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(ticker, trade_date)
);

CREATE INDEX idx_ohlcv_ticker_date ON ohlcv_cache(ticker, trade_date DESC);
```

Data lebih dari 90 hari di-delete oleh monthly cleanup job.

### 10.3 Tabel `run_logs`

```sql
CREATE TABLE run_logs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_mode            TEXT NOT NULL CHECK (run_mode IN ('morning', 'closing', 'manual')),
    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ,
    duration_seconds    NUMERIC(6,2),
    tickers_scanned     INTEGER,
    tickers_failed      TEXT[],
    signals_generated   INTEGER,
    buy_signals         INTEGER,
    exit_signals        INTEGER,
    watch_signals       INTEGER,
    telegram_sent       INTEGER,
    telegram_failed     INTEGER,
    status              TEXT NOT NULL DEFAULT 'RUNNING'
                        CHECK (status IN ('RUNNING', 'SUCCESS', 'PARTIAL', 'FAILED')),
    error_message       TEXT,
    github_run_id       TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_run_logs_started_at ON run_logs(started_at DESC);
CREATE INDEX idx_run_logs_status ON run_logs(status);
```

### 10.4 Row Level Security (RLS)

```sql
-- Enable RLS pada semua tabel
ALTER TABLE signals ENABLE ROW LEVEL SECURITY;
ALTER TABLE ohlcv_cache ENABLE ROW LEVEL SECURITY;
ALTER TABLE run_logs ENABLE ROW LEVEL SECURITY;

-- Hanya service_role yang bisa akses
CREATE POLICY "service_role_full_access_signals"
    ON signals FOR ALL USING (auth.role() = 'service_role');

CREATE POLICY "service_role_full_access_ohlcv"
    ON ohlcv_cache FOR ALL USING (auth.role() = 'service_role');

CREATE POLICY "service_role_full_access_run_logs"
    ON run_logs FOR ALL USING (auth.role() = 'service_role');
```

ZENTRA menggunakan `SUPABASE_SERVICE_KEY` (bukan `SUPABASE_ANON_KEY`) untuk bypass RLS. Key ini hanya boleh ada di GitHub Secrets.

---

## 11. Scheduler & Orchestration

### 11.1 GitHub Actions Workflows

**File 1: `.github/workflows/morning_scan.yml`**

```yaml
name: ZENTRA Morning Scan
on:
  schedule:
    - cron: '45 1 * * 1-5'   # 08:45 WIB = 01:45 UTC, Senin-Jumat
  workflow_dispatch:
    inputs:
      mode:
        description: 'Scan mode override'
        required: false
        default: 'morning'

concurrency:
  group: zentra-morning
  cancel-in-progress: false

jobs:
  morning-scan:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    permissions:
      contents: read

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run ZENTRA Morning Scan
        run: python main.py --mode morning
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
          TELEGRAM_ADMIN_CHAT_ID: ${{ secrets.TELEGRAM_ADMIN_CHAT_ID }}
          GITHUB_RUN_ID: ${{ github.run_id }}
          ZENTRA_ENV: production
```

**File 2: `.github/workflows/closing_scan.yml`**

Identik dengan morning, tapi:
- Cron: `'45 9 * * 1-5'` (16:45 WIB = 09:45 UTC)
- Mode: `closing`
- Concurrency group: `zentra-closing`

**File 3: `.github/workflows/monthly_cleanup.yml`**

```yaml
name: ZENTRA Monthly Cleanup
on:
  schedule:
    - cron: '0 0 1 * *'
  workflow_dispatch:

jobs:
  cleanup:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install -r requirements.txt
      - run: python scripts/cleanup.py
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
```

### 11.2 Main Entrypoint (`main.py`)

```python
import asyncio
import argparse
import sys
from zentra.orchestrator import ZENTRAOrchestrator

def parse_args():
    parser = argparse.ArgumentParser(description="ZENTRA Trading Signal Engine")
    parser.add_argument("--mode", choices=["morning", "closing", "manual"], default="morning")
    parser.add_argument("--ticker", help="Scan single ticker only (for testing)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run without sending to Telegram or writing to DB")
    return parser.parse_args()

async def main():
    args = parse_args()
    orchestrator = ZENTRAOrchestrator(mode=args.mode, dry_run=args.dry_run)
    success = await orchestrator.run(single_ticker=args.ticker)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    asyncio.run(main())
```

### 11.3 Orchestrator (`zentra/orchestrator.py`)

Orchestrator mengkoordinasikan semua layer dalam urutan ini:

1. Validate environment variables
2. Create `run_log` record di Supabase (status: RUNNING)
3. Check market status (weekend/holiday detection)
4. Fetch semua data OHLCV (batch)
5. Process setiap ticker (isolated try/catch per ticker)
6. Collect semua sinyal yang dihasilkan
7. Sort sinyal (EXIT dahulu, BUY diurutkan berdasarkan skor)
8. Deduplicate (cek ACTIVE signals di Supabase)
9. Generate narratives untuk sinyal yang lolos filter
10. Send ke Telegram dengan rate limiting
11. Persist sinyal ke Supabase
12. Update status sinyal lama yang perlu di-expire (> 10 hari)
13. Update `run_log` ke SUCCESS/PARTIAL/FAILED
14. Kirim admin summary jika ada issues

---

## 12. Security Requirements

### 12.1 Secret Management

**Aturan absolut:**
- Tidak ada credential, API key, atau token yang hardcode di codebase, config file, atau komentar
- Semua secret hanya dari environment variables
- `.env` file boleh ada di lokal untuk development tapi WAJIB ada di `.gitignore`
- `.env.example` berisi semua key dengan nilai placeholder, tanpa nilai nyata

```bash
# .env.example
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your-service-role-key-here
TELEGRAM_BOT_TOKEN=123456789:your-bot-token-here
TELEGRAM_CHAT_ID=-1001234567890
TELEGRAM_ADMIN_CHAT_ID=123456789
ZENTRA_ENV=development
GITHUB_RUN_ID=local
```

**Validasi saat startup:**

```python
REQUIRED_ENV_VARS = [
    "SUPABASE_URL",
    "SUPABASE_SERVICE_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
]

def validate_env() -> None:
    missing = [var for var in REQUIRED_ENV_VARS if not os.getenv(var)]
    if missing:
        raise ConfigurationError(f"Missing required env vars: {', '.join(missing)}")
```

### 12.2 Supabase Security

- Gunakan **service role key**, bukan anon key, untuk backend ZENTRA
- RLS diaktifkan di semua tabel (lihat section 10.4)
- Tidak ada query dengan string interpolation langsung. Selalu gunakan Supabase Python client yang menggunakan parameterized queries secara internal

### 12.3 Telegram Security

- Bot token harus dianggap sama sensitifnya dengan password
- ZENTRA tidak menerima command atau input dari Telegram (satu arah: kirim saja). Ini mengeliminasi seluruh kelas attack vector dari Telegram webhook
- Tidak ada info sensitif yang dikirim ke chat yang tidak authorized

### 12.4 GitHub Actions Security

Gunakan permissions minimal di setiap workflow file:

```yaml
permissions:
  contents: read
```

Tidak ada logging yang mencetak nilai environment variable, bahkan di debug mode. Gunakan `structlog` dan pastikan log sanitizer aktif untuk env var values.

---

## 13. Performance Requirements

### 13.1 Execution Time Targets

| Fase | Target | Batas maksimum |
|---|---|---|
| Data fetch (20 tickers batch) | < 10 detik | 30 detik |
| Indicator calculation (20 tickers) | < 5 detik | 15 detik |
| Signal scoring (20 tickers) | < 2 detik | 5 detik |
| Narrative generation (per sinyal) | < 0.5 detik | 2 detik |
| Telegram delivery (per pesan) | < 2 detik | 5 detik |
| **Total run time** | **< 3 menit** | **10 menit** |

GitHub Actions timeout di-set ke 15 menit sebagai hard kill.

### 13.2 Optimizations

**Batch fetch:** Gunakan `yf.download()` dengan list semua tickers sekaligus, bukan loop `yf.Ticker(t).history()`. Ini mengurangi 20 HTTP requests menjadi 1 request.

**Indicator calculation:** `pandas-ta` menggunakan vectorized operations di atas NumPy. Hindari loop Python di atas baris DataFrame.

**Supabase batch writes:**

```python
# BAD: N database round trips
for row in ohlcv_rows:
    supabase.table("ohlcv_cache").insert(row).execute()

# GOOD: 1 database round trip
supabase.table("ohlcv_cache").upsert(
    ohlcv_rows,
    on_conflict="ticker,trade_date"
).execute()
```

---

## 14. Error Handling & Edge Cases

### 14.1 Error Taxonomy

```python
# zentra/exceptions.py

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

class TelegramError(ZENTRABaseError):
    """Error saat kirim pesan ke Telegram."""

class ConfigurationError(ZENTRABaseError):
    """Konfigurasi tidak valid atau env var hilang."""
```

### 14.2 Edge Cases per Komponen

**Data Fetcher:**

| Edge Case | Handling |
|---|---|
| yfinance return empty DataFrame | Raise `DataFetchError` |
| Partial data (beberapa hari hilang di tengah) | Validator detect gap, log warning, tetap proses |
| Network timeout | Retry 3x dengan exponential backoff |
| yfinance rate limit / 429 | Retry dengan wait 30 detik |
| Data terbaru adalah T-3 atau lebih tua | `StaleDataError`, skip ticker |
| Volume semua 0 (suspend/halt) | Log warning "kemungkinan saham di-suspend", skip |
| Harga close tiba-tiba 0 | `DataIntegrityError` |

**Indicator Calculator:**

| Edge Case | Handling |
|---|---|
| NaN di kolom kritis di baris terakhir | `CalculationError`, skip ticker |
| ATR = 0 atau sangat kecil (< 10 Rupiah) | Skip ticker, log "volatilitas terlalu rendah" |
| EMA belum terbentuk (data < window) | `InsufficientDataError` |

**Scorer:**

| Edge Case | Handling |
|---|---|
| Semua indikator negatif | `NO_SIGNAL`, tidak error |
| RR ratio di bawah minimum | Return `NO_SIGNAL` dengan reason |
| Ticker punya open ACTIVE signal | Skip BUY, tetap cek apakah perlu EXIT |
| Ticker ACTIVE > 10 hari | Generate EXPIRED, kirim notifikasi admin |

**Telegram Sender:**

| Edge Case | Handling |
|---|---|
| Bot token tidak valid | Log error, kirim ke admin log, tidak crash run |
| Chat ID salah / bot di-kick | Log error, continue |
| Pesan terlalu panjang (> 4096 karakter) | Truncate narrative, angka kritis tetap ada |
| Telegram server down (5xx) | Retry 3x, log failure |

**Supabase:**

| Edge Case | Handling |
|---|---|
| Connection timeout | Retry 2x |
| Unique constraint violation pada upsert | Ignored (expected behavior) |
| Service key expired | `ConfigurationError`, admin alert |

### 14.3 Market-Specific Edge Cases

**Trading Halt / Suspend:** Saham yang di-suspend tidak akan memiliki volume hari itu. Validator akan mendeteksi volume 0 atau data stale dan skip ticker.

**Rights Issue / Stock Split:** yfinance biasanya sudah adjust data historis. Namun jika ada adjustment besar yang belum tercermin (spike harga > 200% atau drop > 50% dari hari sebelumnya), log sebagai warning. Tetap proses — biarkan scorer memutuskan.

**Market Crash Day (IHSG turun > 5%):** Tidak ada handling khusus di v1.0. Scorer secara alami akan menghasilkan skor rendah untuk hampir semua ticker. Kemungkinan tidak ada sinyal yang keluar.

**Libur Nasional IDX:** Cek dilakukan di market status check (section 5.3). Jika terdeteksi libur, kirim notifikasi ke Telegram dan exit gracefully — jangan error.

### 14.4 Graceful Degradation

Tiga level operasi:

1. **Full operation:** Semua 20 ticker berhasil. Status: `SUCCESS`.
2. **Partial operation:** 1–15 ticker gagal. Sinyal dari ticker lain tetap dikirim. Status: `PARTIAL`. Admin alert dikirim dengan daftar ticker yang gagal.
3. **Critical failure:** Lebih dari 15 ticker gagal, ATAU Supabase tidak bisa diakses, ATAU Telegram tidak bisa diakses setelah retry. Status: `FAILED`. Admin alert dikirim.

---

## 15. Code Quality Standards

### 15.1 Project Structure

```
ZENTRA/
├── .github/
│   └── workflows/
│       ├── morning_scan.yml
│       ├── closing_scan.yml
│       └── monthly_cleanup.yml
├── zentra/
│   ├── __init__.py
│   ├── config.py              # Semua konstanta, ticker list, thresholds
│   ├── exceptions.py          # Custom exception hierarchy
│   ├── orchestrator.py        # Top-level coordinator
│   ├── data/
│   │   ├── __init__.py
│   │   ├── fetcher.py
│   │   └── validator.py
│   ├── analysis/
│   │   ├── __init__.py
│   │   ├── indicators.py
│   │   ├── scorer.py
│   │   └── risk.py
│   ├── narrative/
│   │   ├── __init__.py
│   │   ├── generator.py
│   │   └── blocks.py          # Semua blok teks, dipisah dari logic
│   ├── telegram/
│   │   ├── __init__.py
│   │   ├── sender.py
│   │   └── formatter.py       # MarkdownV2 formatting utils
│   └── db/
│       ├── __init__.py
│       ├── client.py          # Supabase client singleton
│       ├── signals_repo.py    # Repository pattern untuk tabel signals
│       ├── ohlcv_repo.py
│       └── run_logs_repo.py
├── scripts/
│   └── cleanup.py             # Monthly data cleanup
├── tests/
│   ├── conftest.py
│   ├── fixtures/
│   │   ├── ohlcv_bullish.csv
│   │   ├── ohlcv_bearish.csv
│   │   ├── ohlcv_minimal.csv
│   │   ├── ohlcv_insufficient.csv
│   │   ├── ohlcv_stale.csv
│   │   └── ohlcv_exit_setup.csv
│   ├── test_fetcher.py
│   ├── test_validator.py
│   ├── test_indicators.py
│   ├── test_scorer.py
│   ├── test_narrative.py
│   └── test_telegram_formatter.py
├── main.py
├── requirements.in
├── requirements.txt           # Generated, do not edit
├── pyproject.toml
├── .env.example
├── .gitignore
└── README.md
```

### 15.2 Python Standards

**Type hints wajib** di semua function dan method signature. Gunakan `from __future__ import annotations` di setiap file.

**Dataclasses untuk data structures:**

```python
from dataclasses import dataclass, field
from typing import Optional

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
```

**Enums untuk konstanta string:**

```python
from enum import Enum

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
```

**Config dengan frozen dataclasses:**

```python
# zentra/config.py
from dataclasses import dataclass

@dataclass(frozen=True)
class ScoringConfig:
    BUY_THRESHOLD: int = 70
    WATCH_THRESHOLD: int = 55
    MIN_CONFLUENCE: int = 3
    MIN_RR_RATIO: float = 1.5
    MAX_SL_PCT: float = 0.08
    SL_ATR_MULTIPLIER: float = 1.5
    TP_ATR_MULTIPLIER: float = 2.5
    SIGNAL_EXPIRY_DAYS: int = 10

@dataclass(frozen=True)
class DataConfig:
    LOOKBACK_DAYS: int = 60
    MIN_TRADING_DAYS: int = 30
    STALE_DATA_THRESHOLD_DAYS: int = 5
    FETCH_RETRY_ATTEMPTS: int = 3
    OHLCV_RETENTION_DAYS: int = 90

SCORING = ScoringConfig()
DATA = DataConfig()

TICKERS: tuple[str, ...] = (
    "BBCA", "BMRI", "BBRI", "NCKL", "RMKE",
    "BREN", "CBDK", "PTRO", "BRPT", "BUMI",
    "DEWA", "BRMS", "ENRG", "AMMN", "OASA",
    "ADMR", "RAJA", "SIMP", "GZCO", "PGEO",
)
```

**Structured logging:**

```python
import structlog

log = structlog.get_logger()

# Bind context untuk satu ticker processing
ticker_log = log.bind(ticker=ticker, run_id=run_id)
ticker_log.info("processing_ticker", data_rows=len(df))
ticker_log.warning("data_stale", days_old=3)
ticker_log.error("calculation_failed", error=str(e))
```

### 15.3 Linting & Formatting Config

```toml
# pyproject.toml
[tool.ruff]
line-length = 100
target-version = "py311"
select = ["E", "F", "W", "I", "N", "UP", "B", "C4", "SIM"]

[tool.black]
line-length = 100
target-version = ["py311"]

[tool.mypy]
python_version = "3.11"
strict = true
ignore_missing_imports = true

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

---

## 16. Testing Requirements

### 16.1 Test Coverage Targets

| Modul | Minimum Coverage |
|---|---|
| `data/validator.py` | 95% |
| `analysis/scorer.py` | 95% |
| `analysis/risk.py` | 95% |
| `telegram/formatter.py` | 90% |
| `data/fetcher.py` | 80% |
| `analysis/indicators.py` | 85% |
| `narrative/generator.py` | 80% |
| Overall | 85% |

### 16.2 Test Fixtures

Semua fixture di `tests/fixtures/` sebagai CSV files dengan data OHLCV representatif:

- `ohlcv_bullish.csv` — data dengan setup BUY yang jelas (uptrend, RSI baik, volume tinggi)
- `ohlcv_bearish.csv` — data dengan skor rendah, tidak ada sinyal
- `ohlcv_minimal.csv` — hanya 30 baris (minimum valid)
- `ohlcv_insufficient.csv` — hanya 20 baris (harus gagal validasi)
- `ohlcv_stale.csv` — data terakhir adalah 10 hari lalu
- `ohlcv_exit_setup.csv` — RSI overbought, MACD bearish crossover (harus trigger EXIT)

### 16.3 Key Test Cases

**Scorer tests:**
- Ticker dengan semua indikator bullish harus mendapat skor >= 70
- Ticker dengan RSI > 70 tidak boleh dapat skor >= 70 (overbought override)
- Ticker dengan volume < rata-rata tidak boleh dapat skor penuh
- Ticker dengan open ACTIVE signal di DB tidak boleh generate BUY baru (mock Supabase)
- RR ratio < 1.5 harus return NO_SIGNAL
- SL yang > 8% dari entry harus di-cap, bukan reject

**Narrative tests:**
- Output tidak boleh mengandung placeholder `{rsi}` yang belum di-replace
- Pesan BUY harus mengandung semua elemen wajib: entry, SL, TP, estimasi hold
- Pesan EXIT harus mengandung alasan exit dan estimasi gain/loss
- Semua karakter MarkdownV2 spesial harus di-escape dengan benar

**Validator tests:**
- DataFrame kosong harus raise `InsufficientDataError`
- DataFrame dengan close = 0 harus raise `DataIntegrityError`
- DataFrame dengan high < low harus raise `DataIntegrityError`
- Stale data (> 5 hari) harus raise `StaleDataError`
- DataFrame dengan 29 baris harus raise `InsufficientDataError`

**Risk calculator tests:**
- RR ratio selalu >= `MIN_RR_RATIO` untuk sinyal yang lolos
- Stop loss tidak boleh > 8% dari entry
- Harga entry, SL, TP harus integer (Rupiah tanpa desimal)
- Harga SL harus selalu < entry untuk BUY signal
- Harga TP harus selalu > entry untuk BUY signal

---

## 17. Deployment Guide

### 17.1 Prerequisites

1. GitHub account (private repository direkomendasikan)
2. Supabase project (free tier, tidak perlu CC)
3. Telegram bot (buat via @BotFather)
4. Telegram channel atau group (bot harus di-add sebagai admin dengan permission untuk post messages)

### 17.2 Initial Setup

**Step 1: Buat Telegram bot**

```
1. Chat dengan @BotFather di Telegram
2. /newbot -> ikuti instruksi -> simpan BOT_TOKEN
3. Buat channel atau group untuk sinyal ZENTRA
4. Add bot ke channel/group sebagai admin
5. Dapatkan chat_id: forward pesan dari channel ke @userinfobot
6. Dapatkan admin chat_id: kirim pesan ke @userinfobot dari akun pribadi
```

**Step 2: Setup Supabase**

```
1. Buat project baru di supabase.com (pilih region Singapore untuk latency rendah)
2. Masuk ke SQL Editor
3. Jalankan semua CREATE TABLE SQL dari section 10 (urutan: run_logs dulu, lalu signals, ohlcv_cache)
4. Aktifkan RLS dan jalankan CREATE POLICY dari section 10.4
5. Dapatkan dari Settings -> API:
   - Project URL (SUPABASE_URL)
   - service_role key (SUPABASE_SERVICE_KEY) -- jangan pakai anon key
```

**Step 3: Setup GitHub Repository**

```
1. Push code ke repo (pastikan .env tidak ikut, cek .gitignore)
2. Settings -> Secrets and variables -> Actions -> New repository secret
3. Tambahkan semua secrets:
   - SUPABASE_URL
   - SUPABASE_SERVICE_KEY
   - TELEGRAM_BOT_TOKEN
   - TELEGRAM_CHAT_ID
   - TELEGRAM_ADMIN_CHAT_ID
4. Enable GitHub Actions di repo Settings -> Actions -> General
```

**Step 4: Test run**

```bash
# Dari local dengan .env file
python main.py --mode morning --dry-run --ticker BBCA

# Atau trigger manual via GitHub Actions -> morning_scan -> Run workflow
```

### 17.3 Environment Variables Reference

| Variable | Deskripsi | Contoh |
|---|---|---|
| `SUPABASE_URL` | URL project Supabase | `https://abc123.supabase.co` |
| `SUPABASE_SERVICE_KEY` | Service role key | `eyJhbGciOi...` |
| `TELEGRAM_BOT_TOKEN` | Token dari BotFather | `123456789:AAF...` |
| `TELEGRAM_CHAT_ID` | ID channel/group sinyal | `-1001234567890` |
| `TELEGRAM_ADMIN_CHAT_ID` | ID untuk admin alert | `987654321` |
| `ZENTRA_ENV` | Environment flag | `production` atau `development` |
| `GITHUB_RUN_ID` | Auto-set oleh GH Actions | `12345678` |

---

## 18. Monitoring & Observability

### 18.1 Run Health Queries

```sql
-- Lihat 7 run terakhir
SELECT run_mode, started_at, duration_seconds, status,
       tickers_scanned, signals_generated, tickers_failed
FROM run_logs
ORDER BY started_at DESC
LIMIT 7;

-- Deteksi run yang sering gagal
SELECT DATE(started_at) as date, COUNT(*) as runs,
       SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) as failures
FROM run_logs
WHERE started_at > NOW() - INTERVAL '30 days'
GROUP BY DATE(started_at)
ORDER BY date DESC;
```

### 18.2 Signal Performance Queries

```sql
-- Win rate per ticker (closed signals only)
SELECT
    ticker,
    COUNT(*) as total_signals,
    SUM(CASE WHEN exit_pct > 0 THEN 1 ELSE 0 END) as wins,
    ROUND(100.0 * SUM(CASE WHEN exit_pct > 0 THEN 1 ELSE 0 END) / COUNT(*), 1) as win_rate_pct,
    ROUND(AVG(exit_pct), 2) as avg_return_pct,
    ROUND(AVG(EXTRACT(EPOCH FROM (closed_at - created_at)) / 86400), 1) as avg_hold_days
FROM signals
WHERE status IN ('CLOSED_TP', 'CLOSED_SL', 'CLOSED_EXIT_SIGNAL')
GROUP BY ticker
ORDER BY win_rate_pct DESC;

-- Sinyal yang masih ACTIVE dan sudah berapa hari
SELECT ticker, score, entry_price, take_profit, stop_loss,
       created_at,
       EXTRACT(EPOCH FROM (NOW() - created_at)) / 86400 AS days_active
FROM signals
WHERE status = 'ACTIVE'
ORDER BY days_active DESC;
```

### 18.3 Admin Notifications

ZENTRA mengirim alert ke `TELEGRAM_ADMIN_CHAT_ID` untuk:
- Run `FAILED`
- Run `PARTIAL` dengan > 5 ticker gagal
- Sinyal `ACTIVE` yang sudah > 10 hari (sebelum di-expire)
- Tidak ada sinyal dalam 5 hari berturut-turut (kemungkinan ada bug)

---

## 19. Future Roadmap

### Phase 2: Performance Auto-Tracker
- Auto-update status sinyal ke `CLOSED_TP` atau `CLOSED_SL` berdasarkan pergerakan harga harian
- Weekly performance summary otomatis ke Telegram setiap Jumat sore
- Win rate dan average return per ticker di summary

### Phase 3: Backtesting Module
- Script `backtest.py` yang bisa dijalankan lokal
- Jalankan scoring engine di data historis 1 tahun
- Output: equity curve simulasi, win rate, max drawdown, Sharpe ratio
- Langkah kritis sebelum mempercayai sinyal dengan modal lebih besar

### Phase 4: Dashboard (Streamlit Cloud, gratis)
- Halaman utama: sinyal aktif, win rate, equity curve
- Halaman history: semua sinyal dengan filter ticker dan tanggal
- Deploy ke Streamlit Community Cloud (gratis, connect ke Supabase)

### Phase 5: Adaptive Thresholds
- Threshold scoring yang berubah berdasarkan kondisi IHSG keseluruhan
- Ketika pasar bearish, naikkan threshold BUY dari 70 ke 80
- Ketika pasar bullish dengan momentum kuat, threshold bisa turun ke 65

---

## 20. Glossary

| Term | Definisi |
|---|---|
| ATR | Average True Range — ukuran volatilitas rata-rata harian |
| Bollinger Bands | Envelope di sekitar moving average menggunakan standard deviation |
| Confluence | Kondisi di mana beberapa indikator independent memberikan sinyal yang sama |
| EMA | Exponential Moving Average — moving average yang memberikan bobot lebih pada data terbaru |
| Golden Cross | EMA jangka pendek memotong ke atas EMA jangka panjang — sinyal bullish |
| IDX | Indonesia Stock Exchange (Bursa Efek Indonesia) |
| MACD | Moving Average Convergence Divergence — indikator trend dan momentum |
| NLG | Natural Language Generation — proses mengubah data menjadi teks naratif |
| OBV | On-Balance Volume — mengukur tekanan beli/jual berdasarkan akumulasi volume |
| OHLCV | Open, High, Low, Close, Volume — data harga standar per hari |
| RSI | Relative Strength Index — mengukur kecepatan dan magnitude perubahan harga (0–100) |
| RR Ratio | Risk/Reward Ratio — perbandingan potensi kerugian vs potensi keuntungan |
| Stochastic RSI | RSI dari RSI — lebih sensitif terhadap perubahan momentum jangka pendek |
| Swing Trading | Strategi hold posisi beberapa hari hingga beberapa minggu |
| T+2 | Settlement cycle di IDX: transaksi hari ini settle 2 hari kemudian |
| Ticker | Kode saham, contoh: BBCA, BMRI, BREN |

---

*ZENTRA PRD v1.0 — Dokumen ini adalah sumber kebenaran tunggal untuk implementasi ZENTRA. Semua keputusan teknis yang tidak tercakup di sini harus merujuk ke prinsip utama: akurasi sinyal di atas segalanya, keandalan di atas fitur, zero cost di atas kenyamanan.*
