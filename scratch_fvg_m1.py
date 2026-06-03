"""Detect FVG PERSIS seperti logic di live_trader.py → get_live_market_data() → analyze_smc()"""
import sys
sys.path.insert(0, ".")
from tradingview_tool import fetch_xauusd_data
from smc_local import analyze_smc
from datetime import datetime, timedelta, timezone

# === FETCH DATA PERSIS SEPERTI live_trader.py get_live_market_data() ===
data = fetch_xauusd_data(symbol="FOREXCOM:XAUUSD", timeframe="5", limit=500, range_val=500)
candles = data["candles"]
price = candles[-1]["close"]

# === ANALISIS SMC PERSIS SEPERTI live_trader.py ===
smc = analyze_smc(candles)
bias = smc.get("market_bias", "neutral")
fvgs = smc.get("active_fvgs", [])

def fmt(ts):
    return (datetime.fromtimestamp(ts, tz=timezone.utc) + timedelta(hours=7)).strftime("%d/%m %H:%M")

# === HEADER ===
print(f"HARGA SEKARANG: {price:.2f}")
print(f"M5 candles: {len(candles)}")
print(f"Market Bias: {bias.upper()}")
print(f"detect_fvg() params: min_gap=2.0, max_age=200")
print(f"FVG Aktif (dari analyze_smc): {len(fvgs)}")
print()

# === DETAIL PERSIS SEPERTI TELEGRAM ===
print("=== OUTPUT SEPERTI TELEGRAM ===")
for fvg in fvgs:
    fvg_type = "Bullish" if fvg['type'] == 'bullish_fvg' else "Bearish"
    icon = "[BUY]" if fvg['type'] == 'bullish_fvg' else "[SELL]"
    dist = abs(price - (fvg['high'] + fvg['low']) / 2)
    print(f"   {icon} {fvg_type}: {fvg['low']:.2f} - {fvg['high']:.2f} (gap={fvg['gap_size']:.2f}, jarak={dist:.2f})")
print()

# === BREAKDOWN: SEMUA FVG SEBELUM FILTER ===
print("=" * 60)
print("=== BREAKDOWN: SEMUA FVG TERDETEKSI (SEBELUM FILTER) ===")

from smc_local import detect_fvg

# Tanpa filter
all_fvgs_raw = []
total_candles = len(candles)
for i in range(1, total_candles - 1):
    c1, c2, c3 = candles[i-1], candles[i], candles[i+1]
    if c3["low"] > c1["high"]:
        gap = c3["low"] - c1["high"]
        all_fvgs_raw.append({"type": "BULLISH", "high": c3["low"], "low": c1["high"], "gap": gap, "time": c2["time"], "idx": i})
    if c3["high"] < c1["low"]:
        gap = c1["low"] - c3["high"]
        all_fvgs_raw.append({"type": "BEARISH", "high": c1["low"], "low": c3["high"], "gap": gap, "time": c2["time"], "idx": i})

# Cek filled
for f in all_fvgs_raw:
    f["filled"] = False
    for j in range(f["idx"] + 2, total_candles):
        c = candles[j]
        if f["type"] == "BULLISH" and c["low"] <= f["low"]:
            f["filled"] = True
            break
        elif f["type"] == "BEARISH" and c["high"] >= f["high"]:
            f["filled"] = True
            break

active_raw = [f for f in all_fvgs_raw if not f["filled"]]
nearby = [f for f in active_raw if abs(price - (f["high"] + f["low"]) / 2) < 30]

print(f"\nTotal FVG terdeteksi (semua): {len(all_fvgs_raw)}")
print(f"Aktif (belum filled): {len(active_raw)}")
print(f"Dekat harga (+-30 poin): {len(nearby)}")
print()

# Filter yang DIBUANG oleh analyze_smc
filtered_by_gap = [f for f in active_raw if f["gap"] < 2.0]
filtered_by_age = [f for f in active_raw if f["gap"] >= 2.0 and (total_candles - 1 - f["idx"]) > 200]
passed = [f for f in active_raw if f["gap"] >= 2.0 and (total_candles - 1 - f["idx"]) <= 200]

print(f"--- LOLOS filter (min_gap>=2.0 & age<=200): {len(passed)}  <-- INI YANG MUNCUL DI TELEGRAM")
for f in sorted(passed, key=lambda x: -x["high"]):
    age = total_candles - 1 - f["idx"]
    dist = abs(price - (f["high"] + f["low"]) / 2)
    print(f"  [{fmt(f['time'])}] {f['type']:8s} | {f['low']:.2f} - {f['high']:.2f} | gap={f['gap']:.2f} | age={age} | jarak={dist:.1f}")

print(f"\n--- DIBUANG karena gap < 2.0: {len(filtered_by_gap)}")
for f in sorted(filtered_by_gap, key=lambda x: -x["high"]):
    age = total_candles - 1 - f["idx"]
    dist = abs(price - (f["high"] + f["low"]) / 2)
    print(f"  [{fmt(f['time'])}] {f['type']:8s} | {f['low']:.2f} - {f['high']:.2f} | gap={f['gap']:.2f} | age={age} | jarak={dist:.1f}")

print(f"\n--- DIBUANG karena age > 200: {len(filtered_by_age)}")
for f in sorted(filtered_by_age, key=lambda x: -x["high"]):
    age = total_candles - 1 - f["idx"]
    dist = abs(price - (f["high"] + f["low"]) / 2)
    print(f"  [{fmt(f['time'])}] {f['type']:8s} | {f['low']:.2f} - {f['high']:.2f} | gap={f['gap']:.2f} | age={age} | jarak={dist:.1f}")
