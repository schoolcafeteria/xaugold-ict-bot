"""
SMC Local Engine - Kalkulasi Smart Money Concepts dari data OHLC mentah.

Modul ini adalah fallback (Lapis 2) jika data dari indikator LuxAlgo SMC
melalui TradingView WebSocket tidak tersedia atau tidak lengkap.

Fungsi utama:
- detect_swing_points: Mendeteksi Swing High dan Swing Low
- detect_bos: Mendeteksi Break of Structure (BOS)
- detect_choch: Mendeteksi Change of Character (CHoCH)
- detect_order_blocks: Mendeteksi zona Order Block aktif
- analyze_smc: Fungsi utama yang menjalankan semua deteksi
"""

import pandas as pd
from typing import List, Dict, Optional


def detect_swing_points(df: pd.DataFrame, lookback: int = 5) -> pd.DataFrame:
    """
    Mendeteksi Swing High dan Swing Low.

    Swing High: Candle yang high-nya lebih tinggi dari semua candle
                di kiri dan kanan dalam jarak lookback.
    Swing Low:  Candle yang low-nya lebih rendah dari semua candle
                di kiri dan kanan dalam jarak lookback.

    Args:
        df: DataFrame dengan kolom 'high' dan 'low'
        lookback: Jumlah candle ke kiri/kanan untuk validasi swing

    Returns:
        DataFrame dengan kolom tambahan 'swing_high' dan 'swing_low' (boolean)
    """
    df = df.copy()
    df['swing_high'] = False
    df['swing_low'] = False

    for i in range(lookback, len(df) - lookback):
        # Cek swing high
        high = df.iloc[i]['high']
        is_swing_high = all(
            high > df.iloc[i - j]['high'] and high > df.iloc[i + j]['high']
            for j in range(1, lookback + 1)
        )
        if is_swing_high:
            df.iloc[i, df.columns.get_loc('swing_high')] = True

        # Cek swing low
        low = df.iloc[i]['low']
        is_swing_low = all(
            low < df.iloc[i - j]['low'] and low < df.iloc[i + j]['low']
            for j in range(1, lookback + 1)
        )
        if is_swing_low:
            df.iloc[i, df.columns.get_loc('swing_low')] = True

    return df


def detect_bos(df: pd.DataFrame) -> List[Dict]:
    """
    Mendeteksi Break of Structure (BOS).

    BOS Bullish: Harga menembus (close di atas) swing high sebelumnya
                 saat tren sedang naik (konfirmasi kelanjutan tren naik).
    BOS Bearish: Harga menembus (close di bawah) swing low sebelumnya
                 saat tren sedang turun (konfirmasi kelanjutan tren turun).

    Args:
        df: DataFrame dengan kolom 'swing_high' dan 'swing_low'

    Returns:
        List of dicts dengan detail BOS event
    """
    bos_events = []
    last_swing_high = None
    last_swing_low = None
    last_swing_high_idx = None
    last_swing_low_idx = None

    for i in range(len(df)):
        row = df.iloc[i]

        # Update swing points terbaru
        if row['swing_high']:
            last_swing_high = row['high']
            last_swing_high_idx = i

        if row['swing_low']:
            last_swing_low = row['low']
            last_swing_low_idx = i

        # Cek BOS Bullish: close menembus swing high terakhir
        if last_swing_high is not None and row['close'] > last_swing_high:
            bos_events.append({
                'type': 'bos_bullish',
                'bar_index': i,
                'time': row.get('time', i),
                'price': last_swing_high,
                'close': row['close'],
                'swing_bar_index': last_swing_high_idx,
            })
            last_swing_high = None  # Reset agar tidak trigger berulang

        # Cek BOS Bearish: close menembus swing low terakhir
        if last_swing_low is not None and row['close'] < last_swing_low:
            bos_events.append({
                'type': 'bos_bearish',
                'bar_index': i,
                'time': row.get('time', i),
                'price': last_swing_low,
                'close': row['close'],
                'swing_bar_index': last_swing_low_idx,
            })
            last_swing_low = None  # Reset agar tidak trigger berulang

    return bos_events


