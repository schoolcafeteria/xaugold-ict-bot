"""
TradingView Tool - Tool kustom untuk Hermes Agent

Menyediakan dua tool utama:
1. fetch_xauusd_analysis: Mengambil data OHLC + indikator + SMC dari TradingView
2. run_backtest: Menjalankan simulasi backtest pada data historis

Tool ini menghubungkan Node.js fetcher (xauusd_fetcher.js) dengan
Python backtester (backtester.py) melalui subprocess.
"""

import json
import subprocess
import sys
import os
from typing import Dict, Optional
from pathlib import Path

# Direktori proyek (tempat script ini berada)
PROJECT_DIR = Path(__file__).parent.resolve()


def fetch_xauusd_data(
    symbol: str = 'FOREXCOM:XAUUSD',
    timeframe: str = '5',
    limit: int = 200,
    to_date: Optional[str] = None,
    range_val: Optional[int] = None,
) -> Dict:
    """
    Mengambil data OHLC + indikator teknikal + SMC dari TradingView
    menggunakan script Node.js (xauusd_fetcher.js).

    Args:
        symbol: Simbol TradingView (default: OANDA:XAUUSD)
        timeframe: Timeframe dalam menit (default: 5)
        limit: Jumlah candle yang diambil (default: 200)
        to_date: Tanggal akhir data (format: YYYY-MM-DD, opsional)
        range_val: Jumlah bar yang diminta ke TradingView (opsional)

    Returns:
        Dict berisi data candle, indikator, dan SMC
    """
    fetcher_path = PROJECT_DIR / 'xauusd_fetcher.js'

    if not fetcher_path.exists():
        return {'error': f'Fetcher script tidak ditemukan: {fetcher_path}'}

    try:
        cmd = ['node', str(fetcher_path), symbol, str(timeframe), str(limit)]
        if to_date:
            cmd.extend(['--to', to_date])
        if range_val:
            cmd.extend(['--range', str(range_val)])

        # CREATE_NO_WINDOW mencegah CMD window muncul di Windows setiap kali fetch data
        creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(PROJECT_DIR),
            creationflags=creation_flags,
        )

        if result.returncode != 0:
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                return {
                    'error': f'Fetcher error (exit code {result.returncode})',
                    'stderr': result.stderr[:500] if result.stderr else '',
                }

        return json.loads(result.stdout)

    except subprocess.TimeoutExpired:
        return {'error': 'Fetcher timeout (60 detik)'}
    except json.JSONDecodeError as e:
        return {'error': f'Invalid JSON dari fetcher: {str(e)}'}
    except FileNotFoundError:
        return {'error': 'Node.js tidak ditemukan. Pastikan Node.js terinstal.'}
    except Exception as e:
        return {'error': f'Unexpected error: {str(e)}'}


