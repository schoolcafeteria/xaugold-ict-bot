"""Check trading journal dari MT5"""
import sys
sys.path.insert(0, ".")
import mt5_executor
from config import MT5_MAGIC_NUMBER
from datetime import datetime, timedelta

if not mt5_executor.initialize_mt5():
    print("MT5 tidak konek")
    sys.exit(1)

# Ambil history 14 hari terakhir
start = datetime.now() - timedelta(days=14)
end = datetime.now() + timedelta(days=1)
deals = mt5_executor.mt5.history_deals_get(start, end)

if not deals:
    print("Tidak ada transaksi")
    sys.exit(0)

# Filter deal CLOSE dari bot (magic number)
closed = [d for d in deals if d.entry == 1 and d.magic == MT5_MAGIC_NUMBER]

print(f"Magic Number: {MT5_MAGIC_NUMBER}")
print(f"Total trade (14 hari): {len(closed)}")
print()

total_profit = 0
total_loss = 0
wins = 0
losses = 0

header = f"{'Waktu WIB':<18} {'Arah':<6} {'Lot':<6} {'Exit':<10} {'P/L':>10} {'Alasan':<8}"
print(header)
print("-" * len(header))

for d in closed:
    t = datetime.fromtimestamp(d.time) - timedelta(hours=3)
    time_str = t.strftime("%d/%m %H:%M")
    direction = "BUY" if d.type == 1 else "SELL"
    pnl = d.profit + d.swap + d.commission

    if pnl > 0:
        wins += 1
        total_profit += pnl
    elif pnl < 0:
        losses += 1
        total_loss += abs(pnl)

    reason = "Manual"
    if d.reason == 4:
        reason = "SL"
    elif d.reason == 5:
        reason = "TP"

    print(f"{time_str:<18} {direction:<6} {d.volume:<6.2f} {d.price:<10.2f} {pnl:>+10.2f} {reason:<8}")

net = total_profit - total_loss
total = wins + losses
wr = (wins / total * 100) if total > 0 else 0
pf = (total_profit / total_loss) if total_loss > 0 else float("inf")

print()
print("========= RINGKASAN =========")
print(f"Total Trades : {total}")
print(f"Wins         : {wins}")
print(f"Losses       : {losses}")
print(f"Win Rate     : {wr:.1f}%")
print(f"Total Profit : +${total_profit:.2f}")
print(f"Total Loss   : -${total_loss:.2f}")
print(f"Net P/L      : ${net:+.2f}")
print(f"Profit Factor: {pf:.2f}")