def detect_choch(df: pd.DataFrame) -> List[Dict]:
    """
    Mendeteksi Change of Character (CHoCH).

    CHoCH Bullish: Dalam tren turun (membuat Lower Low), harga tiba-tiba
                   menembus Higher High → sinyal pembalikan ke tren naik.
    CHoCH Bearish: Dalam tren naik (membuat Higher High), harga tiba-tiba
                   menembus Lower Low → sinyal pembalikan ke tren turun.

    Args:
        df: DataFrame dengan kolom 'swing_high' dan 'swing_low'

    Returns:
        List of dicts dengan detail CHoCH event
    """
    choch_events = []

    # Kumpulkan semua swing points berurutan
    swings = []
    for i in range(len(df)):
        row = df.iloc[i]
        if row['swing_high']:
            swings.append({'type': 'high', 'price': row['high'], 'index': i, 'time': row.get('time', i)})
        if row['swing_low']:
            swings.append({'type': 'low', 'price': row['low'], 'index': i, 'time': row.get('time', i)})

    if len(swings) < 4:
        return choch_events

    # Tentukan tren berdasarkan swing points
    for i in range(2, len(swings)):
        prev = swings[i - 2]
        curr = swings[i]

        # CHoCH Bullish: dua swing low berurutan membuat LL, lalu swing high menembus HH
        if prev['type'] == 'low' and curr['type'] == 'low' and curr['price'] < prev['price']:
            # Kita dalam tren turun (Lower Low)
            # Cari apakah harga setelahnya menembus swing high terakhir
            last_high = None
            for s in swings:
                if s['type'] == 'high' and s['index'] < curr['index']:
                    last_high = s

            if last_high is not None:
                # Cek apakah ada candle setelah LL yang close di atas last_high
                for j in range(curr['index'] + 1, min(curr['index'] + 20, len(df))):
                    if df.iloc[j]['close'] > last_high['price']:
                        choch_events.append({
                            'type': 'choch_bullish',
                            'bar_index': j,
                            'time': df.iloc[j].get('time', j),
                            'price': last_high['price'],
                            'close': df.iloc[j]['close'],
                        })
                        break

        # CHoCH Bearish: dua swing high berurutan membuat HH, lalu harga menembus HL
        if prev['type'] == 'high' and curr['type'] == 'high' and curr['price'] > prev['price']:
            # Kita dalam tren naik (Higher High)
            last_low = None
            for s in swings:
                if s['type'] == 'low' and s['index'] < curr['index']:
                    last_low = s

            if last_low is not None:
                for j in range(curr['index'] + 1, min(curr['index'] + 20, len(df))):
                    if df.iloc[j]['close'] < last_low['price']:
                        choch_events.append({
                            'type': 'choch_bearish',
                            'bar_index': j,
                            'time': df.iloc[j].get('time', j),
                            'price': last_low['price'],
                            'close': df.iloc[j]['close'],
                        })
                        break

    return choch_events


