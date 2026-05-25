import time
import sys
import logging
import threading
import requests
from datetime import datetime, timezone, timedelta
from config import (
    MT5_SYMBOL, 
    TRADING_START_HOUR, TRADING_END_HOUR,
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    get_lot_size, save_lot_size,
    get_daily_loss_limit, save_daily_loss_limit
)
from tradingview_tool import fetch_xauusd_data
from smc_local import analyze_smc
import mt5_executor
from telegram_notifier import send_telegram_notification

# Setup logging ke console dan file
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("live_trader.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("SMCBot.LiveTrader")

# State tracker harian
state = {
    "current_date": None,
    "daily_loss": 0.0,
    "processed_bars": set(),       # Bar timestamps yang sudah dianalisis entry-nya
    "last_closed_deal_ticket": 0,  # Melacak tiket transaksi terluar untuk hitung rugi
    "active_tickets": [],          # Menyimpan ID tiket posisi bot yang sedang berjalan
}

def is_trading_hour():
    """
    Cek apakah waktu saat ini berada di dalam jam trading aktif (WIB).
    """
    # Waktu UTC + 7 Jam = WIB
    wib_now = datetime.now(timezone.utc) + timedelta(hours=7)
    return TRADING_START_HOUR <= wib_now.hour < TRADING_END_HOUR

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
            deal_time = datetime.fromtimestamp(deal.time, tz=timezone.utc) + timedelta(hours=7)
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
        
        # Ambil history deals untuk mencari transaksi penutupan (OUT) untuk tiket ini
        start_time = datetime.now() - timedelta(days=1)
        history_deals = mt5_executor.mt5.history_deals_get(start_time, datetime.now())
        
        if not history_deals:
            logger.warning(f"Detail deal untuk tiket #{ticket} tidak ditemukan di history.")
            if ticket in state["active_tickets"]:
                state["active_tickets"].remove(ticket)
            continue

        # Cari deal penutupan (entry == 1 (OUT)) yang terikat dengan posisi (position_id == ticket)
        closing_deal = None
        for deal in history_deals:
            if deal.position_id == ticket and deal.entry == 1:
                closing_deal = deal
                break

        if closing_deal is None:
            # Kadang deal penutupan masih diproses oleh broker. Kita coba lagi pada siklus berikutnya.
            logger.warning(f"Deal OUT untuk tiket posisi #{ticket} belum tercatat di history broker.")
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
        if reason_code == 3:
            status_str = "STOP LOSS (SL) 🔴"
        elif reason_code == 4:
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

def run_trading_cycle():
    """
    Satu siklus scan market, deteksi sinyal, dan eksekusi MT5.
    """
    # 1. Pantau penutupan posisi aktif bot
    monitor_closed_positions()

    # 2. Update status kerugian harian berjalan
    update_daily_losses()

    current_loss_limit = get_daily_loss_limit()

    # 3. Cek filter Daily Loss Limit
    if state["daily_loss"] >= current_loss_limit:
        logger.warning(f"⚠️ Batas kerugian harian tercapai: ${state['daily_loss']} >= ${current_loss_limit}. Auto-trade dinonaktifkan untuk sisa hari ini.")
        return

    # 4. Cek filter jam perdagangan WIB (08:00 - 19:00 WIB)
    if not is_trading_hour():
        logger.info("💤 Di luar jam perdagangan aktif (08:00 - 19:00 WIB). Menunggu...")
        return

    # 5. Ambil candle real-time (Timeframe 5M)
    # Gunakan limit 1500 agar EMA 200 terhitung secara presisi dan sesuai dengan TradingView
    data = fetch_xauusd_data(symbol="FOREXCOM:XAUUSD", timeframe="5", limit=1500, range_val=1500)
    if 'error' in data:
        logger.error(f"Gagal mengambil candle dari TradingView: {data['error']}")
        return

    candles = data.get('candles', [])
    if not candles:
        logger.warning("Tidak ada data candle baru terdeteksi.")
        return

    latest_candle = candles[-1]
    candle_time = latest_candle.get('time')

    # Cek apakah candle terakhir sudah pernah kita proses untuk entry baru
    if candle_time in state["processed_bars"]:
        return # Abaikan jika bar ini sudah kita periksa

    # 6. Hitung analisis SMC dan Indikator lokal
    smc = analyze_smc(candles)
    market_bias = smc.get('market_bias', 'neutral')
    active_obs = smc.get('active_order_blocks', [])
    
    rsi = latest_candle.get('rsi_14')
    ema_200 = latest_candle.get('ema_200')
    atr = latest_candle.get('atr_14')
    current_price = latest_candle['close']

    if not atr or not ema_200:
        return # Data indikator awal belum siap

    # 7. Cek apakah ada posisi aktif berjalan yang dibuka bot
    active_positions = mt5_executor.check_active_positions()
    if len(active_positions) > 0:
        logger.info(f"ℹ️ Ada {len(active_positions)} posisi bot sedang berjalan di MT5. Menunggu posisi ditutup...")
        state["processed_bars"].add(candle_time)
        
        # Sinkronisasi tiket aktif jika ada tiket baru di MT5 yang belum terdaftar di state
        # (Misal setelah bot direstart saat ada posisi berjalan)
        for pos in active_positions:
            if pos.ticket not in state["active_tickets"]:
                state["active_tickets"].append(pos.ticket)
                logger.info(f"Synchronized running ticket #{pos.ticket} to state.")
                
        return

    # 8. Evaluasi Aturan Entry (Checkpoint 3)
    entry_direction = None
    sl_level = 0.0
    tp_level = 0.0
    reason_msg = ""

    for ob in active_obs:
        # Poin 1: Bullish OB Retest + Bias Bullish/Neutral + Filter EMA 200
        if ob['type'] == 'bullish_ob' and market_bias in ('bullish', 'neutral'):
            # Retest zone check
            if latest_candle['low'] <= ob['high'] and latest_candle['close'] > ob['low']:
                # Filter Trend EMA 200: BUY hanya jika harga di atas EMA 200
                if ema_200 and current_price < ema_200:
                    continue
                # Filter RSI Overbought
                if rsi and rsi > 70:
                    continue
                
                entry_direction = 'buy'
                sl_level = ob['low'] - (atr * 1.0) # SL 1.0x ATR
                tp_level = current_price + (atr * 2.0) # TP 2.0x ATR
                reason_msg = f"Bullish OB retest (bias={market_bias})"
                break

        # Poin 2: Bearish OB Retest + Bias Bearish/Neutral + Filter EMA 200
        elif ob['type'] == 'bearish_ob' and market_bias in ('bearish', 'neutral'):
            # Retest zone check
            if latest_candle['high'] >= ob['low'] and latest_candle['close'] < ob['high']:
                # Filter Trend EMA 200: SELL hanya jika harga di bawah EMA 200
                if ema_200 and current_price > ema_200:
                    continue
                # Filter RSI Oversold
                if rsi and rsi < 30:
                    continue
                
                entry_direction = 'sell'
                sl_level = ob['high'] + (atr * 1.0) # SL 1.0x ATR
                tp_level = current_price - (atr * 2.0) # TP 2.0x ATR
                reason_msg = f"Bearish OB retest (bias={market_bias})"
                break

    # 9. Kirim order ke MetaTrader 5
    if entry_direction:
        logger.info(f"🎯 SINYAL TERDETEKSI: {entry_direction.upper()} | {reason_msg}")
        order_res = mt5_executor.open_trade(
            direction=entry_direction,
            entry_price=current_price,
            sl=sl_level,
            tp=tp_level,
            reason=reason_msg
        )
        if order_res:
            logger.info("Order otomatis berhasil dipasang di MT5.")
            # Gunakan order_res.position (Position Ticket) bukannya order_res.order (Order Ticket)
            state["active_tickets"].append(order_res.position)
        
    state["processed_bars"].add(candle_time)


# =====================================================================
# TELEGRAM BOT LISTENER (BACKGROUND PROCESS)
# =====================================================================

def telegram_polling_thread():
    """
    Fungsi loop background untuk menerima dan merespon command Telegram.
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

def process_telegram_command(text):
    """
    Memproses dan merespon command dari pengguna.
    """
    parts = text.split()
    command = parts[0].lower()
    
    if command == "/help" or command == "/start":
        help_msg = (
            "🤖 *Menu Perintah SMC Gold Bot:*\n\n"
            "*📋 Perintah:*\n"
            "💬 `/status` - Info live, modal, status bot\n"
            "💬 `/setlot <angka>` - Setel lot trading\n"
            "💬 `/setloss <angka>` - Setel batas rugi harian\n"
            "💬 `/journal` - 5 transaksi terakhir\n"
            "💬 `/close` - Tutup manual semua posisi bot yang sedang berjalan\n"
            "💬 `/testtrade` - Uji coba order ke MT5\n"
            "💬 `/help` - Menu bantuan ini\n\n"
            "*💡 Pertanyaan Interaktif (ketik langsung):*\n"
            "• _kondisi market?_\n"
            "• _order block dimana?_\n"
            "• _kapan bisa entry?_\n"
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
        
        # Cek jam aktif
        trading_status = "🟢 AKTIF" if is_trading_hour() else "💤 STANDBY"
        
        status_msg = (
            f"📊 *STATUS LIVE BOT SMC:*\n\n"
            f"👤 *Akun Broker:* {account_info.login if account_info else 'N/A'}\n"
            f"💰 *Balance:* {balance}\n"
            f"💵 *Equity:* {equity}\n"
            f"⚙️ *Lot Size Saat Ini:* `{get_lot_size():.3f} lot`\n"
            f"🛑 *Batas Daily Loss:* ${get_daily_loss_limit():.2f}\n"
            f"📉 *Total Loss Hari Ini:* ${state['daily_loss']}\n"
            f"⏱️ *Status Jam Trading:* {trading_status} (08:00 - 19:00 WIB)"
        )
        send_telegram_notification(status_msg)
        
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

    elif command == "/journal":
        if not mt5_executor.initialize_mt5():
            send_telegram_notification("❌ Gagal terhubung ke MT5 untuk membaca jurnal.")
            return
            
        # Ambil transaksi 3 hari terakhir untuk cadangan history
        from datetime import datetime
        start_date = datetime.now() - timedelta(days=3)
        deals = mt5_executor.mt5.history_deals_get(start_date, datetime.now())
        
        if not deals:
            send_telegram_notification("📂 *Jurnal Kosong:* Tidak ada transaksi tercatat dalam 3 hari terakhir.")
            return
            
        # Ambil 5 deal terakhir
        deals = list(deals)[-5:]
        deals.reverse() # Urutkan dari yang paling baru
        
        journal_text = "📋 *JURNAL TRADE (5 Transaksi Terakhir):*\n\n"
        for d in deals:
            deal_time = datetime.fromtimestamp(d.time, tz=timezone.utc) + timedelta(hours=7)
            time_str = deal_time.strftime('%H:%M:%S WIB')
            
            # Tentukan tipe transaksi
            # entry: 0=IN (open), 1=OUT (close). type: 0=Buy, 1=Sell
            direction = "BUY" if d.type == 0 else "SELL"
            action_type = "OPEN" if d.entry == 0 else "CLOSE"
            
            profit = d.profit + d.swap + d.commission
            profit_str = f"+${profit:.2f} 🟢" if profit > 0 else (f"-${abs(profit):.2f} 🔴" if profit < 0 else "$0.00 ⚪")
            
            journal_text += (
                f"⏱️ *{time_str}* | {d.symbol}\n"
                f"▪️ *Tipe:* {direction} ({action_type})\n"
                f"▪️ *Lot:* {d.volume:.3f} | *Harga:* {d.price}\n"
                f"▪️ *P/L:* {profit_str if action_type == 'CLOSE' else 'Active'}\n"
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
    """Helper: Ambil data pasar terkini dan analisis SMC."""
    try:
        data = fetch_xauusd_data(symbol="FOREXCOM:XAUUSD", timeframe="5", limit=1500, range_val=1500)
        if 'error' in data or not data.get('candles'):
            return None
        candles = data['candles']
        latest = candles[-1]
        smc = analyze_smc(candles)
        return {
            "price": latest['close'],
            "rsi": latest.get('rsi_14'),
            "ema_200": latest.get('ema_200'),
            "atr": latest.get('atr_14'),
            "bias": smc.get('market_bias', 'neutral'),
            "active_obs": smc.get('active_order_blocks', []),
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

    price, rsi, ema, atr, bias = market["price"], market["rsi"], market["ema_200"], market["atr"], market["bias"]
    bias_icon = "🟢" if bias == "bullish" else "🔴" if bias == "bearish" else "⚪"

    rsi_status = "N/A"
    if rsi:
        rsi_status = "⚠️ Overbought" if rsi > 70 else ("⚠️ Oversold" if rsi < 30 else "✅ Normal")

    ema_status = f"Harga {'DI ATAS' if price > ema else 'DI BAWAH'} EMA 200 ({ema:.2f})" if ema else "N/A"

    obs = market["active_obs"]
    ob_details = ""
    for ob in obs:
        ob_type = "🟢 Bullish" if ob['type'] == 'bullish_ob' else "🔴 Bearish"
        dist = abs(price - (ob['high'] + ob['low']) / 2)
        ob_details += f"\n   {ob_type}: {ob['low']:.2f} - {ob['high']:.2f} (jarak: {dist:.2f})"

    msg = (
        f"📊 *KONDISI MARKET XAUUSD:*\n\n"
        f"💰 *Harga:* {price:.2f}\n"
        f"{bias_icon} *Market Bias:* {bias.upper()}\n"
        f"📏 *ATR(14):* {atr:.2f}\n"
        f"📊 *RSI(14):* {rsi:.2f} ({rsi_status})\n"
        f"📈 *EMA 200:* {ema_status}\n\n"
        f"🧱 *Order Block Aktif:* {len(obs)}{ob_details}"
    )
    send_telegram_notification(msg)


def answer_order_blocks():
    """Jawab pertanyaan tentang zona Order Block aktif."""
    send_telegram_notification("⏳ Menganalisis Order Block...")
    market = get_live_market_data()
    if not market:
        send_telegram_notification("❌ Gagal mengambil data pasar.")
        return

    obs, price = market["active_obs"], market["price"]
    if not obs:
        send_telegram_notification(
            f"🧱 *ORDER BLOCK AKTIF:*\n\n"
            f"💰 Harga saat ini: {price:.2f}\n"
            f"⚪ Tidak ada Order Block aktif. Bot menunggu zona OB baru terbentuk."
        )
        return

    msg = f"🧱 *ORDER BLOCK AKTIF:*\n\n💰 Harga saat ini: *{price:.2f}*\n"
    for i, ob in enumerate(obs):
        ob_type = "🟢 Bullish OB" if ob['type'] == 'bullish_ob' else "🔴 Bearish OB"
        mid = (ob['high'] + ob['low']) / 2
        dist = abs(price - mid)

        if ob['type'] == 'bullish_ob':
            action = "Harga sudah di zona!" if ob['low'] <= price <= ob['high'] else f"Harga perlu TURUN {price - ob['high']:.2f}" if price > ob['high'] else f"Harga di bawah zona"
        else:
            action = "Harga sudah di zona!" if ob['low'] <= price <= ob['high'] else f"Harga perlu NAIK {ob['low'] - price:.2f}" if price < ob['low'] else f"Harga di atas zona"

        msg += (
            f"\n{ob_type} #{i+1}:\n"
            f"   📍 Zona: {ob['low']:.2f} - {ob['high']:.2f}\n"
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
    obs = market["active_obs"]
    blockers, opportunities = [], []

    # Jam trading
    if not is_trading_hour():
        blockers.append("⏰ Di luar jam trading (08:00-19:00 WIB)")
    else:
        opportunities.append("✅ Dalam jam trading aktif")

    # Daily loss limit
    daily_limit = get_daily_loss_limit()
    if state["daily_loss"] >= daily_limit:
        blockers.append(f"🛑 Batas rugi harian tercapai (${state['daily_loss']:.2f} / ${daily_limit:.2f})")

    # Posisi aktif
    active_pos = mt5_executor.check_active_positions()
    if len(active_pos) > 0:
        blockers.append(f"⏳ Ada {len(active_pos)} posisi aktif berjalan")

    # OB analysis
    if not obs:
        blockers.append("🧱 Tidak ada Order Block aktif")
    else:
        for ob in obs:
            if ob['type'] == 'bullish_ob':
                near = price <= ob['high'] and price >= ob['low']
                ok_ema = ema and price > ema
                ok_rsi = rsi and rsi <= 70
                ok_bias = bias in ('bullish', 'neutral')
                if near and ok_ema and ok_rsi and ok_bias:
                    opportunities.append(f"🟢 BUY siap! OB {ob['low']:.2f}-{ob['high']:.2f}")
                else:
                    if not near:
                        blockers.append(f"📏 Harga belum di Bullish OB ({ob['low']:.2f}-{ob['high']:.2f})")
                    if not ok_ema:
                        blockers.append(f"📉 Harga di bawah EMA 200 → BUY diblokir")
                    if rsi and not ok_rsi:
                        blockers.append(f"⚠️ RSI {rsi:.1f} > 70 (Overbought) → BUY diblokir")
                    if not ok_bias:
                        blockers.append(f"🔴 Bias {bias} → BUY tidak diizinkan")
            elif ob['type'] == 'bearish_ob':
                near = price >= ob['low'] and price <= ob['high']
                ok_ema = ema and price < ema
                ok_rsi = rsi and rsi >= 30
                ok_bias = bias in ('bearish', 'neutral')
                if near and ok_ema and ok_rsi and ok_bias:
                    opportunities.append(f"🔴 SELL siap! OB {ob['low']:.2f}-{ob['high']:.2f}")
                else:
                    if not near:
                        blockers.append(f"📏 Harga belum di Bearish OB ({ob['low']:.2f}-{ob['high']:.2f})")
                    if not ok_ema:
                        blockers.append(f"📈 Harga di atas EMA 200 → SELL diblokir")
                    if rsi and not ok_rsi:
                        blockers.append(f"⚠️ RSI {rsi:.1f} < 30 (Oversold) → SELL diblokir")
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
            deal_time = datetime.fromtimestamp(d.time, tz=timezone.utc) + timedelta(hours=7)
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
    logger.info("🚀 MEMULAI AUTO-TRADING BOT XAUUSD SMC (MT5)")
    logger.info("=========================================================")
    
    # Inisialisasi awal koneksi
    if not mt5_executor.initialize_mt5():
        logger.critical("Koneksi awal ke MT5 gagal. Pastikan aplikasi MT5 di Windows sudah menyala.")
        sys.exit(1)
        
    # Jalankan background thread listener Telegram
    listener_thread = threading.Thread(target=telegram_polling_thread, daemon=True)
    listener_thread.start()

    # Ambil nilai awal
    current_lot = get_lot_size()
    current_loss_limit = get_daily_loss_limit()

    # Kirim notifikasi bot aktif ke Telegram
    wib_start = datetime.now(timezone.utc) + timedelta(hours=7)
    send_telegram_notification(
        f"🤖 *Auto-Trading SMC Bot Aktif!*\n"
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
            send_telegram_notification("⚠️ *SMC Gold Bot dimatikan secara manual.*")
            break
        except Exception as e:
            logger.exception(f"Error tidak terduga pada trading loop: {e}")
            
        # Scan setiap 15 detik untuk akurasi data candle 1M
        time.sleep(15)

if __name__ == '__main__':
    main()
