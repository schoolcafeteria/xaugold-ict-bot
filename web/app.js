/**
 * ICT Gold Bot — PnL Dashboard Frontend
 * Handles calendar rendering, data fetching, share card generation
 */

// =====================================================================
// STATE
// =====================================================================

const state = {
    currentMonth: new Date().getMonth() + 1,     // 1-12
    currentYear: new Date().getFullYear(),
    selectedDate: null,                            // 'YYYY-MM-DD' or null
    pnlData: null,                                 // API response cache
    cardBg: 'aurora',
    cardPeriod: 'day',                             // 'day' or 'month'
    hideDetails: false,
};

// =====================================================================
// HELPERS
// =====================================================================

function formatMoney(val) {
    if (val === 0) return '$0.00';
    const sign = val > 0 ? '+' : '';
    return `${sign}$${val.toFixed(2)}`;
}

function formatMoneyAbs(val) {
    return `$${Math.abs(val).toFixed(2)}`;
}

function moneyClass(val) {
    if (val > 0) return 'positive';
    if (val < 0) return 'negative';
    return 'neutral';
}

function getMonthName(month) {
    const names = ['January', 'February', 'March', 'April', 'May', 'June',
                   'July', 'August', 'September', 'October', 'November', 'December'];
    return names[month - 1];
}

function getOrdinalSuffix(day) {
    if (day > 3 && day < 21) return 'th';
    switch (day % 10) {
        case 1: return 'st';
        case 2: return 'nd';
        case 3: return 'rd';
        default: return 'th';
    }
}

function formatCardDate(dateStr) {
    const d = new Date(dateStr + 'T00:00:00');
    const day = d.getDate();
    const month = getMonthName(d.getMonth() + 1);
    const year = d.getFullYear();
    return `${day}${getOrdinalSuffix(day)} ${month} ${year}`;
}

function formatCardTitle(dateStr) {
    const d = new Date(dateStr + 'T00:00:00');
    const day = d.getDate();
    const month = getMonthName(d.getMonth() + 1);
    const year = d.getFullYear();
    return `PnL (${month} ${day}, ${year})`;
}

function todayStr() {
    const now = new Date();
    // Approximate WIB (UTC+7)
    const wib = new Date(now.getTime() + (7 * 60 * 60 * 1000) - (now.getTimezoneOffset() * 60 * 1000));
    return wib.toISOString().split('T')[0];
}

function showToast(message, duration = 2500) {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.classList.add('show');
    setTimeout(() => toast.classList.remove('show'), duration);
}

// =====================================================================
// DATA FETCHING
// =====================================================================

