"""
PnL Card Generator — Membuat gambar share card P&L menggunakan Pillow.

Digunakan untuk mengirim PnL card ke Telegram sebagai gambar PNG.
"""

from PIL import Image, ImageDraw, ImageFont
from datetime import datetime, timedelta, timezone
import io
import os
import logging

logger = logging.getLogger("ICTBot.PnLCard")

# Dimensi card
CARD_WIDTH = 800
CARD_HEIGHT = 450
PADDING = 40

# Gradient presets (start_color, end_color)
GRADIENTS = {
    'aurora': [(13, 79, 79), (58, 26, 110)],
    'sunset': [(74, 26, 10), (74, 10, 46)],
    'forest': [(10, 58, 42), (10, 26, 18)],
    'midnight': [(15, 26, 46), (10, 16, 48)],
}


def _find_font(size):
    """Cari font yang tersedia di sistem."""
    font_paths = [
        # Windows
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/calibri.ttf",
        # Linux
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for path in font_paths:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _find_bold_font(size):
    """Cari bold font."""
    bold_paths = [
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/seguisb.ttf",
        "C:/Windows/Fonts/calibrib.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    for path in bold_paths:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return _find_font(size)


def _draw_gradient(draw, width, height, color_start, color_end):
    """Draw horizontal gradient background."""
    for x in range(width):
        ratio = x / width
        r = int(color_start[0] + (color_end[0] - color_start[0]) * ratio)
        g = int(color_start[1] + (color_end[1] - color_start[1]) * ratio)
        b = int(color_start[2] + (color_end[2] - color_start[2]) * ratio)
        draw.line([(x, 0), (x, height)], fill=(r, g, b))


def _format_money(val):
    """Format angka ke string money."""
    if val == 0:
        return "$0.00"
    sign = "+" if val > 0 else ""
    return f"{sign}${val:.2f}"


def _ordinal(day):
    if 4 <= day <= 20 or 24 <= day <= 30:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")


def generate_pnl_card(
    date_str,
    pnl,
    realized=0.0,
    unrealized=0.0,
    biggest_win=0.0,
    win_rate=0.0,
    total_trades=0,
    bg_theme='aurora',
    hide_details=False,
):
    """
    Generate PnL card sebagai bytes PNG.
    
    Args:
        date_str: Tanggal format 'YYYY-MM-DD' atau 'June 2026' untuk monthly
        pnl: Nilai P&L utama
        realized: Realized PnL
        unrealized: Unrealized PnL
        biggest_win: Trade terbesar yang profit
        win_rate: Win rate dalam persen
        total_trades: Total jumlah close
        bg_theme: 'aurora', 'sunset', 'forest', 'midnight'
        hide_details: Sembunyikan stats detail
    
    Returns:
        bytes: PNG image data
    """
    # Create image
    img = Image.new('RGB', (CARD_WIDTH, CARD_HEIGHT))
    draw = ImageDraw.Draw(img)

    # Draw gradient background
    colors = GRADIENTS.get(bg_theme, GRADIENTS['aurora'])
    _draw_gradient(draw, CARD_WIDTH, CARD_HEIGHT, colors[0], colors[1])

    # Add subtle overlay glow
    overlay = Image.new('RGBA', (CARD_WIDTH, CARD_HEIGHT), (0, 0, 0, 0))
    ov_draw = ImageDraw.Draw(overlay)
    # Top-left glow
    for i in range(200):
        alpha = max(0, 15 - i // 13)
        ov_draw.ellipse(
            [PADDING - i, PADDING - i, PADDING + i * 2, PADDING + i * 2],
            fill=(255, 255, 255, alpha)
        )
    img.paste(Image.alpha_composite(Image.new('RGBA', img.size, (0,0,0,0)), overlay).convert('RGB'),
              mask=overlay.split()[3])

    # Fonts
    font_sm = _find_font(14)
    font_md = _find_font(18)
    font_lg = _find_bold_font(22)
    font_title = _find_bold_font(20)
    font_pnl = _find_bold_font(52)
    font_stat_label = _find_font(13)
    font_stat_value = _find_bold_font(16)

    white = (255, 255, 255)
    white_dim = (255, 255, 255, 180)
    white_muted = (180, 180, 200)
    green = (0, 220, 130)
    red = (255, 71, 87)

    y_cursor = PADDING

    # ---- Header: Brand (left) + Date (right) ----
    draw.text((PADDING, y_cursor), "Eleu", fill=white, font=font_lg)

    # Format date
    try:
        dt = datetime.strptime(date_str, '%Y-%m-%d')
        day = dt.day
        month_name = dt.strftime('%B')
        year = dt.year
        date_display = f"{day}{_ordinal(day)} {month_name} {year}"
        title_display = f"PnL ({month_name} {day}, {year})"
    except ValueError:
        date_display = date_str
        title_display = f"PnL ({date_str})"

    date_bbox = draw.textbbox((0, 0), date_display, font=font_sm)
    date_width = date_bbox[2] - date_bbox[0]
    draw.text((CARD_WIDTH - PADDING - date_width, y_cursor + 6), date_display, fill=white_muted, font=font_sm)

    y_cursor += 50

    # ---- Title ----
    draw.text((PADDING, y_cursor), title_display, fill=white, font=font_title)
    y_cursor += 40

    # ---- Big PnL Number ----
    pnl_text = _format_money(pnl)
    pnl_color = green if pnl >= 0 else red
    draw.text((PADDING, y_cursor), pnl_text, fill=pnl_color, font=font_pnl)
    y_cursor += 80

    # ---- Divider line ----
    if not hide_details:
        draw.line(
            [(PADDING, y_cursor), (CARD_WIDTH - PADDING, y_cursor)],
            fill=(255, 255, 255, 40), width=1
        )
        y_cursor += 24

        # ---- Stats Grid (2x2) ----
        col1_x = PADDING
        col2_x = CARD_WIDTH // 2 + 20

        # Row 1
        draw.text((col1_x, y_cursor), "Realized", fill=white_muted, font=font_stat_label)
        draw.text((col2_x, y_cursor), "Unrealized", fill=white_muted, font=font_stat_label)
        y_cursor += 18
        draw.text((col1_x, y_cursor), _format_money(realized), fill=white, font=font_stat_value)
        draw.text((col2_x, y_cursor), _format_money(unrealized), fill=white, font=font_stat_value)
        y_cursor += 32

        # Row 2
        draw.text((col1_x, y_cursor), "Biggest Win", fill=white_muted, font=font_stat_label)
        draw.text((col2_x, y_cursor), "Win Rate", fill=white_muted, font=font_stat_label)
        y_cursor += 18
        draw.text((col1_x, y_cursor), _format_money(biggest_win), fill=white, font=font_stat_value)
        draw.text((col2_x, y_cursor), f"{win_rate:.1f}% · {total_trades} closes", fill=white, font=font_stat_value)

    # Export to bytes
    buffer = io.BytesIO()
    img.save(buffer, format='PNG', quality=95)
    buffer.seek(0)
    return buffer.getvalue()


def generate_card_for_date(target_date=None, bg_theme='aurora'):
    """
    Generate PnL card untuk tanggal tertentu menggunakan data MT5 live.
    
    Args:
        target_date: datetime.date atau None untuk hari ini (WIB)
        bg_theme: Background theme name
    
    Returns:
        bytes: PNG image data, atau None jika gagal
    """
    try:
        import MetaTrader5 as mt5
        from config import MT5_MAGIC_NUMBER
    except ImportError:
        logger.error("MT5 module not available")
        return None

    if not mt5.initialize():
        logger.error("Cannot connect to MT5")
        return None

    # Tentukan tanggal target (WIB)
    if target_date is None:
        wib_now = datetime.now(timezone.utc) + timedelta(hours=7)
        target_date = wib_now.date()

    date_str = target_date.strftime('%Y-%m-%d')
    month = target_date.month
    year = target_date.year

    # Query deals untuk bulan ini
    start = datetime(year, month, 1)
    if month == 12:
        end = datetime(year + 1, 1, 1)
    else:
        end = datetime(year, month + 1, 1)

    deals = mt5.history_deals_get(
        start - timedelta(days=1),
        end + timedelta(days=1)
    )

    # Process
    day_pnl = 0.0
    day_wins = 0
    day_losses = 0
    day_biggest = 0.0
    month_pnl = 0.0

    if deals:
        for d in deals:
            if d.entry != 1:
                continue

            deal_time_utc = datetime.fromtimestamp(d.time, tz=timezone.utc)
            deal_time_wib = deal_time_utc + timedelta(hours=4)
            deal_date = deal_time_wib.strftime('%Y-%m-%d')

            if deal_time_wib.month != month or deal_time_wib.year != year:
                continue

            pnl = d.profit + d.swap + d.commission
            month_pnl += pnl

            if deal_date == date_str:
                day_pnl += pnl
                if pnl >= 0:
                    day_wins += 1
                    day_biggest = max(day_biggest, pnl)
                else:
                    day_losses += 1

    total = day_wins + day_losses
    wr = (day_wins / total * 100) if total > 0 else 0.0

    # Floating (semua posisi)
    positions = mt5.positions_get()
    floating = sum(p.profit + p.swap + p.commission for p in positions) if positions else 0.0

    return generate_pnl_card(
        date_str=date_str,
        pnl=round(day_pnl, 2),
        realized=round(day_pnl, 2),
        unrealized=round(floating, 2),
        biggest_win=round(day_biggest, 2),
        win_rate=wr,
        total_trades=total,
        bg_theme=bg_theme,
    )


if __name__ == '__main__':
    # Test: generate card dummy
    png_data = generate_pnl_card(
        date_str='2026-06-03',
        pnl=12.50,
        realized=12.50,
        unrealized=-2.30,
        biggest_win=8.75,
        win_rate=66.7,
        total_trades=3,
        bg_theme='aurora',
    )
    with open('test_card.png', 'wb') as f:
        f.write(png_data)
    print("Test card saved to test_card.png")