def fetch_mt5_backtest_data(
    from_date: str,
    to_date: str,
    mt5_symbol: str = None,
    timeframe: str = '5',
) -> Dict:
    """
    Mengambil data candle historis langsung dari terminal MetaTrader 5.

    Args:
        from_date: Tanggal mulai (format: YYYY-MM-DD)
        to_date: Tanggal akhir (format: YYYY-MM-DD)
        mt5_symbol: Simbol MT5 (default: ambil dari config.py)
        timeframe: '5' untuk M5, '1' untuk M1

    Returns:
        Dict berisi candles list dengan indikator (ema_200, rsi_14, atr_14)
    """
    try:
        import MetaTrader5 as mt5
        import pandas as pd
        import numpy as np
        from datetime import datetime, timezone
        from config import MT5_SYMBOL

        if mt5_symbol is None:
            mt5_symbol = MT5_SYMBOL

        if not mt5.initialize():
            return {'error': f'Gagal menginisialisasi MT5: {mt5.last_error()}'}

        start_dt = datetime.strptime(from_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
        # Tambah 1 hari ke to_date agar data pada hari terakhir ikut terambil
        end_dt = datetime.strptime(to_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
        from datetime import timedelta
        end_dt = end_dt + timedelta(days=1)

        mt5_tf = mt5.TIMEFRAME_M5 if timeframe == '5' else mt5.TIMEFRAME_M1
        rates = mt5.copy_rates_range(mt5_symbol, mt5_tf, start_dt, end_dt)
        mt5.shutdown()

        if rates is None or len(rates) == 0:
            return {'error': f'Tidak ada data candle dari MT5 untuk {mt5_symbol} ({from_date} s/d {to_date})'}

        df = pd.DataFrame(rates)
        df = df.rename(columns={'tick_volume': 'volume'})
        df = df.sort_values(by='time')

        # Hitung indikator teknikal
        # EMA 200
        df['ema_200'] = df['close'].ewm(span=200, adjust=False).mean()

        # RSI 14
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['rsi_14'] = 100 - (100 / (1 + rs))

        # ATR 14
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)
        df['atr_14'] = true_range.rolling(14).mean()

        df = df.replace({np.nan: None})

        candles_list = df[['time', 'open', 'high', 'low', 'close', 'volume', 'ema_200', 'rsi_14', 'atr_14']].to_dict(orient='records')

        return {
            'meta': {
                'symbol': mt5_symbol,
                'timeframe': '5',
                'source': 'metatrader5',
                'candle_count': len(candles_list),
                'from': from_date,
                'to': to_date,
            },
            'candles': candles_list
        }

    except ImportError:
        return {'error': 'Library MetaTrader5 belum terinstal. Jalankan: pip install MetaTrader5'}
    except Exception as e:
        return {'error': f'Error saat mengambil data MT5: {str(e)}'}


def run_backtest_tool(
    symbol: str = 'FOREXCOM:XAUUSD',
    timeframe: str = '5',
    limit: int = 500,
    capital: float = 1000.0,
    swing_lookback: int = 3,
    atr_sl: float = 1.5,
    atr_tp: float = 2.0,
    to_date: Optional[str] = None,
    from_date: Optional[str] = None,
    range_val: Optional[int] = None,
    source: str = 'mt5',
    use_ema: bool = True,
) -> Dict:
    """
    Mengambil data historis dan menjalankan backtest strategi SMC.

    Args:
        symbol: Simbol TradingView (digunakan jika source='tradingview')
        timeframe: Timeframe dalam menit (default: 5 untuk M5)
        limit: Jumlah candle historis (digunakan jika source='tradingview')
        capital: Modal awal (USD)
        swing_lookback: Sensitivitas swing point
        atr_sl: ATR multiplier untuk Stop Loss
        atr_tp: ATR multiplier untuk Take Profit
        to_date: Tanggal akhir data (format: YYYY-MM-DD)
        from_date: Tanggal awal data (format: YYYY-MM-DD, khusus source='mt5')
        range_val: Jumlah bar yang diminta ke TradingView
        source: Sumber data - 'mt5' (default) atau 'tradingview'
        use_ema: Gunakan filter EMA 200 (default: True)

    Returns:
        Dict berisi laporan performa backtest
    """
    candles = []

    if source == 'mt5' and from_date and to_date:
        # Gunakan data langsung dari MetaTrader 5
        data = fetch_mt5_backtest_data(from_date=from_date, to_date=to_date, timeframe=timeframe)
        if 'error' in data and not data.get('candles'):
            return {'error': f'Gagal mengambil data MT5: {data["error"]}'}
        candles = data.get('candles', [])
    else:
        # Fallback: Gunakan TradingView
        data = fetch_xauusd_data(symbol, timeframe, limit, to_date=to_date, range_val=range_val)
        if 'error' in data and not data.get('candles'):
            return {'error': f'Gagal mengambil data: {data["error"]}'}
        candles = data.get('candles', [])

    if not candles:
        return {'error': 'Tidak ada data candle yang diterima'}

    # Jalankan backtester (menggunakan rolling SMC)
    from backtester import run_backtest

    report = run_backtest(
        candles=candles,
        initial_capital=capital,
        atr_sl_mult=atr_sl,
        atr_tp_mult=atr_tp,
        swing_lookback=swing_lookback,
        use_ema=use_ema,
    )

    return report


def get_market_signal(
    symbol: str = 'FOREXCOM:XAUUSD',
    timeframe: str = '5',
) -> Dict:
    """
    Mengambil data terbaru dan menghasilkan sinyal trading sederhana.

    Returns:
        Dict berisi sinyal Buy/Sell/Hold beserta alasan dan level SL/TP
    """
    data = fetch_xauusd_data(symbol, timeframe, limit=1500, range_val=1500)

    if 'error' in data and not data.get('candles'):
        return {'signal': 'error', 'reason': data.get('error', 'Unknown error')}

    candles = data.get('candles', [])
    if not candles:
        return {'signal': 'error', 'reason': 'Tidak ada data candle'}

    latest = candles[-1]

    # Analisis SMC
    from smc_local import analyze_smc
    smc = analyze_smc(candles)

    # Tentukan sinyal
    signal = 'HOLD'
    reason = ''
    sl = None
    tp = None
    atr = latest.get('atr_14', 0)

    active_obs = smc.get('active_order_blocks', [])
    bias = smc.get('market_bias', 'neutral')
    price = latest['close']

    # Cek apakah harga dekat dengan Order Block aktif
    for ob in active_obs:
        if ob['type'] == 'bullish_ob' and bias in ('bullish', 'neutral'):
            if ob['low'] <= price <= ob['high'] * 1.002:  # Dalam zona OB ±0.2%
                signal = 'BUY'
                reason = f"Harga berada di zona Bullish Order Block ({ob['low']:.2f} - {ob['high']:.2f}). Market bias: {bias}. Konfirmasi BOS/CHoCH bullish terdeteksi."
                sl = ob['low'] - (atr * 0.5) if atr else ob['low'] - 2
                tp = price + (atr * 2.0) if atr else price + 5
                break

        elif ob['type'] == 'bearish_ob' and bias in ('bearish', 'neutral'):
            if ob['low'] * 0.998 <= price <= ob['high']:
                signal = 'SELL'
                reason = f"Harga berada di zona Bearish Order Block ({ob['low']:.2f} - {ob['high']:.2f}). Market bias: {bias}. Konfirmasi BOS/CHoCH bearish terdeteksi."
                sl = ob['high'] + (atr * 0.5) if atr else ob['high'] + 2
                tp = price - (atr * 2.0) if atr else price - 5
                break

    if signal == 'HOLD':
        reason = f"Tidak ada Order Block aktif yang menyentuh harga saat ini ({price:.2f}). Market bias: {bias}. Menunggu harga kembali ke zona OB."

    # Data indikator pendukung
    rsi = latest.get('rsi_14')
    ema = latest.get('ema_20')
    sma = latest.get('sma_50')
    macd = latest.get('macd')

    return {
        'signal': signal,
        'reason': reason,
        'price': price,
        'sl': round(sl, 2) if sl else None,
        'tp': round(tp, 2) if tp else None,
        'market_bias': bias,
        'indicators': {
            'rsi_14': rsi,
            'ema_20': ema,
            'sma_50': sma,
            'macd': macd,
            'atr_14': atr,
        },
        'smc_summary': smc.get('summary', {}),
        'active_order_blocks': len(active_obs),
        'timestamp': latest.get('time'),
    }


# ============================================================
# Tool definitions untuk Hermes Agent
# ============================================================

TOOLS = [
    {
        'name': 'fetch_xauusd_analysis',
        'description': (
            'Mengambil data OHLC (Open, High, Low, Close) XAUUSD beserta '
            'indikator teknikal (RSI, EMA, SMA, MACD, ATR) dan analisis '
            'Smart Money Concepts (Order Blocks, BOS, CHoCH) dari TradingView. '
            'Gunakan tool ini untuk melihat kondisi pasar terkini.'
        ),
        'parameters': {
            'type': 'object',
            'properties': {
                'timeframe': {
                    'type': 'string',
                    'description': 'Timeframe dalam menit (contoh: "5", "1", "15", "60")',
                    'default': '5',
                },
                'limit': {
                    'type': 'integer',
                    'description': 'Jumlah candle yang diambil',
                    'default': 200,
                },
            },
        },
        'handler': lambda params: get_market_signal(
            timeframe=params.get('timeframe', '5'),
        ),
    },
    {
        'name': 'run_xauusd_backtest',
        'description': (
            'Menjalankan simulasi backtest strategi SMC (Smart Money Concepts) '
            'pada data historis XAUUSD. Menghasilkan laporan performa lengkap '
            'termasuk Win Rate, Profit Factor, dan Maximum Drawdown. '
            'Modal awal default: $1000.'
        ),
        'parameters': {
            'type': 'object',
            'properties': {
                'timeframe': {
                    'type': 'string',
                    'description': 'Timeframe dalam menit',
                    'default': '5',
                },
                'limit': {
                    'type': 'integer',
                    'description': 'Jumlah candle historis untuk backtest',
                    'default': 500,
                },
                'capital': {
                    'type': 'number',
                    'description': 'Modal awal dalam USD',
                    'default': 1000.0,
                },
            },
        },
        'handler': lambda params: run_backtest_tool(
            timeframe=params.get('timeframe', '5'),
            limit=params.get('limit', 500),
            capital=params.get('capital', 1000.0),
        ),
    },
]


if __name__ == '__main__':
    # Test mandiri
    print("=== Testing get_market_signal ===")
    result = get_market_signal()
    print(json.dumps(result, indent=2, default=str))
