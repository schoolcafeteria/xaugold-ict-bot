import time
import sys
import os
import logging
import threading
import requests
from datetime import datetime, timezone, timedelta
from config import (
    MT5_SYMBOL, 
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    get_lot_size, save_lot_size,
    get_daily_loss_limit, save_daily_loss_limit,
    get_trading_hours, save_trading_hours
)
from tradingview_tool import fetch_xauusd_data
from smc_local import analyze_smc
import mt5_executor

# =====================================================================
# INSTANCE LOCK — Pastikan hanya 1 bot yang berjalan sekaligus
# =====================================================================
_LOCK_SOCKET = None
_LOCK_PORT   = 47777  # Port unik khusus untuk lock bot ini

def _check_single_instance():
    """Cek apakah sudah ada instance bot yang berjalan. Jika ya, keluar."""
    global _LOCK_SOCKET
    import socket
    _LOCK_SOCKET = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    _LOCK_SOCKET.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    try:
        _LOCK_SOCKET.bind(('127.0.0.1', _LOCK_PORT))
        # Berhasil bind → kita adalah satu-satunya instance
    except OSError:
        print(f"[INSTANCE LOCK] Bot sudah berjalan di port {_LOCK_PORT}. Instance ini dihentikan.")
        sys.exit(0)

def _release_lock():
    """Lepas lock socket saat bot berhenti."""
    global _LOCK_SOCKET
    try:
        if _LOCK_SOCKET:
            _LOCK_SOCKET.close()
    except Exception:
        pass

import atexit
_check_single_instance()
atexit.register(_release_lock)
from telegram_notifier import (
    send_telegram_notification,
    send_telegram_with_keyboard,
    edit_telegram_message,
    answer_callback_query,
    send_telegram_photo
)
from pnl_card import generate_card_for_date

# Setup logging ke console dan file (dengan UTF-8 untuk support emoji di Windows)
log_format = '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
log_formatter = logging.Formatter(log_format)

# Console handler dengan UTF-8 encoding (fix emoji error di Windows cp1252)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(log_formatter)
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# File handler sudah UTF-8
file_handler = logging.FileHandler("live_trader.log", encoding="utf-8")
file_handler.setFormatter(log_formatter)

logging.basicConfig(level=logging.INFO, handlers=[console_handler, file_handler])
logger = logging.getLogger("ICTBot.LiveTrader")

# State tracker harian
state = {
    "current_date": None,
    "daily_loss": 0.0,
    "processed_bars": set(),       # Bar timestamps yang sudah dianalisis entry-nya
    "last_closed_deal_ticket": 0,  # Melacak tiket transaksi terluar untuk hitung rugi
    "active_tickets": [],          # Menyimpan ID tiket posisi bot yang sedang berjalan
    "paused": False,               # Pause entry baru via /pause, posisi aktif tetap dimonitor
    "profit_lock_triggered": set(), # Tiket posisi yang sudah di-lock profit (SL sudah digeser)
}

# ─── Konfigurasi Profit Lock ───────────────────────────────────────────────────
# Saat profit mencapai PROFIT_LOCK_TRIGGER_PIPS, SL digeser ke entry + PROFIT_LOCK_SL_PIPS
# Untuk XAUUSD: 1 pip = 10 poin (0.10), 1 poin = 0.01
# 30 pips = 300 poin = 3.00 harga
# 5 pips  = 50 poin  = 0.50 harga
PROFIT_LOCK_TRIGGER_POINTS = 300  # 300 poin = 30 pips — trigger geser SL
PROFIT_LOCK_SL_POINTS      = 50   # 50 poin = 5 pips  — SL baru di atas/bawah entry
POINT_VALUE                = 0.01 # Nilai 1 point untuk XAUUSD

def is_trading_hour():
    """
    Cek apakah waktu saat ini berada di dalam jam trading aktif (WIB).
    Jam bisa diubah via /setjam di Telegram.
    """
    # Waktu UTC + 7 Jam = WIB
    wib_now = datetime.now(timezone.utc) + timedelta(hours=7)
    start, end = get_trading_hours()
    return start <= wib_now.hour < end

def update_daily_losses():
    """
    Mengecek history transaksi di MT5 hari ini (WIB) untuk menghitung total loss berjalan.
    """
    wib_now = datetime.now(timezone.utc) + timedelta(hours=7)
    date_str = wib_now.strftime('%Y-%m-%d')
    
    if state["current_date"] != date_str:
        logger.info(f"📅 Memulai hari baru trading: {date_str}. Reset loss harian ke $0.00.")
        state["current_date"] = date_str
        state["daily_loss"] = 0.0
        state["processed_bars"].clear()

    # Inisialisasi koneksi MT5
    if not mt5_executor.initialize_mt5():
        return

    start_date_local = datetime.now() - timedelta(days=1) # Ambil buffer 24 jam terakhir
    # Tambah buffer + 1 hari ke depan agar transaksi dengan server time maju tidak terpotong
    history_deals = mt5_executor.mt5.history_deals_get(start_date_local, datetime.now() + timedelta(days=1))
    
    if history_deals is None:
        return

    # Hitung total kerugian dari deal yang ditutup hari ini
    total_loss_today = 0.0
    for deal in history_deals:
        # Cek apakah deal merupakan hasil close posisi (bukan opening deal)
        # Entry type: 0=Buy, 1=Sell. Exit/deal type: 1=Out (position close)
        if deal.entry == 1: # Deal entry OUT
            deal_time = datetime.fromtimestamp(deal.time) - timedelta(hours=3)
            deal_date_str = deal_time.strftime('%Y-%m-%d')
            
            # Hanya hitung deal yang ditutup hari ini (WIB)
            if deal_date_str == date_str:
                profit = deal.profit + deal.swap + deal.commission
                if profit < 0:
                    total_loss_today += abs(profit)

    state["daily_loss"] = round(total_loss_today, 2)

def monitor_closed_positions():
    """
    Memantau apakah posisi bot yang terdaftar di state['active_tickets'] sudah ditutup.
    Jika ya, kirim notifikasi ke Telegram dengan detil profit/loss dan status (TP/SL/Manual).
    """
    if not state["active_tickets"]:
        return

    if not mt5_executor.initialize_mt5():
        return

    # Ambil posisi aktif saat ini dari terminal MT5
    active_positions = mt5_executor.check_active_positions()
    active_ids = {pos.ticket for pos in active_positions}

    # Cari tiket yang terdaftar di bot tapi sudah tidak ada di daftar posisi aktif MT5
    closed_tickets = []
    for t in state["active_tickets"]:
        if t not in active_ids:
            closed_tickets.append(t)

    for ticket in closed_tickets:
        logger.info(f"🔍 Mendeteksi tiket #{ticket} telah ditutup. Mengambil detail history...")
        
        # Ambil history deals dengan rentang waktu lebih lebar (2 hari + buffer ke depan)
        start_time = datetime.now() - timedelta(days=2)
        end_time = datetime.now() + timedelta(days=1)
        history_deals = mt5_executor.mt5.history_deals_get(start_time, end_time)
        
        if not history_deals:
            logger.warning(f"Detail deal untuk tiket #{ticket} tidak ditemukan di history.")
            if ticket in state["active_tickets"]:
                state["active_tickets"].remove(ticket)
            continue

        # Cari deal penutupan (entry == 1 (OUT)) yang terikat dengan posisi
        closing_deal = None
        for deal in history_deals:
            # Cek berdasarkan position_id, order ticket, atau deal ticket
            if deal.entry == 1 and (deal.position_id == ticket or deal.order == ticket or deal.ticket == ticket):
                closing_deal = deal
                break

        if closing_deal is None:
            # Fallback: cari deal OUT terbaru dengan magic number bot dan simbol yang sama
            for deal in reversed(list(history_deals)):
                if deal.entry == 1 and deal.magic == mt5_executor.MT5_MAGIC_NUMBER:
                    closing_deal = deal
                    logger.info(f"Fallback: Ditemukan deal OUT magic={deal.magic} tiket={deal.ticket}")
                    break

        if closing_deal is None:
            # Coba lagi pada siklus berikutnya, tapi hapus setelah 3 menit gagal
            logger.warning(f"Deal OUT untuk tiket posisi #{ticket} belum tercatat di history broker.")
            # Hapus tiket jika sudah tidak ada di MT5 untuk mencegah loop stuck
            if ticket in state["active_tickets"]:
                state["active_tickets"].remove(ticket)
                logger.info(f"Tiket #{ticket} dihapus dari tracking (posisi sudah tidak ada di MT5).")
                send_telegram_notification(
                    f"🔔 *POSISI DITUTUP*\\n\\n"
                    f"🆔 Tiket: #{ticket}\\n"
                    f"ℹ️ Posisi sudah tidak aktif di MT5.\\n"
                    f"⚠️ Detail P/L tidak tersedia (deal history belum tercatat)."
                )
            continue

        # Hitung keuntungan bersih (profit + swap + komisi)
        net_profit = closing_deal.profit + closing_deal.swap + closing_deal.commission
        
        # Tentukan arah posisi awal
        # Tipe deal OUT berlawanan dengan arah posisi awal.
        # Jadi jika deal OUT nya SELL (1), posisi awalnya adalah BUY. Jika deal OUT nya BUY (0), posisi awalnya adalah SELL.
        pos_direction = "BUY" if closing_deal.type == 1 else "SELL"
        
        # Cari deal pembukaan (IN) untuk mengetahui harga entry awal
        opening_price = 0.0
        for d in history_deals:
            if d.position_id == ticket and d.entry == 0:
                opening_price = d.price
                break

        # Tentukan alasan penutupan (3=SL, 4=TP, 0=Manual)
        reason_code = closing_deal.reason
        status_str = "CLOSED MANUAL ⚪"
        if reason_code == 4:
            status_str = "STOP LOSS (SL) 🔴"
        elif reason_code == 5:
            status_str = "TAKE PROFIT (TP) 🟢"
        
        profit_emoji = "🟢" if net_profit >= 0 else "🔴"
        sign = "+" if net_profit >= 0 else ""
        
        msg = (
            f"🔔 *POSISI BERHASIL DITUTUP!*\n\n"
            f"📈 *Arah:* {pos_direction}\n"
            f"💰 *Lot:* {closing_deal.volume:.2f}\n"
            f"💵 *Harga Entry:* {opening_price if opening_price > 0 else 'N/A'}\n"
            f"💵 *Harga Exit:* {closing_deal.price}\n"
            f"🎯 *Status:* {status_str}\n"
            f"💵 *Profit/Loss:* `{sign}${net_profit:.2f}` {profit_emoji}"
        )
        
        logger.info(f"Notifikasi penutupan terkirim: Tiket #{ticket} | PnL: ${net_profit:.2f}")
        send_telegram_notification(msg)
        if ticket in state["active_tickets"]:
            state["active_tickets"].remove(ticket)

