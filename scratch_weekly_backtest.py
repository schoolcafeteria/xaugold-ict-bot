import subprocess
import json
from datetime import datetime

# Definisikan periode mingguan (Senin - Jumat)
weeks = [
    {"name": "Minggu 1 (4 - 8 Mei)", "from": "2026-05-04", "to": "2026-05-08"},
    {"name": "Minggu 2 (11 - 15 Mei)", "from": "2026-05-11", "to": "2026-05-15"},
    {"name": "Minggu 3 (18 - 22 Mei)", "from": "2026-05-18", "to": "2026-05-22"}
]

print("MEMULAI PENGUJIAN MINGGUAN TIMEFRAME 1M - DATA MT5 (SALDO $40)...\n")

results = []

for w in weeks:
    print(f"  Running backtest untuk {w['name']}...")
    cmd = f"python bot.py --backtest --from {w['from']} --to {w['to']} --capital 40 --source mt5 --json"
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding='utf-8')
    
    # Bersihkan output non-JSON
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
        print(f"  Done: P/L = ${summary.get('net_pnl', 0.0):.2f} ({summary.get('net_pnl_pct', 0.0):.2f}%), WR = {summary.get('win_rate_pct', 0.0):.2f}%")
    except Exception as e:
        print(f"  Gagal memproses {w['name']}: {e}")

# Cetak tabel laporan akhir
print("\n" + "=" * 110)
print("  LAPORAN KINERJA MINGGUAN (M1, MT5, $40 Capital, Lot 0.01, Daily Loss $10, Jam 08-19 WIB, TANPA EMA 200)")
print("=" * 110)
print(f"{'Periode':<25} | {'Modal Awal':<10} | {'Modal Akhir':<11} | {'Net P/L ($)':<12} | {'Net P/L (%)':<12} | {'Trades':<6} | {'Win Rate':<8} | {'Max DD':<7}")
print("-" * 110)
for r in results:
    print(f"{r['name']:<25} | ${r['initial']:<9.2f} | ${r['final']:<10.2f} | ${r['pnl']:<11.2f} | {r['pnl_pct']:<10.2f}% | {r['trades']:<6} | {r['win_rate']:<6.2f}% | {r['drawdown']:<6.2f}%")
print("=" * 110)

# Rangkuman total
if results:
    total_pnl = sum(r['pnl'] for r in results)
    total_trades = sum(r['trades'] for r in results)
    avg_wr = sum(r['win_rate'] for r in results) / len(results)
    max_dd = max(r['drawdown'] for r in results)
    print(f"\n  TOTAL 3 MINGGU: Net P/L = ${total_pnl:.2f} | Trades = {total_trades} | Avg WR = {avg_wr:.2f}% | Max DD = {max_dd:.2f}%")
