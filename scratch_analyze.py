import json

# Jalankan perintah backtest dan dapatkan output json
import subprocess

cmd = "python bot.py --backtest --limit 5000 --to 2026-05-22 --range 8000 --capital 1000 --json"
result = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding='utf-8')

# Ambil data JSON dengan mengabaikan log non-JSON di awal
stdout_clean = result.stdout
json_start = stdout_clean.find('{')
if json_start != -1:
    stdout_clean = stdout_clean[json_start:]

try:
    data = json.loads(stdout_clean)
    trades = data.get("trades", [])
    
    losing_trades = [t for t in trades if t.get("profit", 0) < 0]
    
    print(f"TOTAL RUGI: {len(losing_trades)} trades")
    
    # Kelompokkan berdasarkan arah
    buys = [t for t in losing_trades if t["direction"] == "buy"]
    sells = [t for t in losing_trades if t["direction"] == "sell"]
    print(f"BUY RUGI: {len(buys)}")
    print(f"SELL RUGI: {len(sells)}")
    
    # Hitung rata-rata kerugian
    avg_loss = sum(t["profit"] for t in losing_trades) / len(losing_trades)
    print(f"RATA-RATA RUGI: ${avg_loss:.2f}")
    
    # Simpan detail ke file markdown agar user bisa membaca dengan rapi
    with open("losing_trades_report.md", "w") as f:
        f.write("# Laporan Detail Transaksi Rugi (Losing Trades)\n\n")
        f.write(f"- **Total Transaksi Rugi:** {len(losing_trades)} dari 73 total trade\n")
        f.write(f"- **Rugi Posisi BUY:** {len(buys)} trade\n")
        f.write(f"- **Rugi Posisi SELL:** {len(sells)} trade\n")
        f.write(f"- **Rata-rata Kerugian:** ${avg_loss:.2f} per trade\n\n")
        
        f.write("### Daftar Transaksi Rugi:\n\n")
        f.write("| No | Arah | Entry Price | Stop Loss | Exit Price | Kerugian ($) | Alasan Entry | Waktu Entry |\n")
        f.write("|---|------|-------------|-----------|------------|--------------|--------------|-------------|\n")
        
        for idx, t in enumerate(losing_trades, 1):
            # Ubah timestamp ke waktu format tanggal
            from datetime import datetime, timezone, timedelta
            dt = datetime.fromtimestamp(t["entry_time"], tz=timezone.utc) + timedelta(hours=7)
            time_str = dt.strftime("%Y-%m-%d %H:%M")
            
            f.write(f"| {idx} | {t['direction'].upper()} | {t['entry_price']} | {t['sl']} | {t['exit_price']} | {t['profit']} | {t['reason']} | {time_str} WIB |\n")
            
    print("Laporan berhasil ditulis ke losing_trades_report.md")

except Exception as e:
    print("Error:", e)
    print("Stdout sample:", result.stdout[:500])
