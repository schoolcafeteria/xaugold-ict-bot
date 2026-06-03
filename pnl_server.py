"""
PnL Dashboard Server — Flask backend untuk web PnL Calendar.

Menyediakan API endpoint untuk mengambil data P&L dari MT5
dan menyajikan halaman web dashboard.
"""

from flask import Flask, jsonify, request, send_from_directory
from datetime import datetime, timedelta, timezone
import calendar
import os
import logging

logger = logging.getLogger("ICTBot.PnLServer")

app = Flask(__name__, static_folder='web', static_url_path='/static')


def get_mt5_deals(year, month):
    """
    Ambil semua closed deals dari MT5 untuk bulan tertentu.
    Returns list of deal dicts grouped by tanggal WIB.
    """
    try:
        import MetaTrader5 as mt5
        from config import MT5_MAGIC_NUMBER
    except ImportError:
        return None, "MT5 module not available"

    if not mt5.initialize():
        return None, "MT5 not connected"

    # Range query: awal bulan sampai akhir bulan (dengan buffer)
    start_date = datetime(year, month, 1)
    if month == 12:
        end_date = datetime(year + 1, 1, 1)
    else:
        end_date = datetime(year, month + 1, 1)

    # Buffer 1 hari di kedua sisi untuk timezone edge cases
    deals = mt5.history_deals_get(
        start_date - timedelta(days=1),
        end_date + timedelta(days=1)
    )

    if deals is None:
        deals = []

    # Process deals: semua trade (bot + manual), group by date WIB
    daily_pnl = {}
    total_wins = 0
    total_losses = 0
    biggest_win = 0.0
    biggest_loss = 0.0
    total_profit = 0.0
    total_loss_amount = 0.0
    all_trades = []

    for d in deals:
        if d.entry != 1:  # Hanya deal CLOSE (OUT)
            continue

        # Konversi ke WIB (broker server biasanya UTC+3, WIB = UTC+7 → +4 jam dari broker time)
        deal_time_utc = datetime.fromtimestamp(d.time, tz=timezone.utc)
        deal_time_wib = deal_time_utc + timedelta(hours=4)
        deal_date = deal_time_wib.strftime('%Y-%m-%d')

        # Pastikan deal masuk ke bulan yang diminta
        dt = deal_time_wib
        if dt.month != month or dt.year != year:
            continue

        pnl = round(d.profit + d.swap + d.commission, 2)

        if deal_date not in daily_pnl:
            daily_pnl[deal_date] = {
                'pnl': 0.0,
                'trades': 0,
                'wins': 0,
                'losses': 0,
                'biggest_win': 0.0,
                'biggest_loss': 0.0,
            }

        daily_pnl[deal_date]['pnl'] = round(daily_pnl[deal_date]['pnl'] + pnl, 2)
        daily_pnl[deal_date]['trades'] += 1

        if pnl >= 0:
            daily_pnl[deal_date]['wins'] += 1
            total_wins += 1
            total_profit += pnl
            biggest_win = max(biggest_win, pnl)
            daily_pnl[deal_date]['biggest_win'] = max(daily_pnl[deal_date]['biggest_win'], pnl)
        else:
            daily_pnl[deal_date]['losses'] += 1
            total_losses += 1
            total_loss_amount += abs(pnl)
            biggest_loss = min(biggest_loss, pnl)
            daily_pnl[deal_date]['biggest_loss'] = min(daily_pnl[deal_date]['biggest_loss'], pnl)

        # Arah posisi: deal OUT berlawanan dengan posisi awal
        pos_direction = "BUY" if d.type == 1 else "SELL"
        all_trades.append({
            'date': deal_date,
            'time': deal_time_wib.strftime('%H:%M'),
            'direction': pos_direction,
            'volume': d.volume,
            'pnl': pnl,
            'price': d.price,
        })

    # Get floating P&L dari semua posisi aktif
    try:
        positions = mt5.positions_get()
        floating = 0.0
        open_count = 0
        if positions:
            floating = sum(p.profit + p.swap + p.commission for p in positions)
            open_count = len(positions)
    except Exception:
        floating = 0.0
        open_count = 0

    total_trades = total_wins + total_losses
    win_rate = round((total_wins / total_trades * 100), 1) if total_trades > 0 else 0.0
    net_realized = round(total_profit - total_loss_amount, 2)

    result = {
        'month': month,
        'year': year,
        'daily': daily_pnl,
        'trades': all_trades,
        'summary': {
            'realized_pnl': net_realized,
            'unrealized': round(floating, 2),
            'open_positions': open_count,
            'total_trades': total_trades,
            'wins': total_wins,
            'losses': total_losses,
            'win_rate': win_rate,
            'biggest_win': round(biggest_win, 2),
            'biggest_loss': round(biggest_loss, 2),
            'total_profit': round(total_profit, 2),
            'total_loss': round(total_loss_amount, 2),
        }
    }

    return result, None


