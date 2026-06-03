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

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        print(f"[Telegram Error] {e}")

def get_ngrok_url(retries=10, delay=2):
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

    # 1. Start Flask server
    print("\n[1/3] Starting pnl_server.py...")
    flask_proc = subprocess.Popen(
        [sys.executable, os.path.join(BASE_DIR, "pnl_server.py")],
        cwd=BASE_DIR,
        creationflags=subprocess.CREATE_NEW_CONSOLE
    )
    time.sleep(3)
    print(f"      Flask PID: {flask_proc.pid}")

    # 2. Start ngrok
    print("\n[2/3] Starting ngrok tunnel...")
    ngrok_proc = subprocess.Popen(
        ["ngrok", "http", str(PORT)],
        creationflags=subprocess.CREATE_NEW_CONSOLE
    )
    time.sleep(3)

    # 3. Get public URL
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
