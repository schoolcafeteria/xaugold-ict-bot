"""
Backtester - Mesin Simulasi Trading Lokal untuk Strategi SMC XAUUSD

Mensimulasikan eksekusi trading berdasarkan konsep Smart Money Concepts
(Order Blocks + konfirmasi BOS/CHoCH) pada data historis XAUUSD M5.

Parameter tetap:
- Modal awal: $1000
- Mode: Sinyal saja (tidak ada eksekusi otomatis)
- Timeframe: 5 Menit (M5)

Usage:
  python backtester.py --data <path_to_json>
  atau: cat data.json | python backtester.py
"""

import json
import sys
import argparse
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional
from smc_local import analyze_smc


# ============================================================
# Konfigurasi Default
# ============================================================
DEFAULT_INITIAL_CAPITAL = 1000.0   # USD
DEFAULT_RISK_PER_TRADE = 0.02     # 2% risiko per trade
DEFAULT_LOT_SIZE = 0.01           # Mini lot XAUUSD
POINT_VALUE = 1.0                 # $1 per pip untuk 0.01 lot XAUUSD
DEFAULT_ATR_SL_MULTIPLIER = 1.5   # SL = 1.5x ATR
DEFAULT_ATR_TP_MULTIPLIER = 2.0   # TP = 2.0x ATR (RR = 1:1.33)


class Trade:
    """Representasi satu transaksi trading."""

    def __init__(self, direction: str, entry_price: float, sl: float, tp: float,
                 entry_bar: int, entry_time: float, reason: str):
        self.direction = direction        # 'buy' atau 'sell'
        self.entry_price = entry_price
        self.sl = sl
        self.tp = tp
        self.entry_bar = entry_bar
        self.entry_time = entry_time
        self.reason = reason

        self.exit_price: Optional[float] = None
        self.exit_bar: Optional[int] = None
        self.exit_time: Optional[float] = None
        self.exit_reason: Optional[str] = None
        self.profit: float = 0.0
        self.is_closed = False

    def close(self, exit_price: float, exit_bar: int, exit_time: float, reason: str):
        self.exit_price = exit_price
        self.exit_bar = exit_bar
        self.exit_time = exit_time
        self.exit_reason = reason
        self.is_closed = True

        if self.direction == 'buy':
            self.profit = exit_price - self.entry_price
        else:
            self.profit = self.entry_price - exit_price

    def to_dict(self) -> Dict:
        return {
            'direction': self.direction,
            'entry_price': self.entry_price,
            'sl': self.sl,
            'tp': self.tp,
            'entry_bar': self.entry_bar,
            'entry_time': self.entry_time,
            'reason': self.reason,
            'exit_price': self.exit_price,
            'exit_bar': self.exit_bar,
            'exit_time': self.exit_time,
            'exit_reason': self.exit_reason,
            'profit': round(self.profit, 2),
            'is_closed': self.is_closed,
        }


