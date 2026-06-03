"""Detect FVG (Fair Value Gap) di market XAUUSD sekarang"""
import sys
sys.path.insert(0, ".")
from tradingview_tool import fetch_xauusd_data
from smc_local import aggregate_m1_to_m5
from datetime import datetime, timedelta

print("Fetching data...")
data = fetch_xauusd_data(symbol="FOREXCOM:XAUUSD", timeframe="5", limit=500, range_val=500)
candles = data['candles']
current_price = candles[-1]['close']

def detect_fvg(candles_list, label=""):
    """Deteksi FVG dari list of candle dicts."""
    fvgs = []
    for i in range(1, len(candles_list) - 1):
        c1 = candles_list[i - 1]  # Candle sebelumnya
        c2 = candles_list[i]      # Candle impulse (tengah)
        c3 = candles_list[i + 1]  # Candle sesudahnya

        # Bullish FVG: candle naik kuat, ada gap antara high c1 dan low c3
        if c3['low'] > c1['high']:
            fvgs.append({
                'type': 'bullish_fvg',
                'high': c3['low'],       # Atas gap
                'low': c1['high'],        # Bawah gap
                'time': c2.get('time', i),
                'bar_index': i,
                'filled': False,
            })

        # Bearish FVG: candle turun kuat, ada gap antara low c1 dan high c3
        if c3['high'] < c1['low']:
            fvgs.append({
                'type': 'bearish_fvg',
                'high': c1['low'],        # Atas gap
                'low': c3['high'],         # Bawah gap
                'time': c2.get('time', i),
                'bar_index': i,
                'filled': False,
            })

    # Cek apakah FVG sudah terisi (mitigated)
    for fvg in fvgs:
        for j in range(fvg['bar_index'] + 2, len(candles_list)):
            c = candles_list[j]
            if fvg['type'] == 'bullish_fvg' and c['low'] <= fvg['low']:
                fvg['filled'] = True
                break
            elif fvg['type'] == 'bearish_fvg' and c['high'] >= fvg['high']:
                fvg['filled'] = True
                break

    return fvgs

def format_time(ts):
    if isinstance(ts, (int, float)):
        return (datetime.utcfromtimestamp(ts) + timedelta(hours=7)).strftime('%d/%m %H:%M')
    return str(ts)

# ===== M1 FVG =====
fvgs_m1 = detect_fvg(candles)
active_m1 = [f for f in fvgs_m1 if not f['filled']]
print(f"\n{'='*65}")
print(f"HARGA SEKARANG: {current_price:.2f}")
print(f"{'='*65}")

print(f"\n--- M1 FVG: {len(fvgs_m1)} total, {len(active_m1)} aktif (belum terisi) ---")
# Tampilkan FVG aktif yang dekat harga (dalam 20 poin)
nearby_m1 = [f for f in active_m1 if abs(current_price - (f['high']+f['low'])/2) < 20]
nearby_m1.sort(key=lambda x: abs(current_price - (x['high']+x['low'])/2))

for f in nearby_m1[:15]:
    t = format_time(f['time'])
    gap_size = f['high'] - f['low']
    dist = current_price - (f['high'] + f['low']) / 2
    icon = "UP" if f['type'] == 'bullish_fvg' else "DN"
    arrow = "^" if dist > 0 else "v"
    print(f"  [{t}] {icon} {f['low']:.2f} - {f['high']:.2f} (gap={gap_size:.2f}) | jarak={abs(dist):.2f} {arrow}")

# ===== M5 FVG =====
candles_m5 = aggregate_m1_to_m5(candles)
fvgs_m5 = detect_fvg(candles_m5)
active_m5 = [f for f in fvgs_m5 if not f['filled']]

print(f"\n--- M5 FVG: {len(fvgs_m5)} total, {len(active_m5)} aktif (belum terisi) ---")
nearby_m5 = [f for f in active_m5 if abs(current_price - (f['high']+f['low'])/2) < 30]
nearby_m5.sort(key=lambda x: abs(current_price - (x['high']+x['low'])/2))

for f in nearby_m5[:15]:
    t = format_time(f['time'])
    gap_size = f['high'] - f['low']
    dist = current_price - (f['high'] + f['low']) / 2
    icon = "UP" if f['type'] == 'bullish_fvg' else "DN"
    arrow = "^" if dist > 0 else "v"
    print(f"  [{t}] {icon} {f['low']:.2f} - {f['high']:.2f} (gap={gap_size:.2f}) | jarak={abs(dist):.2f} {arrow}")

# ===== Visualisasi terdekat =====
print(f"\n{'='*65}")
print("PETA FVG TERDEKAT (M5):")
print(f"{'='*65}")

all_nearby = sorted(nearby_m5[:10], key=lambda x: -x['high'])
for f in all_nearby:
    mid = (f['high'] + f['low']) / 2
    icon = "Bullish FVG (buy zone)" if f['type'] == 'bullish_fvg' else "Bearish FVG (sell zone)"
    marker = " <<< HARGA DI SINI" if f['low'] <= current_price <= f['high'] else ""
    print(f"  {f['high']:.2f} ----+")
    print(f"            | {icon}{marker}")
    print(f"  {f['low']:.2f} ----+")
    print()

print(f"  >>> Harga saat ini: {current_price:.2f}")
