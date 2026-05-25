import requests
import logging
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger("SMCBot.Telegram")

def send_telegram_notification(message):
    """
    Mengirimkan pesan teks ke Telegram Chat ID yang dikonfigurasi.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram Bot Token atau Chat ID belum dikonfigurasi.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            return True
        else:
            logger.error(f"Gagal mengirim pesan Telegram: {response.text}")
            return False
    except Exception as e:
        logger.error(f"Error saat mengirim pesan Telegram: {e}")
        return False
