# 🥇 XAUUSD ICT Trading Bot

Bot trading otomatis untuk **XAUUSD (Gold)** menggunakan strategi **Smart Money Concepts (SMC)** dengan eksekusi langsung ke **MetaTrader 5**.

## 📋 Fitur Utama

- **Fair Value Gap (FVG) Detection** — Mendeteksi zona FVG M5 sebagai area entry
- **Market Structure Analysis** — BOS (Break of Structure) & CHoCH (Change of Character) untuk menentukan bias pasar
- **Order Block Detection** — Identifikasi zona institusional
- **Auto Execution ke MT5** — Market order langsung ke MetaTrader 5 dengan SL/TP otomatis
- **Telegram Control Panel** — Monitoring & kontrol bot via inline keyboard Telegram
- **Risk Management** — Daily loss limit, adjustable lot size, configurable trading hours (WIB)

## 🏗️ Arsitektur

```
┌─────────────────┐     ┌──────────────┐     ┌──────────────┐
│   TradingView   │────▶│  SMC Engine   │────▶│  MT5 Executor │
│  (Data Source)  │     │ (smc_local)  │     │  (Execution)  │
└─────────────────┘     └──────────────┘     └──────────────┘
                              │
                              ▼
                     ┌──────────────────┐
                     │  Live Trader     │
                     │  (Orchestrator)  │
                     └────────┬─────────┘
                              │
                              ▼
                     ┌──────────────────┐
                     │  Telegram Bot    │
                     │  (Notifikasi &   │
                     │   Kontrol)       │
                     └──────────────────┘
```

## 📁 Struktur File

| File | Deskripsi |
|---|---|
| `live_trader.py` | **Orchestrator utama** — loop trading, entry logic, Telegram listener |
| `smc_local.py` | **SMC Engine** — deteksi FVG, BOS, CHoCH, Order Block, market bias |
| `mt5_executor.py` | **MT5 Executor** — buka/tutup posisi, modify SL, cek posisi aktif |
| `tradingview_tool.py` | **Data Fetcher** — ambil candle XAUUSD real-time dari TradingView |
| `xauusd_fetcher.js` | **Node.js WebSocket** — koneksi TradingView WebSocket API |
| `telegram_notifier.py` | **Telegram API** — kirim notifikasi, inline keyboard, edit message |
| `config.py` | **Konfigurasi** — Telegram token, MT5 settings, lot size, trading hours |
| `bot.py` | **Entry point alternatif** — mode sinyal, backtest, dan interaktif |

## ⚙️ Strategi Entry

### Kondisi Entry:
1. **Market Bias** cocok dengan arah FVG (bullish bias + bullish FVG → BUY, dan sebaliknya)
2. **Candle M5 menyentuh zona FVG** — cukup wick/shadow yang menyentuh, tidak perlu close di dalam zona

### Parameter:
| Parameter | Nilai |
|---|---|
| Timeframe | M5 (5 Menit) |
| FVG Min Gap | 2.0 poin |
| FVG Max Age | 200 candle |
| Risk:Reward | 1:2 |
| SL Buffer | max(ATR×0.5, 2.0) |

### Flow Entry:
```
Candle M5 Baru
    │
    ▼
analyze_smc() → FVG aktif + market bias
    │
    ▼
Candle menyentuh zona FVG? (low ≤ fvg_high AND high ≥ fvg_low)
    │
    ├─ Ya + Bias cocok → Market Order ke MT5
    │
    └─ Tidak → Skip, tunggu candle berikutnya
```

## 🚀 Setup & Instalasi

### Prerequisites
- Python 3.10+
- Node.js 18+
- MetaTrader 5 (running di PC)
- Telegram Bot Token

### 1. Install Dependencies

```bash
# Python
pip install -r requirements.txt
pip install MetaTrader5 requests

# Node.js
npm install
```

### 2. Konfigurasi

Edit `config.py`:
```python
TELEGRAM_BOT_TOKEN = "your_bot_token"
TELEGRAM_CHAT_ID = "your_chat_id"
MT5_SYMBOL = "XAUUSDc"  # Sesuaikan dengan broker
```

### 3. Jalankan Bot

```bash
python live_trader.py
```

## 📱 Telegram Commands

| Command | Fungsi |
|---|---|
| `/menu` | Tampilkan menu interaktif (inline keyboard) |
| `/status` | Info akun, balance, equity, status bot |
| `/pnl` | P&L hari ini (win/loss/winrate) |
| `/pause` | Pause entry baru (posisi aktif tetap dimonitor) |
| `/resume` | Resume trading |
| `/be` | Geser SL ke breakeven untuk posisi yang sudah profit |
| `/close` | Tutup semua posisi aktif |
| `/setlot 0.05` | Ubah lot size |
| `/setloss 15` | Ubah daily loss limit ($) |
| `/setjam 8 22` | Ubah jam trading (WIB) |
| `/journal` | 5 transaksi terakhir |

## 🛡️ Risk Management

- **Daily Loss Limit** — Bot berhenti entry jika total kerugian hari ini melebihi batas (default: $10)
- **Single Position** — Hanya 1 posisi aktif pada satu waktu
- **Trading Hours** — Hanya entry di jam aktif (default: 08:00 - 19:00 WIB)
- **Pause/Resume** — Kontrol manual via Telegram tanpa mematikan bot

## 📄 License

Private repository — for personal use only.
