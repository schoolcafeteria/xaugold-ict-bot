"""Verifikasi: apakah FVG entry & TP tercapai, sedangkan OTE belum entry?"""
import sys
sys.path.insert(0, ".")
from tradingview_tool import fetch_xauusd_data
from smc_local import aggregate_m1_to_m5
from datetime import datetime, timedelta, timezone

data = fetch_xauusd_data(symbol="FOREXCOM:XAUUSD", timeframe="5", limit=500, range_val=500)
candles_m5 = aggregate_m1_to_m5(data["candles"])

def fmt(ts):
    return (datetime.fromtimestamp(ts, tz=timezone.utc) + timedelta(hours=7)).strftime("%H:%M")

# FVG terbentuk saat candle 3 close (bar 10:35)
# Cari bar 10:35 dan setelahnya
fvg_low = 4505.19
fvg_high = 4505.72
ote_low = 4505.92
ote_high = 4508.68

print("=== PRICE ACTION SETELAH FVG TERBENTUK (10:35+) ===\n")
print(f"FVG Zone: {fvg_low} - {fvg_high}")
print(f"OTE Zone: {ote_low} - {ote_high}")
print()

fvg_entry = None
fvg_tp_price = None
ote_entry = None

for c in candles_m5:
    t = datetime.fromtimestamp(c["time"], tz=timezone.utc) + timedelta(hours=7)
    if t.day == 27 and t.hour >= 10 and t.minute >= 35:
        touched_fvg = c["high"] >= fvg_low
        touched_ote = c["high"] >= ote_low
        
        marker = ""
        if touched_ote and ote_entry is None:
            ote_entry = c
            marker += " << OTE ENTRY"
        if touched_fvg and fvg_entry is None:
            fvg_entry = c
            marker += " << FVG ENTRY"
            fvg_tp_price = fvg_low - (fvg_high - fvg_low) * 2.5  # TP 2.5x
        
        print(f"  [{fmt(c['time'])}] O={c['open']:.2f} H={c['high']:.2f} L={c['low']:.2f} C={c['close']:.2f}{marker}")

print()
print("=" * 60)
print("HASIL:")
print()

if fvg_entry:
    tp = fvg_low - (fvg_high - fvg_low) * 2.5
    sl = fvg_high
    print(f"FVG Entry: SELL di {fvg_low:.2f} [{fmt(fvg_entry['time'])}]")
    print(f"  SL: {sl:.2f} | TP: {tp:.2f}")
    # Cek TP hit
    tp_hit = False
    for c in candles_m5:
        t = datetime.fromtimestamp(c["time"], tz=timezone.utc) + timedelta(hours=7)
        if t.day == 27 and c["time"] > fvg_entry["time"]:
            if c["low"] <= tp:
                tp_hit = True
                print(f"  TP HIT! [{fmt(c['time'])}] Low={c['low']:.2f}")
                break
            if c["high"] >= sl:
                print(f"  SL HIT! [{fmt(c['time'])}] High={c['high']:.2f}")
                break
    if not tp_hit:
        print(f"  TP belum tercapai. Harga terakhir: {candles_m5[-1]['close']:.2f}")
else:
    print("FVG Entry: TIDAK TERPICU (harga tidak pernah sentuh FVG setelah terbentuk)")

print()
if ote_entry:
    print(f"OTE Entry: SELL di {ote_low:.2f} [{fmt(ote_entry['time'])}]")
else:
    print("OTE Entry: TIDAK TERPICU (harga tidak pernah naik ke OTE zone)")
    print(f"  Harga tertinggi setelah 10:35: ", end="")
    max_high = 0
    for c in candles_m5:
        t = datetime.fromtimestamp(c["time"], tz=timezone.utc) + timedelta(hours=7)
        if t.day == 27 and t.hour >= 10 and t.minute >= 35:
            if c["high"] > max_high:
                max_high = c["high"]
    print(f"{max_high:.2f} (OTE butuh {ote_low:.2f})")
