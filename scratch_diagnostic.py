import json
from datetime import datetime, timezone, timedelta
from tradingview_tool import fetch_xauusd_data
from smc_local import analyze_smc

def diagnose_today():
    print("⏳ Mengambil data live 1M XAUUSD (350 candle terakhir)...")
    # Tarik 350 candle agar EMA 200 terisi penuh
    data = fetch_xauusd_data(symbol="FOREXCOM:XAUUSD", timeframe="5", limit=500, range_val=500)
    
    if 'error' in data:
        print("❌ Error fetching data:", data['error'])
        return
        
    candles = data.get('candles', [])
    if not candles:
        print("❌ Tidak ada data candle.")
        return
        
    print(f"📊 Berhasil mengambil {len(candles)} candle.")
    
    # Filter lilin yang terjadi dari jam 08:00 WIB hingga sekarang (25 Mei 2026)
    target_date_str = "2026-05-25"
    target_start_hour = 8
    
    active_period_candles = []
    
    for c in candles:
        # Konversi timestamp TV (UTC) ke WIB
        dt_wib = datetime.fromtimestamp(c['time'], tz=timezone.utc) + timedelta(hours=7)
        c_date = dt_wib.strftime('%Y-%m-%d')
        c_hour = dt_wib.hour
        
        # Simpan jika tanggalnya hari ini dan jam >= 08:00 WIB
        if c_date == target_date_str and c_hour >= target_start_hour:
            c['wib_time'] = dt_wib.strftime('%H:%M:%S')
            active_period_candles.append(c)
            
    print(f"🔍 Jumlah candle terdeteksi sejak 08:00 WIB hari ini: {len(active_period_candles)}")
    
    if not active_period_candles:
        print("⚠️ Tidak ada candle hari ini yang masuk di atas pukul 08:00 WIB.")
        return
        
    # Jalankan simulasi loop sinyal SMC dari jam 08:00 WIB ke depan
    print("\n--- ANALISIS SINYAL TIAP CANDLE (SEJAK 08:00 WIB) ---")
    signals_found = 0
    
    # Untuk menganalisis sinyal secara akurat, kita harus memproses lilin satu per satu secara historis
    for i in range(len(candles) - len(active_period_candles), len(candles)):
        candles_subset = candles[:i+1]
        latest_c = candles_subset[-1]
        
        smc = analyze_smc(candles_subset)
        market_bias = smc.get('market_bias', 'neutral')
        active_obs = smc.get('active_order_blocks', [])
        
        rsi = latest_c.get('rsi_14')
        ema_200 = latest_c.get('ema_200')
        atr = latest_c.get('atr_14')
        current_price = latest_c['close']
        
        if ema_200 is None or atr is None:
            continue  # Lewati jika indikator belum terisi lengkap
            
        wib_time = latest_c.get('wib_time', 'N/A')
        
        # Cari retest
        for ob in active_obs:
            if ob['type'] == 'bullish_ob' and market_bias in ('bullish', 'neutral'):
                # Retest check
                if latest_c['low'] <= ob['high'] and latest_c['close'] > ob['low']:
                    # EMA 200 filter
                    if current_price > ema_200:
                        if rsi and rsi > 70:
                            print(f"⚠️ [BUY RETEST DIBATALKAN (RSI Overbought: {rsi:.2f})] Waktu: {wib_time} | Harga: {current_price} | OB High: {ob['high']}")
                            continue
                        print(f"🎯 [BUY SIGNAL!] Waktu: {wib_time} | Harga: {current_price} | OB Zone: {ob['low']} - {ob['high']} | EMA 200: {ema_200:.2f} | RSI: {rsi:.2f}")
                        signals_found += 1
                        
            elif ob['type'] == 'bearish_ob' and market_bias in ('bearish', 'neutral'):
                # Retest check
                if latest_c['high'] >= ob['low'] and latest_c['close'] < ob['high']:
                    # EMA 200 filter
                    if current_price < ema_200:
                        if rsi and rsi < 30:
                            print(f"⚠️ [SELL RETEST DIBATALKAN (RSI Oversold: {rsi:.2f})] Waktu: {wib_time} | Harga: {current_price} | OB Low: {ob['low']}")
                            continue
                        print(f"🎯 [SELL SIGNAL!] Waktu: {wib_time} | Harga: {current_price} | OB Zone: {ob['low']} - {ob['high']} | EMA 200: {ema_200:.2f} | RSI: {rsi:.2f}")
                        signals_found += 1

    print(f"\n📊 KESIMPULAN: Ditemukan {signals_found} sinyal masuk valid sejak jam 08:00 WIB.")

if __name__ == '__main__':
    diagnose_today()