def check_profit_lock():
    """
    Memantau posisi aktif dan menggeser SL secara otomatis saat profit
    mencapai PROFIT_LOCK_TRIGGER_POINTS (default: 300 poin / 30 pips).
    SL baru dipasang di entry + PROFIT_LOCK_SL_POINTS (default: 50 poin / 5 pips)
    untuk mengamankan profit minimum.
    
    Fungsi ini hanya menggeser SL satu kali per tiket (tidak berulang).
    """
    if not mt5_executor.initialize_mt5():
        return

    active_positions = mt5_executor.check_active_positions()
    if not active_positions:
        # Bersihkan tiket yang sudah tidak aktif dari profit_lock_triggered
        state["profit_lock_triggered"].clear()
        return

    active_ticket_ids = {pos.ticket for pos in active_positions}
    # Hapus tiket yang sudah tutup dari tracker
    state["profit_lock_triggered"] = state["profit_lock_triggered"] & active_ticket_ids

    trigger_price = PROFIT_LOCK_TRIGGER_POINTS * POINT_VALUE  # 300 * 0.01 = 3.00
    sl_offset     = PROFIT_LOCK_SL_POINTS * POINT_VALUE       # 50  * 0.01 = 0.50

    for pos in active_positions:
        # Skip jika tiket ini sudah pernah di-lock
        if pos.ticket in state["profit_lock_triggered"]:
            continue

        entry_price   = pos.price_open
        current_price = pos.price_current
        direction     = "BUY" if pos.type == 0 else "SELL"

        # Hitung profit dalam poin dari harga entry
        if pos.type == 0:  # BUY — harga harus naik
            profit_points_move = current_price - entry_price
            new_sl = round(entry_price + sl_offset, 2)
            sl_sudah_lebih_baik = pos.sl >= new_sl  # SL sudah di atas target baru
        else:              # SELL — harga harus turun
            profit_points_move = entry_price - current_price
            new_sl = round(entry_price - sl_offset, 2)
            sl_sudah_lebih_baik = pos.sl > 0 and pos.sl <= new_sl  # SL sudah di bawah target baru

        # Cek apakah profit sudah mencapai trigger
        if profit_points_move < trigger_price:
            logger.info(
                f"[ProfitLock] #{pos.ticket} ({direction}) | "
                f"Profit move: {profit_points_move:.2f} / {trigger_price:.2f} — belum trigger"
            )
            continue

        # Skip jika SL sudah lebih baik dari target (sudah digeser manual/sebelumnya)
        if sl_sudah_lebih_baik:
            logger.info(
                f"[ProfitLock] #{pos.ticket} ({direction}) | "
                f"SL sudah di posisi lebih baik ({pos.sl}) dari target ({new_sl}), skip."
            )
            state["profit_lock_triggered"].add(pos.ticket)
            continue

        # Geser SL ke entry + offset
        logger.info(
            f"[ProfitLock] #{pos.ticket} ({direction}) | "
            f"Profit {profit_points_move:.2f} poin >= trigger {trigger_price:.2f} poin. "
            f"Geser SL dari {pos.sl} → {new_sl}"
        )
        if mt5_executor.modify_sl(pos, new_sl):
            state["profit_lock_triggered"].add(pos.ticket)
            pnl = pos.profit + pos.swap + pos.commission
            send_telegram_notification(
                f"🔒 *PROFIT LOCK AKTIF!*\n\n"
                f"🆔 *Tiket:* #{pos.ticket}\n"
                f"📈 *Arah:* {direction}\n"
                f"💵 *Entry:* `{entry_price:.2f}`\n"
                f"📍 *Harga Sekarang:* `{current_price:.2f}`\n"
                f"✅ *SL Baru:* `{new_sl:.2f}` (+{PROFIT_LOCK_SL_POINTS} poin dari entry)\n"
                f"📊 *Floating P/L:* `${pnl:.2f}`\n"
                f"_Profit {PROFIT_LOCK_TRIGGER_POINTS} poin tercapai — SL diamankan._"
            )
        else:
            logger.error(f"[ProfitLock] Gagal menggeser SL posisi #{pos.ticket}")


def profit_lock_thread():
    """
    Thread background khusus untuk memantau Profit Lock setiap 1 detik.
    Lebih responsif dibanding menunggu siklus scan 15 detik.
    """
    logger.info("🔒 Profit Lock thread aktif (scan tiap 1 detik).")
    while True:
        try:
            check_profit_lock()
        except Exception as e:
            logger.error(f"Error pada profit_lock_thread: {e}")
        time.sleep(1)


