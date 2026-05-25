import json
from datetime import datetime, timezone, timedelta
from tradingview_tool import fetch_xauusd_data
from smc_local import analyze_smc

def print_status():
    print("⏳ Menarik status pasar emas terupdate...")
    data = fetch_xauusd_data(symbol="FOREXCOM:XAUUSD", timeframe="1", limit=300, range_val=300)
    
    if 'error' in data:
        print("❌ Error:", data['error'])
        return
        
    candles = data.get('candles', [])
    if not candles:
        print("❌ Tidak ada data candle.")
        return
        
    latest_c = candles[-1]
    dt_wib = datetime.fromtimestamp(latest_c['time'], tz=timezone.utc) + timedelta(hours=7)
    time_str = dt_wib.strftime('%H:%M:%S WIB')
    
    smc = analyze_smc(candles)
    market_bias = smc.get('market_bias', 'neutral')
    active_obs = smc.get('active_order_blocks', [])
    
    rsi = latest_c.get('rsi_14')
    ema_200 = latest_c.get('ema_200')
    current_price = latest_c['close']
    
    print("\n==============================================")
    print(f"📊 LIVE MARKET STATUS ({time_str})")
    print("==============================================")
    print(f"💵 Harga Live Emas: {current_price}")
    print(f"📈 Tren EMA 200: {f'{ema_200:.2f}' if ema_200 else 'N/A'}")
    print(f"🔍 Bias Pasar (SMC): {market_bias.upper()}")
    print(f"⚡ RSI 14: {f'{rsi:.2f}' if rsi else 'N/A'}")
    
    print("\n🧱 ACTIVE ORDER BLOCKS:")
    if not active_obs:
        print("   - Tidak ada Order Block aktif saat ini.")
    else:
        for ob in active_obs:
            ob_type = "BULLISH (BUY ZONE)" if ob['type'] == 'bullish_ob' else "BEARISH (SELL ZONE)"
            print(f"   ▪️ Tipe: {ob_type}")
            print(f"     Zona Harga: {ob['low']} - {ob['high']}")
            # Hitung jarak harga ke zona
            if ob['type'] == 'bullish_ob':
                dist = current_price - ob['high']
                print(f"     Jarak ke batas atas zona: {dist:.2f} USD")
            else:
                dist = ob['low'] - current_price
                print(f"     Jarak ke batas bawah zona: {dist:.2f} USD")
    print("==============================================\n")

if __name__ == '__main__':
    print_status()
