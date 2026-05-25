import os
import json

# Configuration Settings for XAUUSD SMC Bot

# Telegram Settings
TELEGRAM_BOT_TOKEN = "8878129888:AAE3DB7A5tQrYe-z61q4jy3i7o0e2rACr4A"
TELEGRAM_CHAT_ID = "776656619"

# MetaTrader 5 Settings
MT5_SYMBOL = "XAUUSDc"          # Sesuaikan dengan nama simbol di broker Anda (misal: GOLD, XAUUSD.micro, dll)
MT5_MAGIC_NUMBER = 888200      # ID Unik transaksi bot SMC

# Default values
DEFAULT_LOT_SIZE = 0.01
DEFAULT_DAILY_LOSS_LIMIT = 10.0

def load_settings():
    settings_file = os.path.join(os.path.dirname(__file__), "settings.json")
    if os.path.exists(settings_file):
        try:
            with open(settings_file, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_settings(settings_dict):
    settings_file = os.path.join(os.path.dirname(__file__), "settings.json")
    try:
        current_settings = load_settings()
        current_settings.update(settings_dict)
        with open(settings_file, "w") as f:
            json.dump(current_settings, f, indent=4)
        return True
    except Exception:
        return False

def get_lot_size():
    settings = load_settings()
    return float(settings.get("lot_size", DEFAULT_LOT_SIZE))

def save_lot_size(new_lot):
    return save_settings({"lot_size": new_lot})

def get_daily_loss_limit():
    settings = load_settings()
    return float(settings.get("daily_loss_limit", DEFAULT_DAILY_LOSS_LIMIT))

def save_daily_loss_limit(new_limit):
    return save_settings({"daily_loss_limit": new_limit})

# Dynamic LOT and Loss properties fallback
MT5_LOT_SIZE = DEFAULT_LOT_SIZE
DAILY_LOSS_LIMIT = DEFAULT_DAILY_LOSS_LIMIT

# Trading Risk Settings (Dari Checkpoint 3)
TRADING_START_HOUR = 8         # Jam 08:00 WIB
TRADING_END_HOUR = 19          # Jam 19:00 WIB (Sinyal baru ditiadakan setelah jam 19.00)
