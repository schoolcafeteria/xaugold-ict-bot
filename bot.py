"""
Bot Trading Hermes XAUUSD - Entry Point Utama

Bot ini menggunakan Hermes Agent untuk menganalisis pasar XAUUSD
dengan strategi Smart Money Concepts (SMC) dan memberikan sinyal
trading (Buy/Sell/Hold).

Mode operasi:
1. Mode Analisa: Tarik data terbaru → analisis → rekomendasi
2. Mode Backtest: Simulasi strategi pada data historis
3. Mode Interaktif: Chat dengan agen untuk analisis mendalam

Parameter tetap:
- Timeframe: 5 Menit (M5)
- Modal Backtest: $1000
- Mode: Sinyal saja (tidak ada eksekusi otomatis)

Usage:
  python bot.py                    # Mode interaktif
  python bot.py --signal           # Langsung ambil sinyal terbaru
  python bot.py --backtest         # Langsung jalankan backtest
"""

import json
import sys
import argparse
from pathlib import Path

# Pastikan directory proyek ada di sys.path
PROJECT_DIR = Path(__file__).parent.resolve()
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from tradingview_tool import get_market_signal, run_backtest_tool, TOOLS


def print_signal(signal_data: dict):
    """Cetak sinyal trading dalam format yang mudah dibaca."""
    print("\n" + "=" * 60)
    print("📊 SINYAL TRADING XAUUSD (M5)")
    print("=" * 60)

    sig = signal_data.get('signal', 'N/A')
    if sig == 'BUY':
        icon = '🟢'
    elif sig == 'SELL':
        icon = '🔴'
    else:
        icon = '⚪'

    print(f"\n{icon} Sinyal  : {sig}")
    print(f"💰 Harga  : {signal_data.get('price', 'N/A')}")
    print(f"🎯 TP     : {signal_data.get('tp', 'N/A')}")
    print(f"🛑 SL     : {signal_data.get('sl', 'N/A')}")
    print(f"📈 Bias   : {signal_data.get('market_bias', 'N/A')}")
    print(f"\n📝 Alasan : {signal_data.get('reason', 'N/A')}")

    indicators = signal_data.get('indicators', {})
    if indicators:
        print(f"\n--- Indikator Pendukung ---")
        print(f"  RSI(14) : {indicators.get('rsi_14', 'N/A')}")
        print(f"  EMA(20) : {indicators.get('ema_20', 'N/A')}")
        print(f"  ATR(14) : {indicators.get('atr_14', 'N/A')}")

    smc = signal_data.get('smc_summary', {})
    if smc:
        print(f"\n--- Smart Money Concepts ---")
        print(f"  BOS Events        : {smc.get('total_bos', 0)}")
        print(f"  CHoCH Events      : {smc.get('total_choch', 0)}")
        print(f"  Order Blocks Aktif: {smc.get('active_order_blocks', 0)}")
        print(f"  Bias Saat Ini     : {smc.get('current_bias', 'N/A')}")

    print("\n" + "=" * 60)


def print_backtest(report: dict):
    """Cetak laporan backtest dalam format yang mudah dibaca."""
    print("\n" + "=" * 60)
    print("📋 LAPORAN BACKTEST XAUUSD SMC (M5)")
    print("=" * 60)

    summary = report.get('summary', {})

    print(f"\n💰 Modal Awal     : ${summary.get('initial_capital', 0):.2f}")
    print(f"💰 Modal Akhir    : ${summary.get('final_capital', 0):.2f}")

    pnl = summary.get('net_pnl', 0)
    pnl_icon = '📈' if pnl >= 0 else '📉'
    print(f"{pnl_icon} Net P/L         : ${pnl:.2f} ({summary.get('net_pnl_pct', 0):.2f}%)")

    print(f"\n📊 Total Trades   : {summary.get('total_trades', 0)}")
    print(f"✅ Winning Trades : {summary.get('winning_trades', 0)}")
    print(f"❌ Losing Trades  : {summary.get('losing_trades', 0)}")
    print(f"🎯 Win Rate       : {summary.get('win_rate_pct', 0):.2f}%")
    print(f"⚖️  Profit Factor  : {summary.get('profit_factor', 0)}")
    print(f"📉 Max Drawdown   : {summary.get('max_drawdown_pct', 0):.2f}%")
    print(f"📈 Market Bias    : {summary.get('market_bias', 'N/A')}")

    trades = report.get('trades', [])
    if trades:
        print(f"\n--- Detail Trade (terakhir 5) ---")
        for t in trades[-5:]:
            direction_icon = '🟢' if t['direction'] == 'buy' else '🔴'
            profit_icon = '✅' if t['profit'] > 0 else '❌'
            print(f"  {direction_icon} {t['direction'].upper()} @ {t['entry_price']:.2f} → "
                  f"{t.get('exit_price', 'N/A')} | "
                  f"P/L: {t['profit']:.2f} {profit_icon} | "
                  f"Exit: {t.get('exit_reason', 'N/A')}")

    print("\n" + "=" * 60)


