"""Detail candle pembentuk FVG Bullish 10:09"""
import sys
sys.path.insert(0, ".")
from tradingview_tool import fetch_xauusd_data
from datetime import datetime, timedelta, timezone

data = fetch_xauusd_data(symbol="FOREXCOM:XAUUSD", timeframe="5", limit=500, range_val=500)
candles = data["candles"]

for i in range(1, len(candles) - 1):
    c1, c2, c3 = candles[i - 1], candles[i], candles[i + 1]
    if c3["low"] > c1["high"]:
        t = datetime.fromtimestamp(c2["time"], tz=timezone.utc) + timedelta(hours=7)
        if t.hour == 10 and 8 <= t.minute <= 10:
            def fmt(ts):
                return (datetime.fromtimestamp(ts, tz=timezone.utc) + timedelta(hours=7)).strftime("%H:%M")

            print(f"Candle 1 [{fmt(c1['time'])}]: O={c1['open']:.2f}  H={c1['high']:.2f}  L={c1['low']:.2f}  C={c1['close']:.2f}")
            print(f"Candle 2 [{fmt(c2['time'])}]: O={c2['open']:.2f}  H={c2['high']:.2f}  L={c2['low']:.2f}  C={c2['close']:.2f}")
            print(f"Candle 3 [{fmt(c3['time'])}]: O={c3['open']:.2f}  H={c3['high']:.2f}  L={c3['low']:.2f}  C={c3['close']:.2f}")
            print()
            print(f"HIGH Candle 1 = {c1['high']:.2f}  (batas atas candle sebelum impulse)")
            print(f"LOW  Candle 3 = {c3['low']:.2f}  (batas bawah candle sesudah impulse)")
            print(f"GAP          = {c3['low'] - c1['high']:.2f}")
            print(f"FVG Zone     = {c1['high']:.2f} - {c3['low']:.2f}")
            break
