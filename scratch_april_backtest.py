import subprocess
import json

# Definisikan periode mingguan sepanjang bulan April 2026
weeks = [
    {"name": "Minggu 1 (1 - 3 Apr)", "to": "2026-04-03", "range": 2000},
    {"name": "Minggu 2 (6 - 10 Apr)", "to": "2026-04-10", "range": 2000},
    {"name": "Minggu 3 (13 - 17 Apr)", "to": "2026-04-17", "range": 2000},
    {"name": "Minggu 4 (20 - 24 Apr)", "to": "2026-04-24", "range": 2000},
    {"name": "Minggu 5 (27 - 30 Apr)", "to": "2026-04-30", "range": 2000}
]

print("MEMULAI PENGUJIAN MINGGUAN BULAN APRIL 2026 (TIMEFRAME 5M, SALDO $40)...\n")
print("Parameter: Lot 0.01 | Daily Loss $10 | Sesi WIB 08:00 - 19:00\n")

results = []

for w in weeks:
    print(f"⏳ Running backtest untuk {w['name']}...")
    cmd = f"python bot.py --backtest --limit 1500 --to {w['to']} --range {w['range']} --capital 40 --json"
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding='utf-8')
    
    stdout_clean = res.stdout
    json_start = stdout_clean.find('{')
    if json_start != -1:
        stdout_clean = stdout_clean[json_start:]
        
    try:
        data = json.loads(stdout_clean)
        summary = data.get("summary", {})
        results.append({
            "name": w["name"],
            "initial": summary.get("initial_capital", 40.0),
            "final": summary.get("final_capital", 0.0),
            "pnl": summary.get("net_pnl", 0.0),
            "pnl_pct": summary.get("net_pnl_pct", 0.0),
            "trades": summary.get("total_trades", 0),
            "win_rate": summary.get("win_rate_pct", 0.0),
            "drawdown": summary.get("max_drawdown_pct", 0.0)
        })
        print(f"✅ Selesai: P/L = ${summary.get('net_pnl', 0.0):.2f} ({summary.get('net_pnl_pct', 0.0):.2f}%), WR = {summary.get('win_rate_pct', 0.0):.2f}%")
    except Exception as e:
        print(f"❌ Gagal memproses {w['name']}: {e}")

# Cetak tabel laporan akhir
print("\n==========================================================================================")
print("📋 LAPORAN KINERJA MINGGUAN BULAN APRIL 2026 (5M, $40 Capital, Lot 0.01, Daily Loss $10)")
print("==========================================================================================")
print(f"{'Periode':<25} | {'Modal Awal':<10} | {'Modal Akhir':<11} | {'Net P/L ($)':<12} | {'Net P/L (%)':<12} | {'Trades':<6} | {'Win Rate':<8} | {'Max DD':<7}")
print("-" * 106)
for r in results:
    print(f"{r['name']:<25} | ${r['initial']:<9.2f} | ${r['final']:<10.2f} | ${r['pnl']:<11.2f} | {r['pnl_pct']:<10.2f}% | {r['trades']:<6} | {r['win_rate']:<6.2f}% | {r['drawdown']:<6.2f}%")
print("==========================================================================================")