def detect_order_blocks(df: pd.DataFrame, bos_events: List[Dict]) -> List[Dict]:
    """
    Mendeteksi Order Blocks.

    Order Block = candle terakhir yang berlawanan arah sebelum pergerakan
    impulsif (BOS). Ini adalah zona di mana institusi besar kemungkinan
    menempatkan order mereka.

    Bullish OB: Candle bearish terakhir sebelum BOS bullish
    Bearish OB: Candle bullish terakhir sebelum BOS bearish

    Args:
        df: DataFrame dengan data OHLC
        bos_events: List dari BOS events yang terdeteksi

    Returns:
        List of dicts dengan detail Order Block
    """
    order_blocks = []

    for bos in bos_events:
        bos_idx = bos['bar_index']

        if bos['type'] == 'bos_bullish':
            # Cari candle bearish terakhir sebelum BOS
            for j in range(bos_idx - 1, max(bos_idx - 15, 0), -1):
                candle = df.iloc[j]
                if candle['close'] < candle['open']:  # Candle bearish
                    order_blocks.append({
                        'type': 'bullish_ob',
                        'bar_index': j,
                        'time': candle.get('time', j),
                        'high': candle['high'],
                        'low': candle['low'],
                        'open': candle['open'],
                        'close': candle['close'],
                        'bos_bar_index': bos_idx,
                        'active': True,
                    })
                    break

        elif bos['type'] == 'bos_bearish':
            # Cari candle bullish terakhir sebelum BOS
            for j in range(bos_idx - 1, max(bos_idx - 15, 0), -1):
                candle = df.iloc[j]
                if candle['close'] > candle['open']:  # Candle bullish
                    order_blocks.append({
                        'type': 'bearish_ob',
                        'bar_index': j,
                        'time': candle.get('time', j),
                        'high': candle['high'],
                        'low': candle['low'],
                        'open': candle['open'],
                        'close': candle['close'],
                        'bos_bar_index': bos_idx,
                        'active': True,
                    })
                    break

    # Tandai OB yang sudah dilanggar (mitigated)
    for ob in order_blocks:
        for i in range(ob['bos_bar_index'] + 1, len(df)):
            candle = df.iloc[i]
            if ob['type'] == 'bullish_ob' and candle['close'] < ob['low']:
                ob['active'] = False
                break
            elif ob['type'] == 'bearish_ob' and candle['close'] > ob['high']:
                ob['active'] = False
                break

    return order_blocks


def analyze_smc(candles: List[Dict], swing_lookback: int = 5) -> Dict:
    """
    Fungsi utama: Jalankan semua deteksi SMC dari data OHLC.

    Args:
        candles: List of dicts dengan keys: time, open, high, low, close, volume
        swing_lookback: Parameter sensitivitas swing point detection

    Returns:
        Dict berisi semua hasil analisis SMC
    """
    df = pd.DataFrame(candles)

    # 1. Deteksi swing points
    df = detect_swing_points(df, lookback=swing_lookback)

    # 2. Deteksi BOS
    bos_events = detect_bos(df)

    # 3. Deteksi CHoCH
    choch_events = detect_choch(df)

    # 4. Deteksi Order Blocks
    order_blocks = detect_order_blocks(df, bos_events)

    # 5. Filter hanya OB aktif
    active_obs = [ob for ob in order_blocks if ob['active']]

    # 6. Tentukan bias pasar saat ini
    recent_bos = bos_events[-1] if bos_events else None
    recent_choch = choch_events[-1] if choch_events else None

    market_bias = 'neutral'
    if recent_choch:
        if recent_choch['type'] == 'choch_bullish':
            market_bias = 'bullish'
        elif recent_choch['type'] == 'choch_bearish':
            market_bias = 'bearish'
    elif recent_bos:
        if recent_bos['type'] == 'bos_bullish':
            market_bias = 'bullish'
        elif recent_bos['type'] == 'bos_bearish':
            market_bias = 'bearish'

    return {
        'swing_highs': df[df['swing_high']].index.tolist(),
        'swing_lows': df[df['swing_low']].index.tolist(),
        'bos_events': bos_events,
        'choch_events': choch_events,
        'order_blocks': order_blocks,
        'active_order_blocks': active_obs,
        'market_bias': market_bias,
        'summary': {
            'total_bos': len(bos_events),
            'total_choch': len(choch_events),
            'total_order_blocks': len(order_blocks),
            'active_order_blocks': len(active_obs),
            'current_bias': market_bias,
        }
    }


if __name__ == '__main__':
    import json
    import sys

    # Untuk testing mandiri: baca data dari stdin atau file
    if len(sys.argv) > 1:
        with open(sys.argv[1], 'r') as f:
            data = json.load(f)
    else:
        data = json.load(sys.stdin)

    candles = data.get('candles', [])
    result = analyze_smc(candles)
    print(json.dumps(result, indent=2, default=str))