def run_interactive():
    """Mode interaktif dengan Hermes Agent."""
    try:
        from hermes_agent import HermesAgent

        print("\n🤖 Menginisialisasi Hermes Agent...")
        print("📊 Mode: Analisis XAUUSD dengan Smart Money Concepts")
        print("⏱️  Timeframe: 5 Menit (M5)")
        print("💰 Modal Backtest: $1000")
        print("-" * 50)

        agent = HermesAgent()

        # Daftarkan tool kustom
        for tool_def in TOOLS:
            agent.tools.register(
                name=tool_def['name'],
                description=tool_def['description'],
                parameters=tool_def['parameters'],
                handler=tool_def['handler'],
            )

        print("\n✅ Agent siap! Tool terdaftar:")
        print("  1. fetch_xauusd_analysis - Analisis pasar terkini")
        print("  2. run_xauusd_backtest - Simulasi backtest strategi")
        print("\n💬 Mulai chat dengan agent (ketik 'exit' untuk keluar):")
        print("-" * 50)

        # Mulai loop interaktif
        system_prompt = (
            "Kamu adalah bot trading XAUUSD profesional yang menggunakan strategi "
            "Smart Money Concepts (SMC). Kamu memiliki akses ke data real-time "
            "TradingView dan mesin backtesting. "
            "Timeframe utama: 5 Menit (M5). "
            "Tugasmu adalah memberikan sinyal trading (Buy/Sell/Hold) yang akurat "
            "berdasarkan analisis Order Blocks, BOS, dan CHoCH. "
            "Selalu sertakan level SL dan TP yang jelas. "
            "Jawab dalam Bahasa Indonesia."
        )

        while True:
            try:
                user_input = input("\n👤 Anda: ").strip()
                if user_input.lower() in ('exit', 'quit', 'keluar'):
                    print("\n👋 Sampai jumpa!")
                    break
                if not user_input:
                    continue

                response = agent.chat(user_input)
                print(f"\n🤖 Hermes: {response}")

            except KeyboardInterrupt:
                print("\n\n👋 Dihentikan oleh pengguna.")
                break

    except ImportError:
        print("\n⚠️  hermes-agent belum terinstal.")
        print("   Instal dengan: pip install hermes-agent")
        print("   Lalu konfigurasi: hermes setup")
        print("\n   Sementara itu, gunakan mode --signal atau --backtest")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error saat inisialisasi Hermes Agent: {e}")
        print("   Pastikan konfigurasi sudah benar: hermes doctor")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description='Bot Trading Hermes XAUUSD')
    parser.add_argument('--signal', action='store_true', help='Langsung ambil sinyal terbaru')
    parser.add_argument('--backtest', action='store_true', help='Langsung jalankan backtest')
    parser.add_argument('--limit', type=int, default=500, help='Jumlah candle untuk backtest (mode TradingView)')
    parser.add_argument('--to', type=str, default=None, help='Tanggal akhir data (YYYY-MM-DD)')
    parser.add_argument('--from', type=str, default=None, dest='from_date', help='Tanggal awal data (YYYY-MM-DD, untuk mode MT5)')
    parser.add_argument('--range', type=int, default=None, dest='range_val', help='Jumlah bar yang diminta ke TradingView')
    parser.add_argument('--capital', type=float, default=1000.0, help='Modal awal untuk backtest')
    parser.add_argument('--timeframe', type=str, default='1', choices=['1', '5'], help='Timeframe: 1 (M1) atau 5 (M5)')
    parser.add_argument('--source', type=str, default='mt5', choices=['mt5', 'tradingview'], help='Sumber data: mt5 (default) atau tradingview')
    parser.add_argument('--no-ema', action='store_true', dest='no_ema', help='Nonaktifkan filter EMA 200')
    parser.add_argument('--json', action='store_true', help='Output dalam format JSON mentah')
    args = parser.parse_args()

    if args.signal:
        print("⏳ Mengambil data dari TradingView...")
        result = get_market_signal()
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            print_signal(result)

    elif args.backtest:
        tf_label = "M5" if args.timeframe == '5' else "M1"
        source_label = f"MetaTrader 5 ({tf_label})" if args.source == 'mt5' else f"TradingView ({tf_label})"
        ema_label = " | EMA 200: OFF" if args.no_ema else " | EMA 200: ON"
        date_range = ""
        if args.from_date and args.to:
            date_range = f" dari {args.from_date} s/d {args.to}"
        elif args.to:
            date_range = f" sampai {args.to}"
        print(f"⏳ Sumber data: {source_label}{ema_label} | Menjalankan backtest{date_range}...")
        result = run_backtest_tool(
            limit=args.limit,
            timeframe=args.timeframe,
            to_date=args.to,
            from_date=args.from_date,
            range_val=args.range_val,
            capital=args.capital,
            source=args.source,
            use_ema=not args.no_ema,
        )
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            print_backtest(result)

    else:
        run_interactive()


if __name__ == '__main__':
    main()
