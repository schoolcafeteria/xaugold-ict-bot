import MetaTrader5 as mt5
import logging
from config import MT5_SYMBOL, MT5_MAGIC_NUMBER, get_lot_size
from telegram_notifier import send_telegram_notification

logger = logging.getLogger("ICTBot.MT5")

def initialize_mt5():
    """
    Menginisialisasi koneksi ke MetaTrader 5 yang sedang berjalan di PC.
    """
    if not mt5.initialize():
        error_code = mt5.last_error()
        msg = f"❌ Gagal inisialisasi MetaTrader 5. Kode error: {error_code}"
        logger.error(msg)
        send_telegram_notification(msg)
        return False
    
    logger.info("✅ MetaTrader 5 terhubung dengan sukses.")
    return True

def get_symbol_info(symbol=MT5_SYMBOL):
    """
    Mengambil data symbol aktif untuk memastikan symbol terdaftar di broker.
    """
    # Pastikan symbol terlihat di Market Watch
    mt5.symbol_select(symbol, True)
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        logger.error(f"Symbol {symbol} tidak ditemukan di terminal MT5.")
        return None
    return symbol_info

def open_trade(direction, entry_price, sl, tp, reason=""):
    """
    Membuka posisi BUY atau SELL baru di MetaTrader 5 dengan SL dan TP otomatis.
    """
    if not initialize_mt5():
        return None

    symbol_info = get_symbol_info()
    if symbol_info is None:
        return None

    # Tentukan tipe order dan harga eksekusi live (ask/bid)
    if direction.lower() == 'buy':
        order_type = mt5.ORDER_TYPE_BUY
        price = mt5.symbol_info_tick(MT5_SYMBOL).ask
    elif direction.lower() == 'sell':
        order_type = mt5.ORDER_TYPE_SELL
        price = mt5.symbol_info_tick(MT5_SYMBOL).bid
    else:
        logger.error(f"Arah posisi tidak valid: {direction}")
        return None

    # Bulatkan harga SL dan TP sesuai digit symbol (misal XAUUSD memiliki 2 atau 3 digit desimal)
    digits = symbol_info.digits
    sl = round(sl, digits)
    tp = round(tp, digits)
    price = round(price, digits)

    current_lot = get_lot_size()

    # Deteksi filling mode yang didukung oleh broker secara otomatis
    filling = mt5.ORDER_FILLING_FOK  # Default fallback
    
    # Cek bitmask filling mode dari broker
    # SYMBOL_FILLING_FOK = 1, SYMBOL_FILLING_IOC = 2
    if symbol_info.filling_mode & 1:
        filling = mt5.ORDER_FILLING_FOK
    elif symbol_info.filling_mode & 2:
        filling = mt5.ORDER_FILLING_IOC
    else:
        filling = mt5.ORDER_FILLING_RETURN

    # Siapkan request order ke MT5
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": MT5_SYMBOL,
        "volume": current_lot,
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": 20,                  # Maksimal slippage deviasi dalam pips/points
        "magic": MT5_MAGIC_NUMBER,
        "comment": "ICT FVG Bot",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": filling,
    }

    logger.info(f"Mengirim order {direction.upper()} {current_lot} lot @ {price} | SL: {sl} | TP: {tp}")
    
    # Kirim order ke terminal MT5
    result = mt5.order_send(request)
    
    if result is None:
        err = mt5.last_error()
        msg = f"❌ Order {direction.upper()} gagal dikirim ke MT5. Error: {err}"
        logger.error(msg)
        send_telegram_notification(msg)
        return None

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        msg = (f"❌ Order {direction.upper()} ditolak oleh broker/MT5.\n"
               f"Retcode: {result.retcode}\n"
               f"Deskripsi: {result.comment}")
        logger.error(msg)
        send_telegram_notification(msg)
        return None

    # Berhasil dieksekusi
    msg = (f"🚀 *EKSEKUSI POSISI OTOMATIS BERHASIL!*\n\n"
           f"📈 *Arah:* {direction.upper()}\n"
           f"💰 *Lot:* {current_lot}\n"
           f"💵 *Harga Entry:* {result.price}\n"
           f"🛑 *Stop Loss:* {sl}\n"
           f"🎯 *Take Profit:* {tp}\n"
           f"💬 *Alasan:* {reason}")
    
    logger.info(msg)
    send_telegram_notification(msg)
    return result

def check_active_positions():
    """
    Mengambil daftar posisi aktif pada simbol bot (baik dari bot maupun manual).
    """
    if not initialize_mt5():
        return []
    
    positions = mt5.positions_get(symbol=MT5_SYMBOL)
    if positions is None:
        return []
    return list(positions)

def close_position(position):
    """
    Menutup posisi berjalan di MT5 berdasarkan tiket posisi (position object).
    """
    if not initialize_mt5():
        return False

    symbol = position.symbol
    lot = position.volume
    order_type = mt5.ORDER_TYPE_BUY if position.type == mt5.ORDER_TYPE_SELL else mt5.ORDER_TYPE_SELL
    
    # Ambil harga live saat ini untuk menutup posisi
    if order_type == mt5.ORDER_TYPE_BUY:
        price = mt5.symbol_info_tick(symbol).ask
    else:
        price = mt5.symbol_info_tick(symbol).bid

    # Siapkan request penutupan
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot,
        "type": order_type,
        "position": position.ticket,
        "price": price,
        "deviation": 20,
        "magic": MT5_MAGIC_NUMBER,
        "comment": "ICT FVG Bot Close Manual",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": position.type_filling if hasattr(position, 'type_filling') else mt5.ORDER_FILLING_FOK
    }

    logger.info(f"Mengirim request close manual untuk posisi #{position.ticket} ({lot} lot)")
    result = mt5.order_send(request)

    if result is None:
        logger.error(f"Gagal mengirim request close manual ke MT5. Error: {mt5.last_error()}")
        return False

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        logger.error(f"Request close manual ditolak oleh broker. Retcode: {result.retcode}, Comment: {result.comment}")
        return False

    logger.info(f"✅ Posisi #{position.ticket} berhasil ditutup secara manual pada harga {result.price}.")
    return True


def modify_sl(position, new_sl):
    """
    Mengubah Stop Loss posisi aktif di MT5 (untuk Breakeven, Trailing, dll).
    TP tetap dipertahankan.
    
    Args:
        position: Position object dari MT5
        new_sl: Harga SL baru
    
    Returns:
        True jika berhasil, False jika gagal
    """
    if not initialize_mt5():
        return False

    symbol_info = get_symbol_info(position.symbol)
    if symbol_info is None:
        return False

    digits = symbol_info.digits
    new_sl = round(new_sl, digits)

    request = {
        "action": mt5.TRADE_ACTION_SLTP,
        "symbol": position.symbol,
        "position": position.ticket,
        "sl": new_sl,
        "tp": position.tp,  # Pertahankan TP yang sudah ada
        "magic": MT5_MAGIC_NUMBER,
    }

    logger.info(f"Mengubah SL posisi #{position.ticket}: {position.sl} → {new_sl}")
    result = mt5.order_send(request)

    if result is None:
        logger.error(f"Gagal mengubah SL posisi #{position.ticket}. Error: {mt5.last_error()}")
        return False

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        logger.error(f"Modifikasi SL ditolak oleh broker. Retcode: {result.retcode}, Comment: {result.comment}")
        return False

    logger.info(f"✅ SL posisi #{position.ticket} berhasil diubah ke {new_sl}.")
    return True