def run_trading_cycle():
    """
    Satu siklus scan market, deteksi sinyal, dan eksekusi MT5.
    """
    # 1. Pantau penutupan posisi aktif bot
    monitor_closed_positions()

    # 2. Update status kerugian harian berjalan
    update_daily_losses()

    current_loss_limit = get_daily_loss_limit()

    # 4. Cek filter Daily Loss Limit
    if state["daily_loss"] >= current_loss_limit:
        logger.warning(f"⚠️ Batas kerugian harian tercapai: ${state['daily_loss']} >= ${current_loss_limit}. Auto-trade dinonaktifkan untuk sisa hari ini.")
        return

    # 4. Cek filter jam perdagangan WIB
    start_h, end_h = get_trading_hours()
    if not is_trading_hour():
        logger.info(f"💤 Di luar jam perdagangan aktif ({start_h:02d}:00 - {end_h:02d}:00 WIB). Menunggu...")
        return

    # 5. Ambil candle real-time (Timeframe M5 langsung)
    logger.info("Mengambil data candle M5 dari TradingView...")
    data = fetch_xauusd_data(symbol="FOREXCOM:XAUUSD", timeframe="5", limit=500, range_val=500)
    
    # Cek error, tapi tetap lanjut jika candle tersedia
    if 'error' in data and not data.get('candles'):
        logger.error(f"Gagal mengambil candle dari TradingView: {data['error']}")
        return

    candles = data.get('candles', [])
    if not candles:
        logger.warning("Tidak ada data candle baru terdeteksi.")
        return

    logger.info(f"Data candle diterima: {len(candles)} candle M5")

    latest_candle = candles[-1]
    candle_time = latest_candle.get('time')

    # Cek apakah candle terakhir sudah pernah kita proses untuk entry baru
    if candle_time in state["processed_bars"]:
        return # Abaikan jika bar ini sudah kita periksa

    # 6. Hitung analisis ICT pada M5
    if len(candles) < 30:
        logger.warning(f"Data M5 tidak cukup ({len(candles)} candle), skip siklus ini.")
        return

    smc_m5 = analyze_smc(candles)
    market_bias = smc_m5.get('market_bias', 'neutral')
    active_fvgs = smc_m5.get('active_fvgs', [])

    rsi = latest_candle.get('rsi_14')
    ema_200 = latest_candle.get('ema_200')
    current_price = latest_candle['close']

    # ATR M5 dari TradingView (sudah built-in), fallback ke manual
    atr_m5 = latest_candle.get('atr_14')
    if not atr_m5 and len(candles) >= 14:
        recent_ranges = [c['high'] - c['low'] for c in candles[-14:]]
        atr_m5 = sum(recent_ranges) / len(recent_ranges)

    atr_m5_str = f"{atr_m5:.2f}" if atr_m5 else "N/A"
    logger.info(f"[SCAN] Harga={current_price:.2f} | M5_Bias={market_bias} | RSI={rsi} | EMA200={ema_200} | ATR_M5={atr_m5_str} | FVG_aktif={len(active_fvgs)} | M5_candles={len(candles)}")

    if not atr_m5:
        logger.warning("Data ATR M5 belum siap, skip siklus ini.")
        return

    # 7. Cek apakah ada posisi aktif berjalan yang dibuka bot
    active_positions = mt5_executor.check_active_positions()
    if len(active_positions) > 0:
        logger.info(f"ℹ️ Ada {len(active_positions)} posisi bot sedang berjalan di MT5. Menunggu posisi ditutup...")
        state["processed_bars"].add(candle_time)
        
        # Sinkronisasi tiket aktif jika ada tiket baru di MT5 yang belum terdaftar di state
        for pos in active_positions:
            if pos.ticket not in state["active_tickets"]:
                state["active_tickets"].append(pos.ticket)
                logger.info(f"Synchronized running ticket #{pos.ticket} to state.")
                
        return

    # 8. Evaluasi Aturan Entry — FVG M5
    entry_direction = None
    sl_level = 0.0
    tp_level = 0.0
    reason_msg = ""

    candle_low = latest_candle['low']
    candle_high = latest_candle['high']

    for fvg in active_fvgs:
        # Bullish FVG (BUY) — hanya jika bias bullish
        if fvg['type'] == 'bullish_fvg' and market_bias == 'bullish':
            # Entry saat candle MENYENTUH zona FVG (high/low overlap dengan zona)
            touched = candle_low <= fvg['high'] and candle_high >= fvg['low']
            if touched:
                entry_direction = 'buy'
                sl_level = fvg['low'] - max(atr_m5 * 0.5, 2.0)  # Min buffer 2.0 poin
                risk = current_price - sl_level
                tp_level = current_price + (risk * 2.0)
                reason_msg = f"Bullish FVG M5 ({fvg['low']:.2f}-{fvg['high']:.2f}, gap={fvg['gap_size']:.2f}, bias={market_bias})"
                logger.info(f"[FVG ENTRY] {reason_msg} | Entry={current_price:.2f} SL={sl_level:.2f} TP={tp_level:.2f} R:R=1:2.0")
                break
            else:
                logger.info(f"[FVG SKIP] Bullish FVG {fvg['low']:.2f}-{fvg['high']:.2f} | Harga {current_price:.2f} belum menyentuh zona")

        # Bearish FVG (SELL) — hanya jika bias bearish
        elif fvg['type'] == 'bearish_fvg' and market_bias == 'bearish':
            # Entry saat candle MENYENTUH zona FVG (high/low overlap dengan zona)
            touched = candle_low <= fvg['high'] and candle_high >= fvg['low']
            if touched:
                entry_direction = 'sell'
                sl_level = fvg['high'] + max(atr_m5 * 0.5, 2.0)  # Min buffer 2.0 poin
                risk = sl_level - current_price
                tp_level = current_price - (risk * 2.0)
                reason_msg = f"Bearish FVG M5 ({fvg['low']:.2f}-{fvg['high']:.2f}, gap={fvg['gap_size']:.2f}, bias={market_bias})"
                logger.info(f"[FVG ENTRY] {reason_msg} | Entry={current_price:.2f} SL={sl_level:.2f} TP={tp_level:.2f} R:R=1:2.0")
                break
            else:
                logger.info(f"[FVG SKIP] Bearish FVG {fvg['low']:.2f}-{fvg['high']:.2f} | Harga {current_price:.2f} belum menyentuh zona")

    # 9. Kirim order ke MetaTrader 5
    if entry_direction:
        logger.info(f"🎯 SINYAL TERDETEKSI: {entry_direction.upper()} | {reason_msg}")
        
        if state["paused"]:
            # Jika bot di-pause, hanya kirim notifikasi sinyal ke Telegram tanpa eksekusi MT5
            msg = (
                f"📡 *SINYAL TERDETEKSI (PAUSED — HANYA NOTIFIKASI)*\n\n"
                f"📈 *Arah:* {entry_direction.upper()}\n"
                f"💵 *Entry:* `{current_price:.2f}`\n"
                f"🛑 *Stop Loss:* `{sl_level:.2f}`\n"
                f"🎯 *Take Profit:* `{tp_level:.2f}`\n"
                f"💬 *Alasan:* {reason_msg}\n\n"
                f"_Bot tidak membuka posisi ke MT5 karena sedang dalam status PAUSE._"
            )
            send_telegram_notification(msg)
            logger.info(f"Sinyal {entry_direction.upper()} terdeteksi saat paused. Notifikasi terkirim.")
        else:
            order_res = mt5_executor.open_trade(
                direction=entry_direction,
                entry_price=current_price,
                sl=sl_level,
                tp=tp_level,
                reason=reason_msg
            )
            if order_res:
                logger.info("Order otomatis berhasil dipasang di MT5.")
                # Ambil position ticket (bisa .position atau .order tergantung versi MT5)
                ticket = getattr(order_res, 'position', None) or getattr(order_res, 'order', None) or getattr(order_res, 'deal', None)
                if ticket:
                    state["active_tickets"].append(ticket)
                    logger.info(f"Ticket #{ticket} ditambahkan ke active_tickets.")
        
    state["processed_bars"].add(candle_time)


# =====================================================================
# TELEGRAM BOT LISTENER (BACKGROUND PROCESS)
# =====================================================================

def telegram_polling_thread():
    """
    Fungsi loop background untuk menerima dan merespon command Telegram.
    Mendukung pesan teks biasa dan callback query dari inline keyboard.
    """
    logger.info("📨 Background Telegram Listener aktif.")
    offset = 0
    
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
            params = {"offset": offset, "timeout": 15}
            response = requests.get(url, params=params, timeout=20)
            
            if response.status_code != 200:
                time.sleep(5)
                continue
                
            updates = response.json().get("result", [])
            for update in updates:
                offset = update["update_id"] + 1
                
                # Handle callback query (tombol inline keyboard ditekan)
                callback_query = update.get("callback_query")
                if callback_query:
                    cb_chat_id = str(callback_query.get("message", {}).get("chat", {}).get("id", ""))
                    if cb_chat_id == TELEGRAM_CHAT_ID:
                        cb_data = callback_query.get("data", "")
                        cb_id = callback_query.get("id")
                        msg_id = callback_query.get("message", {}).get("message_id")
                        logger.info(f"Callback Telegram diterima: '{cb_data}'")
                        process_callback(cb_data, cb_id, msg_id)
                    continue
                
                # Handle pesan teks biasa
                message = update.get("message", {})
                chat_id = str(message.get("chat", {}).get("id", ""))
                text = message.get("text", "").strip()
                
                # Hanya tanggapi pesan dari Chat ID terdaftar
                if chat_id != TELEGRAM_CHAT_ID or not text:
                    continue
                
                logger.info(f"Pesan Telegram diterima: '{text}'")
                process_telegram_command(text)
                
        except Exception as e:
            logger.error(f"Error pada Telegram listener thread: {e}")
            time.sleep(5)
            
        time.sleep(1)


# =====================================================================
# INLINE KEYBOARD MENU SYSTEM
# =====================================================================

