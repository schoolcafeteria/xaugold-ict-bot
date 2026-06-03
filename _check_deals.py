import MetaTrader5 as mt5
from datetime import datetime, timedelta, timezone
from config import MT5_MAGIC_NUMBER

mt5.initialize()

start = datetime(2026, 6, 1)
end = datetime(2026, 7, 1)
deals = mt5.history_deals_get(start - timedelta(days=1), end + timedelta(days=1))

print(f"Magic Number bot: {MT5_MAGIC_NUMBER}")
print(f"Total deals found: {len(deals) if deals else 0}")
print()

if deals:
    for d in deals:
        if d.entry == 1:
            deal_time_utc = datetime.fromtimestamp(d.time, tz=timezone.utc)
            deal_time_wib = deal_time_utc + timedelta(hours=7)
            pnl = d.profit + d.swap + d.commission
            direction = "BUY" if d.type == 1 else "SELL"
            date_str = deal_time_wib.strftime("%Y-%m-%d %H:%M")
            print(f"[{date_str} WIB] {direction} {d.volume} lot | Magic={d.magic} | PnL={pnl:+.2f} | Ticket={d.ticket}")
