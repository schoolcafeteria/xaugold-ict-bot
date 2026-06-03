import requests
import json
import logging
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger("ICTBot.Telegram")

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


def send_telegram_with_keyboard(message, keyboard):
    """
    Mengirimkan pesan teks dengan inline keyboard buttons.
    
    Args:
        message: Teks pesan (Markdown)
        keyboard: List of list of button dicts, contoh:
            [[{"text": "📊 Status", "callback_data": "menu_status"}],
             [{"text": "⏸️ Pause", "callback_data": "menu_pause"}]]
    
    Returns:
        message_id jika berhasil, None jika gagal
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return None

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "reply_markup": json.dumps({"inline_keyboard": keyboard})
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            result = response.json()
            return result.get("result", {}).get("message_id")
        else:
            logger.error(f"Gagal mengirim keyboard Telegram: {response.text}")
            return None
    except Exception as e:
        logger.error(f"Error saat mengirim keyboard Telegram: {e}")
        return None


def edit_telegram_message(message_id, message, keyboard=None):
    """
    Mengedit pesan Telegram yang sudah ada (update konten & keyboard).
    
    Args:
        message_id: ID pesan yang ingin diedit
        message: Teks pesan baru (Markdown)
        keyboard: Inline keyboard baru (opsional, None = hapus keyboard)
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/editMessageText"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "message_id": message_id,
        "text": message,
        "parse_mode": "Markdown"
    }

    if keyboard is not None:
        payload["reply_markup"] = json.dumps({"inline_keyboard": keyboard})
    else:
        payload["reply_markup"] = json.dumps({"inline_keyboard": []})

    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            return True
        else:
            # Jika pesan tidak berubah, Telegram return 400 — bukan error serius
            if "message is not modified" in response.text:
                return True
            logger.error(f"Gagal edit pesan Telegram: {response.text}")
            return False
    except Exception as e:
        logger.error(f"Error saat edit pesan Telegram: {e}")
        return False


def answer_callback_query(callback_query_id, text=None):
    """
    Menjawab callback query (menghilangkan loading spinner pada tombol).
    
    Args:
        callback_query_id: ID dari callback query
        text: Opsional, teks notifikasi kecil yang muncul sebentar di atas chat
    """
    if not TELEGRAM_BOT_TOKEN:
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery"
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text

    try:
        requests.post(url, json=payload, timeout=5)
        return True
    except Exception:
        return False