def build_main_menu_keyboard():
    """Membangun layout keyboard utama."""
    pause_btn = {"text": "▶️ Resume", "callback_data": "act_resume"} if state["paused"] else {"text": "⏸️ Pause", "callback_data": "act_pause"}
    
    return [
        [{"text": "📊 Status", "callback_data": "act_status"}, {"text": "💰 P&L Hari Ini", "callback_data": "act_pnl"}],
        [{"text": "🔍 Kondisi Market", "callback_data": "act_market"}, {"text": "📋 Journal", "callback_data": "act_journal"}],
        [pause_btn, {"text": "⚖️ Breakeven", "callback_data": "act_be"}],
        [{"text": "🛑 Close All", "callback_data": "confirm_close"}, {"text": "⚙️ Settings", "callback_data": "sub_settings"}],
    ]

def build_settings_keyboard():
    """Membangun layout keyboard settings."""
    return [
        [{"text": f"📦 Lot: {get_lot_size():.3f}", "callback_data": "info_lot"}, {"text": f"🛑 Loss: ${get_daily_loss_limit():.0f}", "callback_data": "info_loss"}],
        [{"text": f"⏰ Jam: {get_trading_hours()[0]:02d}:00-{get_trading_hours()[1]:02d}:00", "callback_data": "info_jam"}],
        [{"text": "🔙 Kembali", "callback_data": "back_main"}],
    ]

def send_main_menu():
    """Kirim menu utama sebagai pesan baru."""
    pause_status = "⏸️ PAUSED" if state["paused"] else "🟢 AKTIF" if is_trading_hour() else "💤 STANDBY"
    msg = (
        f"🤖 *ICT Gold Bot — Menu Utama*\n\n"
        f"📡 Status: *{pause_status}*\n"
        f"Pilih menu di bawah:"
    )
    return send_telegram_with_keyboard(msg, build_main_menu_keyboard())


def process_callback(cb_data, cb_id, msg_id):
    """
    Router untuk semua callback dari inline keyboard.
    """
    # --- Navigasi Menu ---
    if cb_data == "back_main":
        answer_callback_query(cb_id)
        pause_status = "⏸️ PAUSED" if state["paused"] else "🟢 AKTIF" if is_trading_hour() else "💤 STANDBY"
        edit_telegram_message(
            msg_id,
            f"🤖 *ICT Gold Bot — Menu Utama*\n\n📡 Status: *{pause_status}*\nPilih menu di bawah:",
            build_main_menu_keyboard()
        )
        return

    if cb_data == "sub_settings":
        answer_callback_query(cb_id)
        edit_telegram_message(
            msg_id,
            "⚙️ *SETTINGS*\n\n"
            "Pengaturan saat ini ditampilkan di tombol.\n"
            "Untuk mengubah, ketik perintah:\n\n"
            "• `/setlot 0.05` — ubah lot\n"
            "• `/setloss 15` — ubah batas rugi\n"
            "• `/setjam 8 22` — ubah jam trading",
            build_settings_keyboard()
        )
        return

    # --- Info buttons (hanya tampil notif kecil) ---
    if cb_data == "info_lot":
        answer_callback_query(cb_id, f"Lot saat ini: {get_lot_size():.3f}. Ketik /setlot untuk ubah.")
        return
    if cb_data == "info_loss":
        answer_callback_query(cb_id, f"Loss limit: ${get_daily_loss_limit():.2f}. Ketik /setloss untuk ubah.")
        return
    if cb_data == "info_jam":
        s, e = get_trading_hours()
        answer_callback_query(cb_id, f"Jam trading: {s:02d}:00-{e:02d}:00 WIB. Ketik /setjam untuk ubah.")
        return

    # --- Action buttons ---
    if cb_data == "act_status":
        answer_callback_query(cb_id, "📊 Mengambil status...")
        process_telegram_command("/status")
        return

    if cb_data == "act_pnl":
        answer_callback_query(cb_id, "💰 Menghitung P&L...")
        handle_interactive_question("profit hari ini")
        return

    if cb_data == "act_market":
        answer_callback_query(cb_id, "🔍 Menganalisis market...")
        answer_market_condition()
        return

    if cb_data == "act_journal":
        answer_callback_query(cb_id, "📋 Mengambil jurnal...")
        process_telegram_command("/journal")
        return

    if cb_data == "act_be":
        answer_callback_query(cb_id, "⚖️ Memproses breakeven...")
        process_telegram_command("/be")
        return

    if cb_data == "act_pause":
        answer_callback_query(cb_id, "⏸️ Bot di-pause!")
        state["paused"] = True
        logger.info("Bot di-PAUSE via menu Telegram.")
        edit_telegram_message(
            msg_id,
            "⏸️ *BOT TRADING DI-PAUSE!*\n\n"
            "🔹 Eksekusi MT5: *DIHENTIKAN*\n"
            "🔹 Notifikasi Sinyal: *AKTIF (Hanya Kirim Chat)*\n"
            "🔹 Posisi Aktif & Profit Lock: *TETAP JALAN*",
            build_main_menu_keyboard()
        )
        return

    if cb_data == "act_resume":
        answer_callback_query(cb_id, "▶️ Bot dilanjutkan!")
        state["paused"] = False
        logger.info("Bot di-RESUME via menu Telegram.")
        edit_telegram_message(
            msg_id,
            "▶️ *BOT TRADING DILANJUTKAN!*\n\n"
            "🟢 Entry baru: *AKTIF*\n"
            "🟢 Scanning sinyal FVG M5 kembali berjalan.",
            build_main_menu_keyboard()
        )
        return

    # --- Close dengan konfirmasi ---
    if cb_data == "confirm_close":
        active_pos = mt5_executor.check_active_positions()
        if not active_pos:
            answer_callback_query(cb_id, "Tidak ada posisi aktif.")
            return
        answer_callback_query(cb_id)
        edit_telegram_message(
            msg_id,
            f"⚠️ *KONFIRMASI CLOSE ALL*\n\n"
            f"Ada *{len(active_pos)}* posisi aktif.\n"
            f"Yakin ingin menutup semua posisi?",
            [
                [{"text": "✅ Ya, Tutup Semua", "callback_data": "do_close"}, {"text": "❌ Batal", "callback_data": "back_main"}]
            ]
        )
        return

    if cb_data == "do_close":
        answer_callback_query(cb_id, "🛑 Menutup posisi...")
        edit_telegram_message(msg_id, "⏳ *Menutup semua posisi...*", None)
        process_telegram_command("/close")
        return

    # Fallback
    answer_callback_query(cb_id, "Perintah tidak dikenal.")


