"""Check obstacles between current price and TP 4470.42"""
import sys
sys.path.insert(0, ".")
from tradingview_tool import fetch_xauusd_data
from smc_local import analyze_smc, detect_fvg
from datetime import datetime, timedelta, timezone

data = fetch_xauusd_data(symbol="FOREXCOM:XAUUSD", timeframe="5", limit=500, range_val=500)
candles = data["candles"]
price = candles[-1]["close"]
tp_target = 4461.69  # TP aktual dari trade

def fmt(ts):
    return (datetime.fromtimestamp(ts, tz=timezone.utc) + timedelta(hours=7)).strftime("%d/%m %H:%M")

print(f"HARGA SEKARANG: {price:.2f}")
print(f"TP TARGET: {tp_target:.2f}")
print(f"JARAK: {price - tp_target:.2f} poin")
print()

# 1. Cek Bullish FVG di bawah (support zones)
fvgs = detect_fvg(candles, min_gap=2.0, max_age=200)
bullish_below = [f for f in fvgs if f['type'] == 'bullish_fvg' and f['high'] < price and f['low'] > tp_target]
bearish_below = [f for f in fvgs if f['type'] == 'bearish_fvg' and f['high'] < price and f['low'] > tp_target]

print("=== HALANGAN MENUJU TP (support zones di bawah) ===\n")

if bullish_below:
    print("🟢 BULLISH FVG (bisa jadi support/bounce):")
    for f in sorted(bullish_below, key=lambda x: -x['high']):
        print(f"  [{fmt(f['time'])}] {f['low']:.2f} - {f['high']:.2f} | gap={f['gap_size']:.2f}")
else:
    print("🟢 Tidak ada Bullish FVG antara harga dan TP")

print()

# 2. Cek swing lows (support levels)
smc = analyze_smc(candles)
import pandas as pd
from smc_local import detect_swing_points
df = pd.DataFrame(candles)
df = detect_swing_points(df, lookback=5)
swing_lows = df[df['swing_low'] == True]
support_lows = swing_lows[(swing_lows['low'] < price) & (swing_lows['low'] > tp_target)]

print("📉 SWING LOWS (support levels):")
if len(support_lows) > 0:
    for idx, row in support_lows.iterrows():
        print(f"  [{fmt(row['time'])}] LOW = {row['low']:.2f}")
else:
    print("  Tidak ada swing low antara harga dan TP")

print()
print("=" * 50)
print(f"KESIMPULAN:")
print(f"  Harga: {price:.2f}")
total_obstacles = len(bullish_below) + len(support_lows)
if total_obstacles > 0:
    print(f"  ⚠️ Ada {total_obstacles} halangan menuju TP {tp_target:.2f}")
else:
    print(f"  ✅ Jalur menuju TP {tp_target:.2f} relatif bersih")
