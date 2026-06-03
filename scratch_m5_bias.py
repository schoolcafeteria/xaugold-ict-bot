"""Quick diagnostic: Kenapa M5 bias bullish?"""
import json, sys
sys.path.insert(0, ".")
from tradingview_tool import fetch_xauusd_data
from smc_local import analyze_smc, aggregate_m1_to_m5
from datetime import datetime

print("⏳ Fetching data...")
data = fetch_xauusd_data(symbol="FOREXCOM:XAUUSD", timeframe="5", limit=500, range_val=500)
candles = data['candles']
print(f"M1 candles: {len(candles)}")

# Aggregate ke M5
candles_m5 = aggregate_m1_to_m5(candles)
print(f"M5 candles: {len(candles_m5)}")

# Analisis SMC pada M5
smc_m5 = analyze_smc(candles_m5)

print(f"\n{'='*60}")
print(f"M5 BIAS: {smc_m5['market_bias'].upper()}")
print(f"{'='*60}")

# Tampilkan 10 BOS terakhir
bos = smc_m5['bos_events']
print(f"\n📊 Total BOS events: {len(bos)}")
print(f"--- 10 BOS Terakhir ---")
for b in bos[-10:]:
    t = datetime.fromtimestamp(b['time']).strftime('%H:%M') if isinstance(b['time'], (int,float)) else b['time']
    print(f"  [{t}] {b['type'].upper():15s} | Break price={b['price']:.2f} | Close={b['close']:.2f}")

# Tampilkan 10 CHoCH terakhir
choch = smc_m5['choch_events']
print(f"\n🔄 Total CHoCH events: {len(choch)}")
print(f"--- 10 CHoCH Terakhir ---")
for c in choch[-10:]:
    t = datetime.fromtimestamp(c['time']).strftime('%H:%M') if isinstance(c['time'], (int,float)) else c['time']
    print(f"  [{t}] {c['type'].upper():15s} | Break price={c['price']:.2f} | Close={c['close']:.2f}")

# Event paling terakhir yang menentukan bias
print(f"\n{'='*60}")
print("🎯 EVENT PENENTU BIAS:")
last_bos = bos[-1] if bos else None
last_choch = choch[-1] if choch else None

if last_bos and last_choch:
    if last_choch['bar_index'] > last_bos['bar_index']:
        winner = last_choch
        source = "CHoCH"
    else:
        winner = last_bos
        source = "BOS"
elif last_choch:
    winner = last_choch
    source = "CHoCH"
elif last_bos:
    winner = last_bos
    source = "BOS"
else:
    winner = None
    source = "None"

if winner:
    t = datetime.fromtimestamp(winner['time']).strftime('%d/%m %H:%M') if isinstance(winner['time'], (int,float)) else winner['time']
    print(f"  {source}: {winner['type'].upper()} pada {t}")
    print(f"  Break price: {winner['price']:.2f} | Close: {winner['close']:.2f}")
    print(f"  Bar index: {winner['bar_index']} / {len(candles_m5)-1}")
    bars_ago = len(candles_m5) - 1 - winner['bar_index']
    print(f"  {bars_ago} candle M5 yang lalu (~{bars_ago*5} menit)")
print(f"{'='*60}")

# Juga cek M1 untuk perbandingan
smc_m1 = analyze_smc(candles)
last_bos_m1 = smc_m1['bos_events'][-1] if smc_m1['bos_events'] else None
last_choch_m1 = smc_m1['choch_events'][-1] if smc_m1['choch_events'] else None
print(f"\n📌 Perbandingan M1 bias: {smc_m1['market_bias'].upper()}")
if last_bos_m1:
    t = datetime.fromtimestamp(last_bos_m1['time']).strftime('%H:%M') if isinstance(last_bos_m1['time'], (int,float)) else last_bos_m1['time']
    print(f"  Last M1 BOS: {last_bos_m1['type']} pada {t}")
if last_choch_m1:
    t = datetime.fromtimestamp(last_choch_m1['time']).strftime('%H:%M') if isinstance(last_choch_m1['time'], (int,float)) else last_choch_m1['time']
    print(f"  Last M1 CHoCH: {last_choch_m1['type']} pada {t}")