def process_telegram_command(text):
    """
    Memproses dan merespon command dari pengguna.
    """
    parts = text.split()
    command = parts[0].lower()
    
    if command == "/help" or command == "/start" or command == "/menu":
        send_main_menu()
        return

    if command == "/help_text":
        help_msg = (
            "🤖 *Menu Perintah ICT Gold Bot:*\n\n"
            "*📋 Perintah:*\n"
            "💬 `/menu` - Menu interaktif (tombol)\n"
            "💬 `/status` - Info live, modal, status bot\n"
            "💬 `/pause` - Pause entry baru\n"
            "💬 `/resume` - Resume trading\n"
            "💬 `/setlot <angka>` - Setel lot trading\n"
            "💬 `/setloss <angka>` - Setel batas rugi harian\n"
            "💬 `/setjam <mulai> <selesai>` - Atur jam trading\n"
            "💬 `/journal` - 5 transaksi terakhir\n"
            "💬 `/close` - Tutup manual semua posisi\n"
            "💬 `/help` - Menu ini\n\n"
            "*💡 Pertanyaan Interaktif (ketik langsung):*\n"
            "• _kondisi market?_\n"
            "• _profit hari ini?_\n"
            "• _harga sekarang?_"
        )
        send_telegram_notification(help_msg)
    
    elif command == "/status":
        # Ambil status akun MT5
        account_info = None
        if mt5_executor.initialize_mt5():
            account_info = mt5_executor.mt5.account_info()
            
        balance = f"${account_info.balance:.2f}" if account_info else "N/A"
        equity = f"${account_info.equity:.2f}" if account_info else "N/A"
        
        # Cek jam aktif & pause
        if state["paused"]:
            trading_status = "⏸️ PAUSED"
        elif is_trading_hour():
            trading_status = "🟢 AKTIF"
        else:
            trading_status = "💤 STANDBY"
        
        start_h, end_h = get_trading_hours()
        status_msg = (
            f"📊 *STATUS LIVE BOT ICT FVG:*\n\n"
            f"👤 *Akun Broker:* {account_info.login if account_info else 'N/A'}\n"
            f"💰 *Balance:* {balance}\n"
            f"💵 *Equity:* {equity}\n"
            f"⚙️ *Lot Size Saat Ini:* `{get_lot_size():.3f} lot`\n"
            f"🛑 *Batas Daily Loss:* ${get_daily_loss_limit():.2f}\n"
            f"📉 *Total Loss Hari Ini:* ${state['daily_loss']}\n"
            f"⏱️ *Status Trading:* {trading_status} ({start_h:02d}:00 - {end_h:02d}:00 WIB)"
        )
        send_telegram_notification(status_msg)
        
    elif command == "/pause":
        if state["paused"]:
            send_telegram_notification("⏸️ Bot sudah dalam status *PAUSED*. Ketik `/resume` untuk melanjutkan.")
        else:
            state["paused"] = True
            logger.info("Bot di-PAUSE via Telegram.")
            send_telegram_notification(
                "⏸️ *BOT TRADING DI-PAUSE!*\n\n"
                "🔹 Eksekusi MT5: *DIHENTIKAN*\n"
                "🔹 Notifikasi Sinyal: *AKTIF (Hanya Kirim Chat)*\n"
                "🔹 Posisi Aktif & Profit Lock: *TETAP JALAN*\n\n"
                "Ketik `/resume` untuk melanjutkan trading."
            )

    elif command == "/resume":
        if not state["paused"]:
            send_telegram_notification("🟢 Bot sudah dalam status *AKTIF*. Tidak perlu resume.")
        else:
            state["paused"] = False
            logger.info("Bot di-RESUME via Telegram.")
            send_telegram_notification(
                "▶️ *BOT TRADING DILANJUTKAN!*\n\n"
                "🟢 Entry baru: *AKTIF*\n"
                "🟢 Scanning sinyal FVG M5 kembali berjalan."
            )

    elif command == "/pnl":
        if not mt5_executor.initialize_mt5():
            send_telegram_notification("❌ Gagal terhubung ke MT5.")
            return
        
        from config import MT5_MAGIC_NUMBER
        wib_now = datetime.now(timezone.utc) + timedelta(hours=7)
        date_str = wib_now.strftime('%Y-%m-%d')
        
        start_date = datetime.now() - timedelta(days=1)
        end_date = datetime.now() + timedelta(days=1)
        deals = mt5_executor.mt5.history_deals_get(start_date, end_date)
        
        if not deals:
            send_telegram_notification("📂 *P&L Hari Ini:* Belum ada transaksi.")
            return
        
        # Filter deal close hari ini dari bot
        wins, losses, total_profit = 0, 0, 0.0
        for d in deals:
            if d.entry == 1 and d.magic == MT5_MAGIC_NUMBER:
                deal_time = datetime.fromtimestamp(d.time) - timedelta(hours=3)
                if deal_time.strftime('%Y-%m-%d') == date_str:
                    pnl = d.profit + d.swap + d.commission
                    total_profit += pnl
                    if pnl >= 0:
                        wins += 1
                    else:
                        losses += 1
        
        total_trades = wins + losses
        if total_trades == 0:
            send_telegram_notification("📂 *P&L Hari Ini:* Belum ada trade yang ditutup hari ini.")
            return
        
        winrate = (wins / total_trades * 100) if total_trades > 0 else 0
        profit_emoji = "🟢" if total_profit >= 0 else "🔴"
        sign = "+" if total_profit >= 0 else ""
        
        # Posisi aktif saat ini
        active_pos = mt5_executor.check_active_positions()
        floating = sum(p.profit + p.swap + p.commission for p in active_pos) if active_pos else 0.0
        floating_str = f"+${floating:.2f}" if floating >= 0 else f"-${abs(floating):.2f}"
        
        msg = (
            f"💰 *P&L HARI INI ({date_str}):*\n\n"
            f"📊 *Total Trade:* {total_trades}\n"
            f"🟢 *Win:* {wins} | 🔴 *Loss:* {losses}\n"
            f"🎯 *Win Rate:* {winrate:.0f}%\n\n"
            f"{profit_emoji} *Net P&L:* `{sign}${total_profit:.2f}`\n"
            f"📈 *Floating:* `{floating_str}` ({len(active_pos)} posisi aktif)"
        )
        send_telegram_notification(msg)

    elif command == "/be":
        active_pos = mt5_executor.check_active_positions()
        
        if not active_pos:
            send_telegram_notification("📂 *Tidak ada posisi aktif* untuk di-breakeven.")
            return
        
        success_count = 0
        for pos in active_pos:
            direction = "BUY" if pos.type == 0 else "SELL"
            entry_price = pos.price_open
            current_price = pos.price_current
            
            # Cek apakah posisi sudah profit (layak BE)
            is_profit = (current_price > entry_price) if pos.type == 0 else (current_price < entry_price)
            
            if not is_profit:
                pnl = pos.profit + pos.swap + pos.commission
                send_telegram_notification(
                    f"⚠️ Posisi #{pos.ticket} ({direction}) belum profit.\n"
                    f"Entry: {entry_price} | Now: {current_price} | P/L: ${pnl:.2f}\n"
                    f"BE hanya bisa dilakukan saat posisi sudah profit."
                )
                continue
            
            # SL sudah di BE atau lebih baik?
            if pos.type == 0 and pos.sl >= entry_price:  # BUY
                send_telegram_notification(f"ℹ️ Posisi #{pos.ticket} ({direction}) SL sudah di BE atau lebih baik ({pos.sl}).")
                continue
            elif pos.type == 1 and pos.sl > 0 and pos.sl <= entry_price:  # SELL
                send_telegram_notification(f"ℹ️ Posisi #{pos.ticket} ({direction}) SL sudah di BE atau lebih baik ({pos.sl}).")
                continue
            
            # Geser SL ke entry price (breakeven)
            if mt5_executor.modify_sl(pos, entry_price):
                success_count += 1
                pnl = pos.profit + pos.swap + pos.commission
                send_telegram_notification(
                    f"⚖️ *BREAKEVEN BERHASIL!*\n\n"
                    f"🆔 *Tiket:* #{pos.ticket}\n"
                    f"📈 *Arah:* {direction}\n"
                    f"💵 *Entry:* {entry_price}\n"
                    f"🛑 *SL Lama:* {pos.sl}\n"
                    f"✅ *SL Baru:* {entry_price} (BE)\n"
                    f"📊 *Floating P/L:* ${pnl:.2f}"
                )
            else:
                send_telegram_notification(f"❌ Gagal mengubah SL posisi #{pos.ticket}. Cek MT5.")
        
        if success_count == 0 and active_pos:
            logger.info("Tidak ada posisi yang bisa di-breakeven.")

    elif command == "/setlot":
        if len(parts) < 2:
            send_telegram_notification("⚠️ *Format salah.* Gunakan: `/setlot <ukuran_lot>`\n_Contoh: /setlot 0.02_")
            return
            
        try:
            new_lot = float(parts[1])
            if new_lot <= 0.0 or new_lot > 1.0:
                send_telegram_notification("⚠️ *Lot tidak valid.* Lot harus berupa angka desimal positif antara `0.001` hingga `1.0`.")
                return
                
            if save_lot_size(new_lot):
                send_telegram_notification(f"✅ *Lot trading berhasil diubah!*\n⚙️ *Lot Baru:* `{new_lot:.3f} lot`.")
                logger.info(f"Lot trading diubah ke: {new_lot}")
            else:
                send_telegram_notification("❌ Gagal menyimpan setelan lot baru.")
        except ValueError:
            send_telegram_notification("⚠️ *Format salah.* Lot harus berupa angka desimal.\n_Contoh: /setlot 0.02_")

    elif command == "/setloss":
        if len(parts) < 2:
            send_telegram_notification("⚠️ *Format salah.* Gunakan: `/setloss <batas_rugi_usd>`\n_Contoh: /setloss 15.0_")
            return
            
        try:
            new_limit = float(parts[1])
            if new_limit <= 0.0:
                send_telegram_notification("⚠️ *Batas rugi tidak valid.* Harus berupa angka positif.")
                return
                
            if save_daily_loss_limit(new_limit):
                send_telegram_notification(f"✅ *Daily Loss Limit berhasil diubah!*\n🛑 *Batas Rugi Baru:* `${new_limit:.2f}`.")
                logger.info(f"Daily loss limit diubah ke: {new_limit}")
            else:
                send_telegram_notification("❌ Gagal menyimpan setelan batas rugi baru.")
        except ValueError:
            send_telegram_notification("⚠️ *Format salah.* Harus berupa angka desimal.\n_Contoh: /setloss 15.0_")

    elif command == "/setjam":
        if not parts or len(parts) < 2:
            start_h, end_h = get_trading_hours()
            send_telegram_notification(
                f"⏰ *JAM TRADING SAAT INI:*\n"
                f"▪️ Mulai: `{start_h:02d}:00` WIB\n"
                f"▪️ Selesai: `{end_h:02d}:00` WIB\n\n"
                f"_Untuk mengubah, ketik:_\n"
                f"`/setjam [mulai] [selesai]`\n"
                f"_Contoh: /setjam 7 22_"
            )
            return
        try:
            new_start = int(parts[1])
            new_end = int(parts[2]) if len(parts) > 2 else get_trading_hours()[1]
            if new_start < 0 or new_start > 23 or new_end < 0 or new_end > 23:
                send_telegram_notification("⚠️ *Jam tidak valid.* Harus antara 0-23.")
                return
            if new_start >= new_end:
                send_telegram_notification("⚠️ *Jam mulai harus lebih kecil dari jam selesai.*")
                return
            if save_trading_hours(new_start, new_end):
                send_telegram_notification(
                    f"✅ *Jam Trading berhasil diubah!*\n"
                    f"⏰ *Mulai:* `{new_start:02d}:00` WIB\n"
                    f"⏰ *Selesai:* `{new_end:02d}:00` WIB"
                )
                logger.info(f"Jam trading diubah ke: {new_start:02d}:00 - {new_end:02d}:00 WIB")
            else:
                send_telegram_notification("❌ Gagal menyimpan jam trading baru.")
        except (ValueError, IndexError):
            send_telegram_notification("⚠️ *Format salah.*\n_Contoh: /setjam 7 22_")

    elif command == "/journal":
        if not mt5_executor.initialize_mt5():
            send_telegram_notification("❌ Gagal terhubung ke MT5 untuk membaca jurnal.")
            return
            
        # Ambil transaksi 3 hari terakhir
        from datetime import datetime
        from config import MT5_MAGIC_NUMBER
        start_date = datetime.now() - timedelta(days=3)
        end_date = datetime.now() + timedelta(days=1)
        deals = mt5_executor.mt5.history_deals_get(start_date, end_date)
        
        if not deals:
            send_telegram_notification("📂 *Jurnal Kosong:* Tidak ada transaksi tercatat dalam 3 hari terakhir.")
            return
        
        # Filter: hanya deal CLOSE (entry==1) dari bot ini (magic number)
        closed_deals = [d for d in deals if d.entry == 1 and d.magic == MT5_MAGIC_NUMBER]
        
        if not closed_deals:
            send_telegram_notification("📂 *Jurnal Kosong:* Belum ada trade dari bot XAUGOLD 3 dalam 3 hari terakhir.")
            return
            
        # Ambil 5 deal terakhir
        closed_deals = list(closed_deals)[-5:]
        closed_deals.reverse() # Urutkan dari yang paling baru
        
        journal_text = "📋 *JURNAL TRADE BOT (5 Terakhir):*\n\n"
        for d in closed_deals:
            deal_time = datetime.fromtimestamp(d.time) - timedelta(hours=3)
            time_str = deal_time.strftime('%d/%m %H:%M WIB')
            
            # Arah posisi: deal OUT berlawanan dengan posisi asal
            pos_direction = "BUY" if d.type == 1 else "SELL"
            
            profit = d.profit + d.swap + d.commission
            profit_str = f"+${profit:.2f} 🟢" if profit > 0 else (f"-${abs(profit):.2f} 🔴" if profit < 0 else "$0.00 ⚪")
            
            # Alasan close
            reason = "Manual ⚪"
            if d.reason == 4:
                reason = "SL 🔴"
            elif d.reason == 5:
                reason = "TP 🟢"
            
            journal_text += (
                f"⏱️ *{time_str}*\n"
                f"▪️ *{pos_direction}* {d.volume:.2f} lot | Exit: {d.price}\n"
                f"▪️ {reason} | *P/L:* {profit_str}\n"
                f"-----------------------------------\n"
            )
            
        send_telegram_notification(journal_text)

    elif command == "/testtrade":
        send_telegram_notification("⏳ *Memulai tes eksekusi order otomatis ke MT5...*")
        
        if not mt5_executor.initialize_mt5():
            send_telegram_notification("❌ *Tes Gagal:* Tidak dapat terhubung ke terminal MT5. Pastikan MT5 Anda menyala.")
            return
            
        # Ambil harga ask live untuk XAUUSD
        symbol_info = mt5_executor.get_symbol_info()
        if not symbol_info:
            send_telegram_notification(f"❌ *Tes Gagal:* Simbol {MT5_SYMBOL} tidak aktif di MT5.")
            return
            
        tick = mt5_executor.mt5.symbol_info_tick(MT5_SYMBOL)
        if not tick:
            send_telegram_notification("❌ *Tes Gagal:* Gagal membaca harga live.")
            return
            
        # Kirim sinyal order BUY kecil
        price = tick.ask
        sl = price - 2.0  # SL $2 di bawah entry
        tp = price + 3.0  # TP $3 di atas entry
        
        send_telegram_notification(f"📝 Mengirim order BUY 0.01 lot pada harga {price}...")
        order_res = mt5_executor.open_trade(
            direction="buy",
            entry_price=price,
            sl=sl,
            tp=tp,
            reason="Uji coba Telegram Manual"
        )
        
        if order_res:
            send_telegram_notification("✅ *Tes Berhasil:* Bot terbukti bisa aktif otomatis mengirimkan order ke MT5 dengan sukses!")
        else:
            send_telegram_notification("❌ *Tes Gagal:* Order ditolak oleh MT5/Broker. Periksa tab Journal di MT5 Anda untuk melihat alasannya.")

    elif command == "/sharecard":
        send_telegram_notification("⏳ *Generating PnL card...*")
        
        # Parse tanggal opsional: /sharecard atau /sharecard 2026-06-03
        target_date = None
        if len(parts) >= 2:
            try:
                target_date = datetime.strptime(parts[1], '%Y-%m-%d').date()
            except ValueError:
                send_telegram_notification("⚠️ *Format tanggal salah.* Gunakan: `/sharecard YYYY-MM-DD`\n_Contoh: /sharecard 2026-06-03_")
                return
        
        try:
            png_data = generate_card_for_date(target_date=target_date)
            if png_data:
                wib_now = datetime.now(timezone.utc) + timedelta(hours=7)
                date_label = target_date.strftime('%d %B %Y') if target_date else wib_now.strftime('%d %B %Y')
                send_telegram_photo(png_data, caption=f"📊 *PnL Card — {date_label}*")
            else:
                send_telegram_notification("❌ Gagal generate PnL card. Pastikan MT5 terhubung.")
        except Exception as e:
            logger.error(f"Error generating PnL card: {e}")
            send_telegram_notification(f"❌ Error: {e}")

    elif command == "/web":
        send_telegram_notification(
            "🌐 *PnL Dashboard*\n\n"
            "Buka di browser:\n"
            "`http://localhost:5000`\n\n"
            "_Dashboard menampilkan PnL Calendar, summary, dan fitur Share Card._"
        )

    elif command == "/close":
        send_telegram_notification("⏳ *Memeriksa posisi aktif untuk ditutup...*")
        active_pos = mt5_executor.check_active_positions()
        
        if not active_pos:
            send_telegram_notification("📂 *Tidak ada posisi aktif* dari bot yang sedang berjalan saat ini.")
            return

        success_count = 0
        for pos in active_pos:
            direction = "BUY" if pos.type == 0 else "SELL"
            logger.info(f"Telegram manual close request untuk posisi #{pos.ticket}")
            if mt5_executor.close_position(pos):
                success_count += 1
                # Hapus tiket posisi dari state active jika ada
                if pos.ticket in state["active_tickets"]:
                    state["active_tickets"].remove(pos.ticket)
                
                # Kirim notifikasi konfirmasi khusus
                profit = pos.profit + pos.swap + pos.commission
                profit_str = f"+${profit:.2f} 🟢" if profit > 0 else (f"-${abs(profit):.2f} 🔴" if profit < 0 else "$0.00 ⚪")
                send_telegram_notification(
                    f"🛑 *POSISI BERHASIL DITUTUP SECARA MANUAL!*\n\n"
                    f"🆔 *Position ID:* #{pos.ticket}\n"
                    f"📈 *Arah:* {direction}\n"
                    f"💰 *Lot:* {pos.volume:.2f}\n"
                    f"💵 *Harga Entry:* {pos.price_open}\n"
                    f"💵 *Harga Close:* {pos.price_current}\n"
                    f"📊 *Hasil P/L:* {profit_str}"
                )
            else:
                send_telegram_notification(f"❌ *Gagal menutup posisi* #{pos.ticket}. Periksa journal MT5.")

        if success_count > 0:
            # Perbarui loss harian
            update_daily_losses()
        
    else:
        # Pertanyaan interaktif (non-command)
        if not text.startswith("/"):
            if not handle_interactive_question(text):
                send_telegram_notification(
                    "🤔 Maaf, saya tidak mengerti pertanyaan Anda.\n\n"
                    "💡 *Contoh pertanyaan:*\n"
                    "• _kondisi market?_\n"
                    "• _order block dimana?_\n"
                    "• _kapan bisa entry?_\n"
                    "• _profit hari ini?_\n"
                    "• _harga sekarang?_\n\n"
                    "Atau ketik /help untuk daftar perintah."
                )
        else:
            send_telegram_notification(f"⚠️ Perintah `{command}` tidak dikenal. Ketik /help untuk bantuan.")