# =====================================================================
# ROUTES
# =====================================================================

@app.route('/')
def index():
    """Serve halaman dashboard utama."""
    return send_from_directory('web', 'index.html')


@app.route('/api/pnl')
def api_pnl():
    """
    API: Data P&L per hari untuk bulan tertentu.
    Query params: ?month=6&year=2026
    """
    now_wib = datetime.now(timezone.utc) + timedelta(hours=7)
    month = int(request.args.get('month', now_wib.month))
    year = int(request.args.get('year', now_wib.year))

    data, error = get_mt5_deals(year, month)
    if error:
        return jsonify({'error': error}), 500

    return jsonify(data)


@app.route('/api/pnl/day')
def api_pnl_day():
    """
    API: Data P&L detail untuk satu hari.
    Query params: ?date=2026-06-03
    """
    date_str = request.args.get('date')
    if not date_str:
        return jsonify({'error': 'date parameter required'}), 400

    try:
        dt = datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        return jsonify({'error': 'Invalid date format, use YYYY-MM-DD'}), 400

    data, error = get_mt5_deals(dt.year, dt.month)
    if error:
        return jsonify({'error': error}), 500

    day_data = data['daily'].get(date_str, {
        'pnl': 0.0, 'trades': 0, 'wins': 0, 'losses': 0,
        'biggest_win': 0.0, 'biggest_loss': 0.0,
    })

    # Filter trades untuk hari ini saja
    day_trades = [t for t in data.get('trades', []) if t['date'] == date_str]

    return jsonify({
        'date': date_str,
        'pnl': day_data,
        'trades': day_trades,
        'summary': data['summary'],
    })


# =====================================================================
# EXCHANGE RATE (Real-time)
# =====================================================================

_rate_cache = {
    'rates': {},
    'last_fetch': None,
}
_RATE_CACHE_TTL = 3600  # 1 jam


def _fetch_exchange_rates():
    """Fetch kurs dari free API, cache selama 1 jam."""
    import time
    now = time.time()

    if _rate_cache['last_fetch'] and (now - _rate_cache['last_fetch']) < _RATE_CACHE_TTL:
        return _rate_cache['rates']

    try:
        import requests
        # Free API tanpa key
        res = requests.get(
            'https://open.er-api.com/v6/latest/USD',
            timeout=5
        )
        if res.status_code == 200:
            data = res.json()
            if data.get('result') == 'success':
                _rate_cache['rates'] = data.get('rates', {})
                _rate_cache['last_fetch'] = now
                logger.info(f"💱 Exchange rates updated: USD/IDR = {_rate_cache['rates'].get('IDR', 'N/A')}")
                return _rate_cache['rates']
    except Exception as e:
        logger.warning(f"Failed to fetch exchange rates: {e}")

    # Fallback jika gagal fetch
    if not _rate_cache['rates']:
        _rate_cache['rates'] = {'IDR': 16500, 'USD': 1}
    return _rate_cache['rates']


@app.route('/api/rate')
def api_rate():
    """
    API: Kurs real-time.
    Returns JSON with exchange rates dari USD.
    """
    rates = _fetch_exchange_rates()
    return jsonify({
        'base': 'USD',
        'IDR': rates.get('IDR', 16500),
    })


def run_server(host='0.0.0.0', port=5000):
    """Jalankan Flask server (untuk dipanggil dari thread)."""
    # Suppress Flask request logs agar tidak noisy di console utama
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.WARNING)

    logger.info(f"🌐 PnL Dashboard server berjalan di http://{host}:{port}")
    app.run(host=host, port=port, debug=False, use_reloader=False)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    app.run(host='0.0.0.0', port=5000, debug=True)