async function fetchPnLData(year, month) {
    try {
        const res = await fetch(`/api/pnl?year=${year}&month=${month}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (data.error) throw new Error(data.error);
        return data;
    } catch (err) {
        console.error('Failed to fetch PnL data:', err);
        showToast('⚠️ Failed to load data: ' + err.message, 4000);
        return null;
    }
}

// =====================================================================
// SUMMARY CARDS
// =====================================================================

function renderSummary(data) {
    if (!data || !data.summary) return;

    const s = data.summary;

    // Realized PnL
    const realizedEl = document.getElementById('realized-value');
    realizedEl.textContent = formatMoney(s.realized_pnl);
    realizedEl.className = 'stat-value ' + moneyClass(s.realized_pnl);
    document.getElementById('realized-sub').textContent = `${getMonthName(data.month)} ${data.year}`;

    // Unrealized
    const unrealEl = document.getElementById('unrealized-value');
    unrealEl.textContent = formatMoney(s.unrealized);
    unrealEl.className = 'stat-value ' + moneyClass(s.unrealized);
    document.getElementById('unrealized-sub').textContent = `${s.open_positions} open`;

    // Total Trades
    document.getElementById('trades-value').textContent = s.total_trades;
    document.getElementById('trades-sub').textContent = `W: ${s.wins} / L: ${s.losses}`;

    // Win Rate
    const wrEl = document.getElementById('winrate-value');
    wrEl.textContent = s.win_rate + '%';
    document.getElementById('winrate-sub').textContent =
        s.total_trades > 0 ? `Biggest: ${formatMoney(s.biggest_win)}` : '—';
}

// =====================================================================
// CALENDAR RENDERING
// =====================================================================

function renderCalendar(data) {
    const grid = document.getElementById('calendar-grid');
    const year = state.currentYear;
    const month = state.currentMonth;
    const today = todayStr();

    // Update month label
    document.getElementById('month-label').textContent = `${getMonthName(month)} ${year}`;

    // Clear existing day cells (keep headers)
    const existing = grid.querySelectorAll('.day-cell');
    existing.forEach(el => el.remove());

    // Determine calendar layout
    const firstDay = new Date(year, month - 1, 1).getDay(); // 0=Sun
    const daysInMonth = new Date(year, month, 0).getDate();

    // Daily P&L data
    const daily = data ? data.daily : {};

    // Calculate monthly totals
    let monthlyPnl = 0;
    let monthlyClosed = 0;
    Object.values(daily).forEach(d => {
        monthlyPnl += d.pnl;
        monthlyClosed += d.trades;
    });

    document.getElementById('monthly-closes').textContent = monthlyClosed;
    const totalEl = document.getElementById('monthly-total');
    totalEl.textContent = formatMoney(monthlyPnl);
    totalEl.className = 'summary-total ' + moneyClass(monthlyPnl);

    // Empty cells before first day
    for (let i = 0; i < firstDay; i++) {
        const empty = document.createElement('div');
        empty.className = 'day-cell empty';
        grid.appendChild(empty);
    }

    // Day cells
    for (let day = 1; day <= daysInMonth; day++) {
        const dateStr = `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
        const dayData = daily[dateStr];

        const cell = document.createElement('div');
        cell.className = 'day-cell';
        if (dateStr === today) cell.classList.add('today');
        if (dateStr === state.selectedDate) cell.classList.add('selected');

        // P&L styling
        if (dayData) {
            if (dayData.pnl > 0) cell.classList.add('profit');
            else if (dayData.pnl < 0) cell.classList.add('loss');
        }

        // Day number
        const numEl = document.createElement('div');
        numEl.className = 'day-number';
        numEl.textContent = day;
        cell.appendChild(numEl);

        // P&L value
        const pnlEl = document.createElement('div');
        pnlEl.className = 'day-pnl ' + (dayData ? moneyClass(dayData.pnl) : '');
        pnlEl.textContent = dayData ? formatMoney(dayData.pnl) : '$0';
        cell.appendChild(pnlEl);

        // Trade count
        const tradesEl = document.createElement('div');
        tradesEl.className = 'day-trades';
        tradesEl.textContent = dayData ? `${dayData.trades} trade${dayData.trades > 1 ? 's' : ''}` : '';
        cell.appendChild(tradesEl);

        // Click handler
        cell.addEventListener('click', () => selectDay(dateStr, dayData));

        grid.appendChild(cell);
    }
}

function selectDay(dateStr, dayData) {
    state.selectedDate = dateStr;

    // Update selection visual
    document.querySelectorAll('.day-cell').forEach(c => c.classList.remove('selected'));
    event.currentTarget.classList.add('selected');

    // Update share card
    updateShareCard(dateStr, dayData);

    // Scroll to share section
    document.getElementById('share-section').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// =====================================================================
// SHARE CARD
// =====================================================================

function updateShareCard(dateStr, dayData) {
    const data = state.pnlData;
    const summary = data ? data.summary : {};

    if (state.cardPeriod === 'day') {
        // Single day card
        const pnl = dayData ? dayData.pnl : 0;
        const wins = dayData ? dayData.wins : 0;
        const losses = dayData ? dayData.losses : 0;
        const trades = dayData ? dayData.trades : 0;
        const biggestWin = dayData ? dayData.biggest_win : 0;
        const winRate = trades > 0 ? ((wins / trades) * 100).toFixed(1) : '0.0';

        document.getElementById('sc-date').textContent = formatCardDate(dateStr);
        document.getElementById('sc-title').textContent = formatCardTitle(dateStr);

        const pnlEl = document.getElementById('sc-pnl');
        pnlEl.textContent = formatMoney(pnl);
        pnlEl.className = 'sc-pnl ' + moneyClass(pnl);

        document.getElementById('sc-realized').textContent = formatMoney(pnl);
        document.getElementById('sc-unrealized').textContent = formatMoney(summary.unrealized || 0);
        document.getElementById('sc-biggest').textContent = formatMoney(biggestWin);
        document.getElementById('sc-winrate').textContent = `${winRate}% · ${trades} close${trades !== 1 ? 's' : ''}`;
    } else {
        // Whole month card
        const pnl = summary.realized_pnl || 0;
        const monthName = getMonthName(state.currentMonth);

        document.getElementById('sc-date').textContent = `${monthName} ${state.currentYear}`;
        document.getElementById('sc-title').textContent = `PnL (${monthName} ${state.currentYear})`;

        const pnlEl = document.getElementById('sc-pnl');
        pnlEl.textContent = formatMoney(pnl);
        pnlEl.className = 'sc-pnl ' + moneyClass(pnl);

        document.getElementById('sc-realized').textContent = formatMoney(pnl);
        document.getElementById('sc-unrealized').textContent = formatMoney(summary.unrealized || 0);
        document.getElementById('sc-biggest').textContent = formatMoney(summary.biggest_win || 0);
        document.getElementById('sc-winrate').textContent =
            `${summary.win_rate || 0}% · ${summary.total_trades || 0} closes`;
    }
}

function setCardDefaults() {
    const today = todayStr();
    document.getElementById('sc-date').textContent = formatCardDate(today);
    document.getElementById('sc-title').textContent = formatCardTitle(today);
}

// =====================================================================
// SHARE CARD EXPORT
// =====================================================================

async function saveCardAsPNG() {
    const card = document.getElementById('share-card');
    try {
        const canvas = await html2canvas(card, {
            backgroundColor: null,
            scale: 2,
            useCORS: true,
            logging: false,
        });

        const link = document.createElement('a');
        const dateLabel = state.selectedDate || todayStr();
        link.download = `pnl_${dateLabel}.png`;
        link.href = canvas.toDataURL('image/png');
        link.click();

        showToast('✅ PNG saved successfully!');
    } catch (err) {
        console.error('Save PNG error:', err);
        showToast('❌ Failed to save PNG');
    }
}

async function copyCardToClipboard() {
    const card = document.getElementById('share-card');
    try {
        const canvas = await html2canvas(card, {
            backgroundColor: null,
            scale: 2,
            useCORS: true,
            logging: false,
        });

        canvas.toBlob(async (blob) => {
            try {
                await navigator.clipboard.write([
                    new ClipboardItem({ 'image/png': blob })
                ]);
                showToast('✅ Copied to clipboard!');
            } catch (e) {
                showToast('⚠️ Clipboard access denied. Use Save PNG instead.');
            }
        }, 'image/png');
    } catch (err) {
        console.error('Copy error:', err);
        showToast('❌ Failed to copy');
    }
}

// =====================================================================
// MAIN LOAD & EVENT LISTENERS
// =====================================================================

async function loadMonth(year, month) {
    state.currentYear = year;
    state.currentMonth = month;
    state.selectedDate = null;

    const data = await fetchPnLData(year, month);
    state.pnlData = data;

    renderSummary(data);
    renderCalendar(data);
    setCardDefaults();
}

function initEventListeners() {
    // Month navigation
    document.getElementById('prev-month').addEventListener('click', () => {
        let m = state.currentMonth - 1;
        let y = state.currentYear;
        if (m < 1) { m = 12; y--; }
        loadMonth(y, m);
    });

    document.getElementById('next-month').addEventListener('click', () => {
        let m = state.currentMonth + 1;
        let y = state.currentYear;
        if (m > 12) { m = 1; y++; }
        loadMonth(y, m);
    });

    document.getElementById('today-btn').addEventListener('click', () => {
        const now = new Date();
        loadMonth(now.getFullYear(), now.getMonth() + 1);
    });

    // Background swatches
    document.querySelectorAll('.swatch').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.swatch').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            state.cardBg = btn.dataset.bg;
            document.getElementById('share-card').dataset.bg = state.cardBg;
        });
    });

    // Card period toggle
    document.querySelectorAll('.opt-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.opt-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            state.cardPeriod = btn.dataset.period;

            // Refresh share card with current selection
            if (state.pnlData) {
                const dayData = state.selectedDate
                    ? state.pnlData.daily[state.selectedDate]
                    : null;
                updateShareCard(state.selectedDate || todayStr(), dayData);
            }
        });
    });

    // Hide details checkbox
    document.getElementById('hide-details').addEventListener('change', (e) => {
        state.hideDetails = e.target.checked;
        const card = document.getElementById('share-card');
        card.classList.toggle('hide-details', state.hideDetails);
    });

    // Export buttons
    document.getElementById('save-btn').addEventListener('click', saveCardAsPNG);
    document.getElementById('copy-btn').addEventListener('click', copyCardToClipboard);

    // View toggle (Month/Week/Year) - only Month is implemented for now
    document.querySelectorAll('.view-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.view-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            if (btn.dataset.view !== 'month') {
                showToast('ℹ️ Only Month view is available for now');
                // Reset to month
                setTimeout(() => {
                    document.querySelectorAll('.view-btn').forEach(b => b.classList.remove('active'));
                    document.querySelector('.view-btn[data-view="month"]').classList.add('active');
                }, 1500);
            }
        });
    });
}

// =====================================================================
// INIT
// =====================================================================

document.addEventListener('DOMContentLoaded', () => {
    initEventListeners();
    setCardDefaults();

    // Load current month
    const now = new Date();
    loadMonth(now.getFullYear(), now.getMonth() + 1);
});