# =====================================================================
# TELEGRAM INTERACTIVE HANDLER (RULE-BASED, TANPA LLM)
# =====================================================================

def get_live_market_data():
    """Helper: Ambil data pasar terkini dan analisis ICT M5 (FVG + bias)."""
    try:
        data = fetch_xauusd_data(symbol="FOREXCOM:XAUUSD", timeframe="5", limit=500, range_val=500)
        if 'error' in data or not data.get('candles'):
            return None
        candles = data['candles']
        latest = candles[-1]
        
        # M5 analysis
        m5_bias = 'neutral'
        active_fvgs = []
        if len(candles) >= 30:
            smc_m5 = analyze_smc(candles)
            m5_bias = smc_m5.get('market_bias', 'neutral')
            active_fvgs = smc_m5.get('active_fvgs', [])
        
        # ATR M5
        atr_m5 = latest.get('atr_14')
        if not atr_m5 and len(candles) >= 14:
            recent_ranges = [c['high'] - c['low'] for c in candles[-14:]]
            atr_m5 = sum(recent_ranges) / len(recent_ranges)
        
        return {
            "price": latest['close'],
            "rsi": latest.get('rsi_14'),
            "ema_200": latest.get('ema_200'),
            "atr_m5": atr_m5,
            "bias": m5_bias,
            "active_fvgs": active_fvgs,
        }
    except Exception as e:
        logger.error(f"Error fetching market data for interactive: {e}")
        return None


