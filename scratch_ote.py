"""OTE calculation around FVG 4505.19-4505.72"""
import sys
sys.path.insert(0, ".")
from tradingview_tool import fetch_xauusd_data
from smc_local import aggregate_m1_to_m5, detect_swing_points, analyze_smc
from datetime import datetime, timedelta, timezone
import pandas as pd

data = fetch_xauusd_data(symbol="FOREXCOM:XAUUSD", timeframe="5", limit=500, range_val=500)
candles_m5 = aggregate_m1_to_m5(data["candles"])
price = candles_m5[-1]["close"]

# Cari swing points M5
df = pd.DataFrame(candles_m5)
df = detect_swing_points(df, lookback=5)

def fmt(ts):
    return (datetime.fromtimestamp(ts, tz=timezone.utc) + timedelta(hours=7)).strftime("%d/%m %H:%M")

# Cari swing high dan swing low terdekat di sekitar FVG (bar index ~280-300)
print(f"HARGA: {price:.2f}")
print(f"FVG: 4505.19 - 4505.72 (Bearish)\n")

# Ambil swing points terakhir
swing_highs = df[df["swing_high"] == True].tail(10)
swing_lows = df[df["swing_low"] == True].tail(10)

print("=== SWING HIGHS M5 (10 terakhir) ===")
for idx, row in swing_highs.iterrows():
    print(f"  [{fmt(row['time'])}] HIGH = {row['high']:.2f}  (bar {idx})")

print("\n=== SWING LOWS M5 (10 terakhir) ===")
for idx, row in swing_lows.iterrows():
    print(f"  [{fmt(row['time'])}] LOW  = {row['low']:.2f}  (bar {idx})")

# Cari swing terdekat untuk OTE calculation
# FVG bearish = bagian dari down move, jadi cari swing HIGH sebelum drop dan swing LOW setelah
# Swing high terakhir sebelum harga turun ke ~4505
recent_sh = None
for idx, row in swing_highs.iterrows():
    if row["high"] > 4505:
        recent_sh = row

recent_sl = None
for idx, row in swing_lows.iterrows():
    if row["low"] < 4510:
        recent_sl = row

if recent_sh is not None and recent_sl is not None:
    sh = recent_sh["high"]
    sl_price = recent_sl["low"]
    
    print(f"\n{'='*60}")
    print(f"OTE CALCULATION:")
    print(f"  Swing High: {sh:.2f} [{fmt(recent_sh['time'])}]")
    print(f"  Swing Low:  {sl_price:.2f} [{fmt(recent_sl['time'])}]")
    print(f"  Range: {sh - sl_price:.2f} poin")
    
    range_size = sh - sl_price
    
    # OTE untuk SELL (retracement dari drop)
    # Price dropped from SH to SL, retracement = price going back UP
    ote_618 = sl_price + (range_size * 0.618)
    ote_705 = sl_price + (range_size * 0.705)
    ote_790 = sl_price + (range_size * 0.790)
    
    print(f"\n  OTE Zone (untuk SELL - retracement naik):")
    print(f"    79.0% = {ote_790:.2f}")
    print(f"    70.5% = {ote_705:.2f}  << sweet spot")
    print(f"    61.8% = {ote_618:.2f}")
    print(f"    OTE Zone = {ote_618:.2f} - {ote_790:.2f}")
    
    print(f"\n  FVG Zone = 4505.19 - 4505.72")
    
    # Cek overlap
    fvg_low, fvg_high = 4505.19, 4505.72
    if fvg_low <= ote_790 and fvg_high >= ote_618:
        print(f"\n  >>> FVG dan OTE OVERLAP! Confluence zone!")
    elif fvg_high < ote_618:
        print(f"\n  >>> FVG di BAWAH OTE zone (FVG {fvg_high:.2f} < OTE {ote_618:.2f})")
    elif fvg_low > ote_790:
        print(f"\n  >>> FVG di ATAS OTE zone (FVG {fvg_low:.2f} > OTE {ote_790:.2f})")
    
    print(f"\n  Entry di OTE:")
    print(f"    Entry SELL: {ote_618:.2f} - {ote_790:.2f}")
    print(f"    SL: di atas Swing High {sh:.2f}")
    print(f"    TP: di bawah Swing Low {sl_price:.2f}")
    
    risk = sh - ote_705
    reward = ote_705 - sl_price
    print(f"\n    Risk  = {sh:.2f} - {ote_705:.2f} = {risk:.2f}")
    print(f"    Reward = {ote_705:.2f} - {sl_price:.2f} = {reward:.2f}")
    print(f"    R:R = 1 : {reward/risk:.1f}")
