# Contoh Sinyal Telegram ZENTRA

Berikut adalah berbagai macam contoh format pesan Telegram yang dikirimkan oleh ZENTRA Trading Engine pada berbagai kondisi pasar.

---

### 1. Sinyal Beli (Buy Signal)
Dikirim ketika sebuah saham memiliki indikator teknikal yang sangat kuat dan setup skor melampaui ambang batas (Buy Threshold).

```text
🚨 ZENTRA ENTRY SIGNAL 🚨

Ticker: BBCA
Date: 2026-05-07
Setup Score: 78/100
Confluence: 4 indicators

Entry: Rp 9,800
Stop Loss: Rp 9,300 (-5.1%)
Take Profit: Rp 10,650 (+8.6%)
R/R Ratio: 1.70
```

---

### 2. Sinyal Tidak Ada Setup (No Signal)
Dikirim pada sore hari (16:45) jika tidak ada saham yang memenuhi kriteria beli setelah ZENTRA melakukan pemindaian ke 20 saham pantauan.

```text
ℹ️ ZENTRA DAILY SCAN
2026-05-07

No buy signals generated today.
Market conditions do not meet strict entry criteria.
Stay patient. Cash is a position.
```

---

### 3. Sinyal Pantau (Watchlist Signal)
Dikirim pada pagi hari (09:15) saat *morning scan*. ZENTRA mendeteksi beberapa saham yang menunjukkan momentum awal yang bagus dan berpotensi menjadi sinyal beli pada sore hari. Ini bukan sinyal eksekusi, melainkan pemberitahuan untuk *standby*.

```text
👀 ZENTRA MORNING WATCHLIST
Time: 09:15 AM
Date: 2026-05-07

The following tickers are showing strong early momentum and may trigger a BUY signal at market close:

1. BMRI (Score: 68/100)
2. BRPT (Score: 62/100)

Standby for final confirmation at 16:45.
```

---

### 4. Sinyal Jual: Kena Take Profit (Hard Exit)
Sistem secara otomatis akan menutup dan mencatat posisi (jika kita auto-trading) atau memberi notifikasi jika harga *High* hari ini telah menyentuh target harga yang kita tetapkan di awal.

```text
✅ ZENTRA TAKE PROFIT HIT

Ticker: NCKL
Entry Price: Rp 950
Exit Price: Rp 1,060
Profit: +11.5%
Holding Days: 4 days

Reason: Target price reached.
```

---

### 5. Sinyal Jual: Kena Stop Loss (Hard Exit)
Dikirim jika harga *Low* hari ini turun hingga menyentuh level Cut Loss yang telah dihitung berdasarkan volatilitas ATR di awal entry.

```text
🛑 ZENTRA STOP LOSS HIT

Ticker: ADMR
Entry Price: Rp 1,200
Exit Price: Rp 1,120
Loss: -6.6%
Holding Days: 2 days

Reason: Stop loss hit.
```

---

### 6. Sinyal Jual: Penurunan Setup / Soft Exit
Jika setelah masa *grace period* (3 hari) saham tersebut tidak bergerak ke mana-mana dan momentum indikatornya memudar (seperti MACD dead cross atau harga jatuh kembali ke bawah EMA-20), ZENTRA akan memberikan sinyal Exit dini untuk mengamankan modal (meskipun belum kena Stop Loss).

```text
⚠️ ZENTRA EARLY EXIT SIGNAL

Ticker: GZCO
Entry Price: Rp 135
Exit Price: Rp 132
Loss: -2.2%
Holding Days: 5 days

Reason: Setup score dropped below threshold (MACD bearish crossover)
```

---

### 7. Sinyal Jual: Expired (Soft Exit)
Jika sebuah saham dibeli, dan harganya hanya diam atau *sideways* tanpa menyentuh TP dan SL selama durasi batas maksimal menahan barang (10 hari). ZENTRA merekomendasikan jual agar modal bisa diputar ke saham lain.

```text
⏳ ZENTRA POSITION EXPIRED

Ticker: DEWA
Entry Price: Rp 65
Exit Price: Rp 67
Profit: +3.0%
Holding Days: 10 days

Reason: Expired (10d limit reached)
```

---

### 8. Laporan Kinerja Mingguan (Weekly Performance)
Dikirim secara otomatis setiap hari Jumat sore (setelah scan 16:45). ZENTRA merangkum semua posisi yang telah di-close minggu tersebut.

```text
📊 ZENTRA WEEKLY PERFORMANCE
Week ending: 2026-05-08

Win Rate: 66.7% (2W, 1L)
Avg Return: +3.4%
Total Signals Generated: 4

🏆 Top Winner: NCKL (+11.5%)
💔 Top Loser: ADMR (-6.6%)

Engine Status: HEALTHY
```

---

### 9. Laporan Kesalahan (Error Alert)
Dikirim ke Admin/Developer (biasanya ke channel yang sama jika tidak ada channel *debug* khusus) jika terjadi kesalahan fatal pada sistem, seperti API Yahoo Finance down atau Supabase *rate limited*.

```text
🔥 ZENTRA CRITICAL ERROR 🔥
Date: 2026-05-07 16:45

Failed to complete daily scan.
Error: Database connection timeout (Supabase).
Please check the logs.
```