def answer_market_condition():
    """Jawab pertanyaan tentang kondisi market saat ini."""
    send_telegram_notification("⏳ Mengambil data pasar terkini...")
    market = get_live_market_data()
    if not market:
        send_telegram_notification("❌ Gagal mengambil data pasar dari TradingView.")
        return

    price, rsi, ema, bias = market["price"], market["rsi"], market["ema_200"], market["bias"]
    atr_m5 = market.get("atr_m5")
    bias_icon = "🟢" if bias == "bullish" else "🔴" if bias == "bearish" else "⚪"

    rsi_status = "N/A"
    if rsi:
        rsi_status = "⚠️ Overbought" if rsi > 70 else ("⚠️ Oversold" if rsi < 30 else "✅ Normal")

    ema_status = f"Harga {'DI ATAS' if price > ema else 'DI BAWAH'} EMA 200 ({ema:.2f})" if ema else "N/A"

    fvgs = market["active_fvgs"]
    fvg_details = ""
    for fvg in fvgs:
        fvg_type = "🟢 Bullish" if fvg['type'] == 'bullish_fvg' else "🔴 Bearish"
        dist = abs(price - (fvg['high'] + fvg['low']) / 2)
        fvg_details += f"\n   {fvg_type}: {fvg['low']:.2f} - {fvg['high']:.2f} (gap={fvg['gap_size']:.2f}, jarak={dist:.2f})"

    atr_line = f"📏 *ATR M5:* {atr_m5:.2f}\n" if atr_m5 else ""

    msg = (
        f"📊 *KONDISI MARKET XAUUSD:*\n\n"
        f"💰 *Harga:* {price:.2f}\n"
        f"{bias_icon} *Market Bias (M5):* {bias.upper()}\n"
        f"{atr_line}"
        f"📊 *RSI(14):* {rsi:.2f} ({rsi_status})\n"
        f"📈 *EMA 200:* {ema_status}\n\n"
        f"🟦 *FVG Aktif (M5):* {len(fvgs)}{fvg_details}"
    )
    send_telegram_notification(msg)


def answer_order_blocks():
    """Jawab pertanyaan tentang zona FVG aktif."""
    send_telegram_notification("⏳ Menganalisis FVG M5...")
    market = get_live_market_data()
    if not market:
        send_telegram_notification("❌ Gagal mengambil data pasar.")
        return

    fvgs, price = market["active_fvgs"], market["price"]
    if not fvgs:
        send_telegram_notification(
            f"🟦 *FVG AKTIF (M5):*\n\n"
            f"💰 Harga saat ini: {price:.2f}\n"
            f"⚪ Tidak ada FVG aktif. Bot menunggu FVG baru terbentuk."
        )
        return

    msg = f"🟦 *FVG AKTIF (M5):*\n\n💰 Harga saat ini: *{price:.2f}*\n"
    for i, fvg in enumerate(fvgs):
        fvg_type = "🟢 Bullish FVG" if fvg['type'] == 'bullish_fvg' else "🔴 Bearish FVG"
        mid = (fvg['high'] + fvg['low']) / 2
        dist = abs(price - mid)

        if fvg['type'] == 'bullish_fvg':
            action = "Harga di zona FVG!" if fvg['low'] <= price <= fvg['high'] else f"Harga perlu TURUN {price - fvg['high']:.2f}" if price > fvg['high'] else "Harga di bawah zona"
        else:
            action = "Harga di zona FVG!" if fvg['low'] <= price <= fvg['high'] else f"Harga perlu NAIK {fvg['low'] - price:.2f}" if price < fvg['low'] else "Harga di atas zona"

        msg += (
            f"\n{fvg_type} #{i+1}:\n"
            f"   📍 Zona: {fvg['low']:.2f} - {fvg['high']:.2f}\n"
            f"   📏 Gap: {fvg['gap_size']:.2f}\n"
            f"   📏 Jarak: {dist:.2f}\n"
            f"   💡 {action}\n"
        )
    send_telegram_notification(msg)


def answer_entry_conditions():
    """Jawab pertanyaan kapan/kenapa bot belum entry."""
    send_telegram_notification("⏳ Menganalisis kondisi entry...")
    market = get_live_market_data()
    if not market:
        send_telegram_notification("❌ Gagal mengambil data pasar.")
        return

    price, ema, rsi, bias = market["price"], market["ema_200"], market["rsi"], market["bias"]
    blockers, opportunities = [], []

    # Jam trading
    s_h, e_h = get_trading_hours()
    if not is_trading_hour():
        blockers.append(f"⏰ Di luar jam trading ({s_h:02d}:00-{e_h:02d}:00 WIB)")
    else:
        opportunities.append(f"✅ Dalam jam trading aktif ({s_h:02d}:00-{e_h:02d}:00)")

    # Daily loss limit
    daily_limit = get_daily_loss_limit()
    if state["daily_loss"] >= daily_limit:
        blockers.append(f"🛑 Batas rugi harian tercapai (${state['daily_loss']:.2f} / ${daily_limit:.2f})")

    # Posisi aktif
    active_pos = mt5_executor.check_active_positions()
    if len(active_pos) > 0:
        blockers.append(f"⏳ Ada {len(active_pos)} posisi aktif berjalan")

    # FVG analysis
    fvgs = market.get("active_fvgs", [])
    if not fvgs:
        blockers.append("🟦 Tidak ada FVG M5 aktif")
    else:
        for fvg in fvgs:
            if fvg['type'] == 'bullish_fvg':
                near = fvg['low'] <= price <= fvg['high']
                ok_bias = bias == 'bullish'
                if near and ok_bias:
                    opportunities.append(f"🟢 BUY siap! FVG {fvg['low']:.2f}-{fvg['high']:.2f}")
                else:
                    if not near:
                        blockers.append(f"📏 Harga belum di Bullish FVG ({fvg['low']:.2f}-{fvg['high']:.2f})")
                    if not ok_bias:
                        blockers.append(f"🔴 Bias {bias} → BUY tidak diizinkan")
            elif fvg['type'] == 'bearish_fvg':
                near = fvg['low'] <= price <= fvg['high']
                ok_bias = bias == 'bearish'
                if near and ok_bias:
                    opportunities.append(f"🔴 SELL siap! FVG {fvg['low']:.2f}-{fvg['high']:.2f}")
                else:
                    if not near:
                        blockers.append(f"📏 Harga belum di Bearish FVG ({fvg['low']:.2f}-{fvg['high']:.2f})")
                    if not ok_bias:
                        blockers.append(f"🟢 Bias {bias} → SELL tidak diizinkan")

    msg = f"🔍 *ANALISIS KONDISI ENTRY:*\n\n💰 Harga: *{price:.2f}*\n"
    if opportunities:
        msg += "\n*✅ Peluang:*\n"
        for o in opportunities:
            msg += f"   {o}\n"
    if blockers:
        msg += "\n*❌ Penghalang:*\n"
        for b in blockers:
            msg += f"   {b}\n"
    if not blockers and opportunities:
        msg += "\n💡 *Bot siap entry pada siklus scan berikutnya!*"
    elif blockers:
        msg += "\n💡 *Bot menunggu semua penghalang teratasi.*"
    send_telegram_notification(msg)