def run_backtest(
    candles: List[Dict],
    smc_data: Dict = None,
    initial_capital: float = DEFAULT_INITIAL_CAPITAL,
    risk_per_trade: float = DEFAULT_RISK_PER_TRADE,
    atr_sl_mult: float = DEFAULT_ATR_SL_MULTIPLIER,
    atr_tp_mult: float = DEFAULT_ATR_TP_MULTIPLIER,
    swing_lookback: int = 3,
    use_ema: bool = True,
) -> Dict:
    """
    Menjalankan backtest strategi SMC pada data historis.

    Menggunakan pendekatan ROLLING: SMC dihitung ulang setiap
    SMC_RECALC_INTERVAL candle menggunakan window lookback,
    sehingga market bias dan Order Blocks berubah secara dinamis.

    Strategi:
    1. Setiap 20 candle, hitung ulang SMC (swing, BOS, CHoCH, OB)
    2. Identifikasi Order Block aktif yang searah dengan market bias
    3. Jika harga kembali ke zona OB → entry
    4. SL di bawah/atas OB, TP berdasarkan ATR multiplier

    Args:
        candles: List of candle dicts (harus sudah ada indikator: atr_14)
        smc_data: Tidak digunakan lagi (kept for backward compat)
        initial_capital: Modal awal dalam USD
        risk_per_trade: Persentase risiko per trade (0.02 = 2%)
        atr_sl_mult: Multiplier ATR untuk Stop Loss
        atr_tp_mult: Multiplier ATR untuk Take Profit
        swing_lookback: Parameter sensitivitas swing point

    Returns:
        Dict berisi laporan performa backtest
    """
    SMC_WINDOW = 100          # Jumlah candle lookback untuk analisis SMC
    SMC_RECALC_INTERVAL = 20  # Hitung ulang SMC setiap N candle
    MIN_START = max(50, SMC_WINDOW)  # Mulai setelah cukup data

    capital = initial_capital
    trades: List[Trade] = []
    active_trade: Optional[Trade] = None
    peak_capital = initial_capital
    max_drawdown = 0.0
    equity_curve = []

    # State SMC yang di-update secara rolling
    active_obs = []
    market_bias = 'neutral'
    last_recalc = 0
    used_ob_bars = set()  # Mencatat bar_index dari OB yang sudah terpakai
    daily_losses = {}     # Mencatat total kerugian per tanggal WIB: {'YYYY-MM-DD': float_loss}

    for i in range(MIN_START, len(candles)):
        candle = candles[i]
        atr = candle.get('atr_14')

        if atr is None or atr == 0:
            continue

        # ========== Recalculate SMC secara rolling ==========
        if i - last_recalc >= SMC_RECALC_INTERVAL or last_recalc == 0:
            window_start = max(0, i - SMC_WINDOW)
            window_candles = candles[window_start:i + 1]
            smc_result = analyze_smc(window_candles, swing_lookback=swing_lookback)

            # Update bias dan OB dari window terbaru
            market_bias = smc_result.get('market_bias', 'neutral')

            # Remap bar_index dari window-local ke global
            new_obs = []
            for ob in smc_result.get('active_order_blocks', []):
                ob_copy = ob.copy()
                ob_copy['bar_index'] = ob_copy['bar_index'] + window_start
                ob_copy['bos_bar_index'] = ob_copy.get('bos_bar_index', 0) + window_start
                new_obs.append(ob_copy)
            active_obs = new_obs
            last_recalc = i

        # ========== Cek exit untuk trade aktif ==========
        if active_trade and not active_trade.is_closed:
            if active_trade.direction == 'buy':
                # Cek SL
                if candle['low'] <= active_trade.sl:
                    active_trade.close(active_trade.sl, i, candle.get('time', i), 'stop_loss')
                    capital += active_trade.profit * DEFAULT_LOT_SIZE * 100
                # Cek TP
                elif candle['high'] >= active_trade.tp:
                    active_trade.close(active_trade.tp, i, candle.get('time', i), 'take_profit')
                    capital += active_trade.profit * DEFAULT_LOT_SIZE * 100
            else:  # sell
                # Cek SL
                if candle['high'] >= active_trade.sl:
                    active_trade.close(active_trade.sl, i, candle.get('time', i), 'stop_loss')
                    capital += active_trade.profit * DEFAULT_LOT_SIZE * 100
                # Cek TP
                elif candle['low'] <= active_trade.tp:
                    active_trade.close(active_trade.tp, i, candle.get('time', i), 'take_profit')
                    capital += active_trade.profit * DEFAULT_LOT_SIZE * 100

            if active_trade.is_closed:
                # Dapatkan tanggal penutupan
                exit_time = active_trade.exit_time
                if exit_time:
                    dt_exit = datetime.fromtimestamp(exit_time, tz=timezone.utc) + timedelta(hours=7)
                    date_key = dt_exit.strftime('%Y-%m-%d')
                    trade_result = active_trade.profit * DEFAULT_LOT_SIZE * 100

                    # Catat kerugian harian jika trade berakhir rugi
                    if trade_result < 0:
                        loss_amount = abs(trade_result)
                        daily_losses[date_key] = daily_losses.get(date_key, 0.0) + loss_amount

                trades.append(active_trade)
                active_trade = None

        # ========== Cek entry baru (hanya jika tidak ada trade aktif) ==========
        if active_trade is None:
            # Filter Sesi Waktu WIB (08:00 - 19:00)
            candle_time = candle.get('time')
            if candle_time:
                dt_wib = datetime.fromtimestamp(candle_time, tz=timezone.utc) + timedelta(hours=7)
                if not (8 <= dt_wib.hour < 19):
                    continue  # Abaikan entry jika di luar jam 08:00 - 19:00 WIB

                # Filter Daily Loss Limit ($10)
                date_key = dt_wib.strftime('%Y-%m-%d')
                if daily_losses.get(date_key, 0.0) >= 10.0:
                    continue  # Skip trade jika hari ini sudah rugi >= $10

            for ob in active_obs:
                ob_bar = ob.get('bar_index', 0)

                # Hanya cek OB yang sudah terbentuk sebelum candle saat ini
                if ob_bar >= i:
                    continue

                # Skip jika OB ini sudah pernah digunakan untuk entry sebelumnya
                if ob_bar in used_ob_bars:
                    continue

                # Skip OB yang terlalu jauh (lebih dari 50 candle lalu)
                if i - ob_bar > 50:
                    continue

                # Ambil data indikator untuk konfirmasi
                rsi = candle.get('rsi_14')
                ema_200 = candle.get('ema_200')

                # ===== Bullish OB + market bias bullish/neutral =====
                if ob['type'] == 'bullish_ob' and market_bias in ('bullish', 'neutral'):
                    # Harga masuk ke zona OB
                    if candle['low'] <= ob['high'] and candle['close'] > ob['low']:
                        entry_price = candle['close']

                        # Filter Trend EMA 200: Hanya BUY jika harga di atas EMA 200
                        if use_ema and ema_200 and entry_price < ema_200:
                            continue

                        # Filter RSI: Jangan BUY jika RSI sudah overbought
                        if rsi and rsi > 70:
                            continue

                        sl = ob['low'] - (atr * 1.0)  # SL dikembalikan
                        tp = entry_price + (atr * atr_tp_mult)

                        active_trade = Trade(
                            direction='buy',
                            entry_price=entry_price,
                            sl=sl,
                            tp=tp,
                            entry_bar=i,
                            entry_time=candle.get('time', i),
                            reason=f'Bullish OB retest (bar {ob_bar}, bias={market_bias})',
                        )
                        used_ob_bars.add(ob_bar)
                        break

                # ===== Bearish OB + market bias bearish/neutral =====
                elif ob['type'] == 'bearish_ob' and market_bias in ('bearish', 'neutral'):
                    # Harga masuk ke zona OB
                    if candle['high'] >= ob['low'] and candle['close'] < ob['high']:
                        entry_price = candle['close']

                        # Filter Trend EMA 200: Hanya SELL jika harga di bawah EMA 200
                        if use_ema and ema_200 and entry_price > ema_200:
                            continue

                        # Filter RSI: Jangan SELL jika RSI sudah oversold
                        if rsi and rsi < 30:
                            continue

                        sl = ob['high'] + (atr * 1.0)  # SL dikembalikan
                        tp = entry_price - (atr * atr_tp_mult)

                        active_trade = Trade(
                            direction='sell',
                            entry_price=entry_price,
                            sl=sl,
                            tp=tp,
                            entry_bar=i,
                            entry_time=candle.get('time', i),
                            reason=f'Bearish OB retest (bar {ob_bar}, bias={market_bias})',
                        )
                        used_ob_bars.add(ob_bar)
                        break

        # Tracking equity
        equity_curve.append(round(capital, 2))
        if capital > peak_capital:
            peak_capital = capital
        dd = (peak_capital - capital) / peak_capital * 100
        if dd > max_drawdown:
            max_drawdown = dd

    # ========== Tutup trade yang masih terbuka ==========
    if active_trade and not active_trade.is_closed:
        last_candle = candles[-1]
        active_trade.close(
            last_candle['close'], len(candles) - 1,
            last_candle.get('time', len(candles) - 1), 'end_of_data'
        )
        capital += active_trade.profit * DEFAULT_LOT_SIZE * 100
        trades.append(active_trade)

    # ========== Hitung metrik performa ==========
    closed_trades = [t for t in trades if t.is_closed]
    wins = [t for t in closed_trades if t.profit > 0]
    losses = [t for t in closed_trades if t.profit <= 0]

    total_profit = sum(t.profit for t in wins) * DEFAULT_LOT_SIZE * 100
    total_loss = abs(sum(t.profit for t in losses) * DEFAULT_LOT_SIZE * 100)

    win_rate = (len(wins) / len(closed_trades) * 100) if closed_trades else 0
    profit_factor = (total_profit / total_loss) if total_loss > 0 else float('inf')
    net_pnl = capital - initial_capital

    report = {
        'summary': {
            'initial_capital': initial_capital,
            'final_capital': round(capital, 2),
            'net_pnl': round(net_pnl, 2),
            'net_pnl_pct': round(net_pnl / initial_capital * 100, 2),
            'total_trades': len(closed_trades),
            'winning_trades': len(wins),
            'losing_trades': len(losses),
            'win_rate_pct': round(win_rate, 2),
            'profit_factor': round(profit_factor, 4) if profit_factor != float('inf') else 'inf',
            'max_drawdown_pct': round(max_drawdown, 2),
            'market_bias': market_bias,
        },
        'trades': [t.to_dict() for t in closed_trades],
        'equity_curve_sample': equity_curve[-20:] if equity_curve else [],
    }

    return report


