import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime, timezone
import sys
sys.path.append(r"f:\XAUGOLD 2")
from smc_local import analyze_smc
from config import MT5_SYMBOL

if not mt5.initialize():
    print("Gagal init MT5:", mt5.last_error())
    exit()

# Ambil 300 candle M5 terbaru
rates = mt5.copy_rates_from_pos(MT5_SYMBOL, mt5.TIMEFRAME_M5, 0, 300)
mt5.shutdown()

df = pd.DataFrame(rates)
df['ema_200'] = df['close'].ewm(span=200, adjust=False).mean()
delta = df['close'].diff()
gain = delta.where(delta > 0, 0).rolling(14).mean()
loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
df['rsi_14'] = 100 - (100 / (1 + gain / loss))
hl = df['high'] - df['low']
hc = np.abs(df['high'] - df['close'].shift())
lc = np.abs(df['low'] - df['close'].shift())
df['atr_14'] = pd.concat([hl, hc, lc], axis=1).max(axis=1).rolling(14).mean()
df = df.replace({np.nan: None})

candles = df[['time','open','high','low','close','tick_volume','ema_200','rsi_14','atr_14']].rename(columns={'tick_volume':'volume'}).to_dict('records')

smc = analyze_smc(candles)
last = candles[-1]
price = last['close']
ema = last.get('ema_200')
rsi = last.get('rsi_14')
bias = smc.get('market_bias', 'neutral')
obs = smc.get('active_order_blocks', [])

ema_pos = "di ATAS ✅" if ema and price > ema else "di BAWAH ❌"
bias_icon = "🟢" if bias == "bullish" else "🔴" if bias == "bearish" else "⚪"

print(f"💰 Harga saat ini : {price:.2f}")
print(f"📊 EMA 200        : {ema:.2f} (harga {ema_pos} EMA)" if ema else "EMA 200: N/A")
print(f"📈 RSI(14)        : {rsi:.1f}" if rsi else "RSI: N/A")
print(f"{bias_icon} Market Bias    : {bias.upper()}")
print(f"\n🧱 ORDER BLOCK AKTIF: {len(obs)}")
print("-" * 45)
for i, ob in enumerate(obs):
    t = "🟢 Bullish OB" if ob['type'] == 'bullish_ob' else "🔴 Bearish OB"
    mid = (ob['high'] + ob['low']) / 2
    dist = abs(price - mid)
    in_zone = ob['low'] <= price <= ob['high']
    if ob['type'] == 'bullish_ob':
        gap = max(0, price - ob['high'])
        note = "🎯 Harga SUDAH DI ZONA!" if in_zone else f"Harga perlu turun {gap:.2f}"
    else:
        gap = max(0, ob['low'] - price)
        note = "🎯 Harga SUDAH DI ZONA!" if in_zone else f"Harga perlu naik {gap:.2f}"
    print(f"{t} #{i+1}: {ob['low']:.2f} - {ob['high']:.2f}")
    print(f"   Jarak: {dist:.2f} | {note}")