def answer_profit_today():
    """Jawab pertanyaan tentang profit/loss hari ini."""
    if not mt5_executor.initialize_mt5():
        send_telegram_notification("❌ Gagal terhubung ke MT5.")
        return

    wib_now = datetime.now(timezone.utc) + timedelta(hours=7)
    date_str = wib_now.strftime('%Y-%m-%d')
    start_date = datetime.now() - timedelta(days=1)
    deals = mt5_executor.mt5.history_deals_get(start_date, datetime.now() + timedelta(days=1))

    if not deals:
        send_telegram_notification("📂 Tidak ada transaksi tercatat hari ini.")
        return

    total_profit, total_loss, win_count, loss_count = 0.0, 0.0, 0, 0
    for d in deals:
        if d.entry == 1:
            deal_time = datetime.fromtimestamp(d.time) - timedelta(hours=3)
            if deal_time.strftime('%Y-%m-%d') == date_str:
                pnl = d.profit + d.swap + d.commission
                if pnl > 0:
                    total_profit += pnl
                    win_count += 1
                elif pnl < 0:
                    total_loss += abs(pnl)
                    loss_count += 1

    net = total_profit - total_loss
    total_trades = win_count + loss_count
    wr = (win_count / total_trades * 100) if total_trades > 0 else 0
    net_icon = "📈" if net >= 0 else "📉"

    msg = (
        f"💰 *RINGKASAN P/L HARI INI ({date_str}):*\n\n"
        f"{net_icon} *Net P/L:* {'+'if net>=0 else ''}${net:.2f}\n"
        f"🟢 *Total Profit:* +${total_profit:.2f} ({win_count} trade)\n"
        f"🔴 *Total Loss:* -${total_loss:.2f} ({loss_count} trade)\n"
        f"📊 *Win Rate:* {wr:.1f}% ({win_count}/{total_trades})\n"
        f"🛑 *Akumulasi Loss:* ${state['daily_loss']:.2f} / ${get_daily_loss_limit():.2f}"
    )
    send_telegram_notification(msg)


def answer_current_price():
    """Jawab pertanyaan tentang harga saat ini."""
    market = get_live_market_data()
    if not market:
        send_telegram_notification("❌ Gagal mengambil data harga.")
        return

    price, ema, rsi, atr, bias = market["price"], market["ema_200"], market["rsi"], market["atr"], market["bias"]
    bias_icon = "🟢" if bias == "bullish" else "🔴" if bias == "bearish" else "⚪"
    ema_pos = "di atas" if ema and price > ema else "di bawah"

    msg = (
        f"💰 *HARGA XAUUSD SAAT INI:*\n\n"
        f"💵 *Harga:* {price:.2f}\n"
        f"{bias_icon} *Bias:* {bias.upper()}\n"
        f"📈 *EMA 200:* {ema:.2f} (harga {ema_pos})\n"
        f"📊 *RSI:* {rsi:.2f}\n"
        f"📏 *ATR:* {atr:.2f}"
    )
    send_telegram_notification(msg)


def handle_interactive_question(text):
    """Router utama pertanyaan interaktif. Return True jika dikenali."""
    t = text.lower().strip()

    if any(kw in t for kw in ["kondisi", "market", "analisis", "analisa", "gimana pasar", "bagaimana pasar"]):
        answer_market_condition()
        return True
    if any(kw in t for kw in ["order block", "ob ", "zona ob", "ob?", "blok"]):
        answer_order_blocks()
        return True
    if any(kw in t for kw in ["kapan", "entry", "kenapa belum", "kenapa tidak", "kenapa engga", "bisa sell", "bisa buy", "ambil sell", "ambil buy"]):
        answer_entry_conditions()
        return True
    if any(kw in t for kw in ["profit", "loss", "rugi", "untung", "pnl", "hasil hari"]):
        answer_profit_today()
        return True
    if any(kw in t for kw in ["harga", "price", "berapa sekarang"]):
        answer_current_price()
        return True
    if any(kw in t for kw in ["close", "tutup", "exit", "selesai", "cut loss", "cutloss", "matikan"]):
        process_telegram_command("/close")
        return True
    return False


def main():
    logger.info("=========================================================")
    logger.info("🚀 MEMULAI AUTO-TRADING BOT XAUUSD ICT FVG (MT5)")
    logger.info("=========================================================")
    
    # Jalankan PnL Dashboard web server di background thread
    try:
        from pnl_server import run_server
        flask_thread = threading.Thread(target=run_server, daemon=True)
        flask_thread.start()
        logger.info("🌐 PnL Dashboard thread started on http://localhost:5000")
    except Exception as e:
        logger.warning(f"⚠️ PnL Dashboard gagal dimulai: {e}")

    # Jalankan background thread listener Telegram lebih dulu (bisa terima command walau MT5 belum nyala)
    listener_thread = threading.Thread(target=telegram_polling_thread, daemon=True)
    listener_thread.start()

    # Jalankan Profit Lock thread — scan tiap 1 detik (independent dari loop utama)
    pl_thread = threading.Thread(target=profit_lock_thread, daemon=True)
    pl_thread.start()

    # Retry loop: tunggu MT5 siap (untuk PM2 auto-start saat boot)
    mt5_retry_interval = 30  # detik
    mt5_connected = False
    while not mt5_connected:
        if mt5_executor.initialize_mt5():
            mt5_connected = True
            logger.info("✅ Koneksi MT5 berhasil!")
        else:
            logger.warning(f"⏳ MT5 belum siap. Retry dalam {mt5_retry_interval} detik... (Pastikan MetaTrader 5 sudah menyala)")
            send_telegram_notification(f"⏳ *Bot menunggu MetaTrader 5...*\nRetry dalam {mt5_retry_interval} detik.")
            time.sleep(mt5_retry_interval)

    # Ambil nilai awal
    current_lot = get_lot_size()
    current_loss_limit = get_daily_loss_limit()

    # Kirim notifikasi bot aktif ke Telegram
    wib_start = datetime.now(timezone.utc) + timedelta(hours=7)
    send_telegram_notification(
        f"🤖 *Auto-Trading ICT FVG Bot Aktif!*\n"
        f"🕒 *Waktu Mulai:* {wib_start.strftime('%d-%m-%Y %H:%M:%S WIB')}\n"
        f"💰 *Modal Terdeteksi:* ${mt5_executor.mt5.account_info().balance if mt5_executor.mt5.account_info() else 'N/A'}\n"
        f"⚙️ *Lot Size:* `{current_lot:.3f} lot`\n"
        f"⚙️ *Daily Loss Limit:* `${current_loss_limit:.2f}`"
    )

    # Loop scanner tak terbatas
    while True:
        try:
            run_trading_cycle()
        except KeyboardInterrupt:
            logger.info("👋 Bot dihentikan secara manual.")
            send_telegram_notification("⚠️ *ICT Gold Bot dimatikan secara manual.*")
            break
        except Exception as e:
            logger.exception(f"Error tidak terduga pada trading loop: {e}")
            
        # Scan setiap 15 detik untuk akurasi data candle 1M
        time.sleep(15)

if __name__ == '__main__':
    main()