def main():
    parser = argparse.ArgumentParser(description='XAUUSD SMC Backtester')
    parser.add_argument('--data', type=str, help='Path ke file JSON data candle')
    parser.add_argument('--capital', type=float, default=DEFAULT_INITIAL_CAPITAL, help='Modal awal (USD)')
    parser.add_argument('--risk', type=float, default=DEFAULT_RISK_PER_TRADE, help='Risiko per trade (0.02 = 2%%)')
    parser.add_argument('--atr-sl', type=float, default=DEFAULT_ATR_SL_MULTIPLIER, help='ATR multiplier untuk SL')
    parser.add_argument('--atr-tp', type=float, default=DEFAULT_ATR_TP_MULTIPLIER, help='ATR multiplier untuk TP')
    parser.add_argument('--swing-lookback', type=int, default=5, help='Lookback untuk swing point detection')
    args = parser.parse_args()

    # Baca data
    if args.data:
        with open(args.data, 'r') as f:
            data = json.load(f)
    else:
        data = json.load(sys.stdin)

    candles = data.get('candles', [])

    if not candles:
        print(json.dumps({'error': 'Tidak ada data candle'}, indent=2))
        sys.exit(1)

    # Jalankan analisis SMC
    # Jika data SMC dari TradingView tersedia, gunakan itu
    # Jika tidak, hitung lokal
    smc_available = data.get('meta', {}).get('smc_available', False)

    if smc_available and data.get('smc'):
        smc_data = data['smc']
        # Konversi format SMC TradingView ke format internal kita
        smc_data['market_bias'] = 'neutral'  # Akan diperbarui dari analisis
        smc_data['active_order_blocks'] = smc_data.get('order_blocks', [])
    else:
        # Fallback: hitung SMC lokal
        smc_data = analyze_smc(candles, swing_lookback=args.swing_lookback)

    # Jalankan backtest
    report = run_backtest(
        candles=candles,
        smc_data=smc_data,
        initial_capital=args.capital,
        risk_per_trade=args.risk,
        atr_sl_mult=args.atr_sl,
        atr_tp_mult=args.atr_tp,
    )

    print(json.dumps(report, indent=2, default=str))


if __name__ == '__main__':
    main()
