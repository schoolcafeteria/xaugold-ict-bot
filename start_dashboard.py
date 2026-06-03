# -*- coding: utf-8 -*-
"""
Startup script untuk Eleu Dashboard
- Jalankan pnl_server.py
- Jalankan ngrok tunnel
- Kirim URL publik ke Telegram
"""

import subprocess
import time
import requests
import sys
import os

# === CONFIG ===
BOT_TOKEN = "8906851032:AAHjlz2pXfaenrGfxHzlS2pXfO3MVEqRIJM"
CHAT_ID   = "776656619"
PORT      = 5000
BASE_DIR  = os.path.dirname(os.path.abspath(__file__))

# Absolute path to ngrok from WinGet
NGROK_PATH = r"C:\Users\Mako by Seris\AppData\Local\Microsoft\WinGet\Packages\Ngrok.Ngrok_Microsoft.Winget.Source_8wekyb3d8bbwe\ngrok.exe"
if not os.path.exists(NGROK_PATH):
    NGROK_PATH = "ngrok" # fallback

def wait_for_internet(timeout_secs=180):
    """Tunggu sampai koneksi internet aktif (bisa ping Telegram API)"""
    start_time = time.time()
    while time.time() - start_time < timeout_secs:
        try:
            # Test connection to Telegram API
            requests.get("https://api.telegram.org", timeout=5)
            return True
        except Exception:
            time.sleep(3)
    return False

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    # Retry sending telegram message up to 5 times
    for i in range(5):
        try:
            res = requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
            if res.status_code == 200:
                return True
        except Exception as e:
            print(f"[Telegram Error] Try {i+1}/5: {e}")
        time.sleep(5)
    return False

def get_ngrok_url(retries=15, delay=2):
    for i in range(retries):
        try:
            res = requests.get("http://localhost:4040/api/tunnels", timeout=5)
            tunnels = res.json().get("tunnels", [])
            if tunnels:
                return tunnels[0]["public_url"]
        except:
            pass
        print(f"[ngrok] Waiting for tunnel... ({i+1}/{retries})")
        time.sleep(delay)
    return None

def main():
    print("=" * 50)
    print("  Eleu Dashboard Startup")
    print("=" * 50)

    # 1. Tunggu internet koneksi dulu
    print("Menunggu koneksi internet...")
    if not wait_for_internet():
        print("Koneksi internet tidak tersedia setelah 3 menit.")
        return

    # 2. Start Flask server
    print("\n[1/3] Starting pnl_server.py...")
    flask_proc = subprocess.Popen(
        [sys.executable, os.path.join(BASE_DIR, "pnl_server.py")],
        cwd=BASE_DIR,
        creationflags=subprocess.CREATE_NO_WINDOW
    )
    time.sleep(3)
    print(f"      Flask PID: {flask_proc.pid}")

    # 3. Start ngrok
    print("\n[2/3] Starting ngrok tunnel...")
    ngrok_proc = subprocess.Popen(
        [NGROK_PATH, "http", str(PORT)],
        creationflags=subprocess.CREATE_NO_WINDOW
    )
    time.sleep(3)

    # 4. Get public URL
    print("\n[3/3] Getting public URL...")
    url = get_ngrok_url()

    if url:
        print(f"\n[OK] Dashboard LIVE: {url}")
        msg = (
            f"*Eleu Dashboard Online!*\n\n"
            f"URL: {url}\n\n"
            f"Dashboard PnL kamu siap diakses dari mana saja.\n"
            f"_URL ini berlaku selama laptop menyala._"
        )
        send_telegram(msg)
        print("[Telegram] Notifikasi terkirim!")
    else:
        print("\n[ERROR] Gagal mendapatkan URL ngrok")
        send_telegram("*Eleu Dashboard gagal start.* Cek terminal.")

    print("\n[INFO] Server berjalan. Tekan Ctrl+C untuk stop.")
    try:
        flask_proc.wait()
    except KeyboardInterrupt:
        print("\n[INFO] Stopping...")
        flask_proc.terminate()
        ngrok_proc.terminate()

if __name__ == "__main__":
    main()
