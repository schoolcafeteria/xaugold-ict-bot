"""Detect M5 FVG terdekat dari harga sekarang"""
import sys
sys.path.insert(0, ".")
from tradingview_tool import fetch_xauusd_data
from smc_local import aggregate_m1_to_m5
from datetime import datetime, timedelta, timezone

data = fetch_xauusd_data(symbol="FOREXCOM:XAUUSD", timeframe="5", limit=500, range_val=500)
candles_m1 = data["candles"]
candles = aggregate_m1_to_m5(candles_m1)
price = candles[-1]["close"]

# Detect FVG
fvgs = []
for i in range(1, len(candles) - 1):
    c1, c2, c3 = candles[i - 1], candles[i], candles[i + 1]
    if c3["low"] > c1["high"]:
        fvgs.append({"type": "BULLISH", "high": c3["low"], "low": c1["high"], "time": c2["time"], "idx": i, "filled": False,
                     "c1": c1, "c2": c2, "c3": c3})
    if c3["high"] < c1["low"]:
        fvgs.append({"type": "BEARISH", "high": c1["low"], "low": c3["high"], "time": c2["time"], "idx": i, "filled": False,
                     "c1": c1, "c2": c2, "c3": c3})

# Cek filled
for f in fvgs:
    for j in range(f["idx"] + 2, len(candles)):
        c = candles[j]
        if f["type"] == "BULLISH" and c["low"] <= f["low"]:
            f["filled"] = True
            break
        elif f["type"] == "BEARISH" and c["high"] >= f["high"]:
            f["filled"] = True
            break

active = [f for f in fvgs if not f["filled"]]
nearby = sorted(
    [f for f in active if abs(price - (f["high"] + f["low"]) / 2) < 30],
    key=lambda x: abs(price - (x["high"] + x["low"]) / 2),
)

def fmt(ts):
    return (datetime.fromtimestamp(ts, tz=timezone.utc) + timedelta(hours=7)).strftime("%d/%m %H:%M")

print(f"HARGA SEKARANG: {price:.2f}")
print(f"M5 candles: {len(candles)}")
print(f"M5 FVG total: {len(fvgs)} | Aktif: {len(active)} | Dekat harga: {len(nearby)}")
print()

above = sorted([f for f in nearby if (f["high"] + f["low"]) / 2 > price], key=lambda x: -x["high"])
below = sorted([f for f in nearby if (f["high"] + f["low"]) / 2 <= price], key=lambda x: -x["high"])

print("=== DI ATAS HARGA (resistance / sell zone) ===")
for f in above:
    gap = f["high"] - f["low"]
    dist = (f["high"] + f["low"]) / 2 - price
    inside = " <<< HARGA DI SINI" if f["low"] <= price <= f["high"] else ""
    print(f"  [{fmt(f['time'])}] {f['type']:8s} | {f['low']:.2f} - {f['high']:.2f} | gap={gap:.2f} | +{dist:.1f} poin{inside}")

print(f"\n  --- HARGA: {price:.2f} ---\n")

print("=== DI BAWAH HARGA (support / buy zone) ===")
for f in below:
    gap = f["high"] - f["low"]
    dist = price - (f["high"] + f["low"]) / 2
    inside = " <<< HARGA DI SINI" if f["low"] <= price <= f["high"] else ""
    print(f"  [{fmt(f['time'])}] {f['type']:8s} | {f['low']:.2f} - {f['high']:.2f} | gap={gap:.2f} | -{dist:.1f} poin{inside}")

# Detail FVG terdekat
print()
print("=" * 60)
closest = nearby[0] if nearby else None
if closest:
    print(f"FVG TERDEKAT - DETAIL 3 CANDLE:")
    print(f"  Candle 1 [{fmt(closest['c1']['time'])}]: O={closest['c1']['open']:.2f}  H={closest['c1']['high']:.2f}  L={closest['c1']['low']:.2f}  C={closest['c1']['close']:.2f}")
    print(f"  Candle 2 [{fmt(closest['c2']['time'])}]: O={closest['c2']['open']:.2f}  H={closest['c2']['high']:.2f}  L={closest['c2']['low']:.2f}  C={closest['c2']['close']:.2f}  << impulse")
    print(f"  Candle 3 [{fmt(closest['c3']['time'])}]: O={closest['c3']['open']:.2f}  H={closest['c3']['high']:.2f}  L={closest['c3']['low']:.2f}  C={closest['c3']['close']:.2f}")
    print(f"  FVG Zone: {closest['low']:.2f} - {closest['high']:.2f} (gap={closest['high']-closest['low']:.2f})")
    dist = abs(price - (closest['high'] + closest['low']) / 2)
    print(f"  Jarak dari harga: {dist:.2f} poin")
