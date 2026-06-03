/**
 * Eleu — PnL Dashboard Frontend
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
    currency: 'USD',                               // 'USD' or 'IDR'
    isGifBg: false,                                // true when background is animated GIF
    gifArrayBuffer: null,                          // raw GIF data for re-encoding
    isVideoBg: false,                              // true when background is video
    videoObjectUrl: null,                          // blob URL for uploaded video
};

// Currency conversion rates (updated from API on load)
const CURRENCY_CONFIG = {
    USD: { symbol: '$', rate: 1, decimals: 2 },
    IDR: { symbol: 'Rp', rate: 16500, decimals: 0 },  // fallback, updated on load
};

// =====================================================================
// HELPERS
// =====================================================================

function formatMoney(val) {
    if (val === 0) return '$0.00';
    const sign = val > 0 ? '+' : '';
    return `${sign}$${val.toFixed(2)}`;
}

function formatCardMoney(val) {
    const cfg = CURRENCY_CONFIG[state.currency] || CURRENCY_CONFIG.USD;
    const converted = val * cfg.rate;
    const abs = Math.abs(converted);
    const sign = converted > 0 ? '+' : (converted < 0 ? '-' : '');

    let formatted;
    if (cfg.decimals === 0) {
        formatted = Math.round(abs).toLocaleString('id-ID');
    } else {
        formatted = abs.toFixed(cfg.decimals).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    }
    return `${sign}${cfg.symbol}${formatted}`;
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
        pnlEl.textContent = formatCardMoney(pnl);
        pnlEl.className = 'sc-pnl ' + moneyClass(pnl);

        document.getElementById('sc-realized').textContent = formatCardMoney(pnl);
        document.getElementById('sc-unrealized').textContent = formatCardMoney(summary.unrealized || 0);
        document.getElementById('sc-biggest').textContent = formatCardMoney(biggestWin);
        document.getElementById('sc-winrate').textContent = `${winRate}% · ${trades} close${trades !== 1 ? 's' : ''}`;
    } else {
        // Whole month card
        const pnl = summary.realized_pnl || 0;
        const monthName = getMonthName(state.currentMonth);

        document.getElementById('sc-date').textContent = `${monthName} ${state.currentYear}`;
        document.getElementById('sc-title').textContent = `PnL (${monthName} ${state.currentYear})`;

        const pnlEl = document.getElementById('sc-pnl');
        pnlEl.textContent = formatCardMoney(pnl);
        pnlEl.className = 'sc-pnl ' + moneyClass(pnl);

        document.getElementById('sc-realized').textContent = formatCardMoney(pnl);
        document.getElementById('sc-unrealized').textContent = formatCardMoney(summary.unrealized || 0);
        document.getElementById('sc-biggest').textContent = formatCardMoney(summary.biggest_win || 0);
        document.getElementById('sc-winrate').textContent =
            `${summary.win_rate || 0}% · ${summary.total_trades || 0} closes`;
    }

    // Update fun comparison
    updateFunComparison();
}

function setCardDefaults() {
    const today = todayStr();
    document.getElementById('sc-date').textContent = formatCardDate(today);
    document.getElementById('sc-title').textContent = formatCardTitle(today);
}

function updateFunComparison() {
    const compEl = document.getElementById('sc-comparison');
    const selected = document.querySelector('input[name="fun-compare"]:checked');

    if (!selected || selected.value === 'none') {
        compEl.style.display = 'none';
        return;
    }

    // Get item name and price
    let itemName, itemPrice;

    if (selected.value === 'custom') {
        itemName = document.getElementById('custom-item-name').value.trim() || 'Item';
        itemPrice = parseFloat(document.getElementById('custom-item-price').value) || 0;
        if (itemPrice <= 0) {
            compEl.style.display = 'none';
            return;
        }
    } else {
        itemName = selected.dataset.name;
        itemPrice = parseFloat(selected.dataset.price);
    }

    // Get current PnL in USD
    const data = state.pnlData;
    let pnlUsd = 0;

    if (state.cardPeriod === 'day' && state.selectedDate) {
        const dayData = data ? data.daily[state.selectedDate] : null;
        pnlUsd = dayData ? dayData.pnl : 0;
    } else if (state.cardPeriod === 'month' && data) {
        pnlUsd = data.summary.realized_pnl || 0;
    }

    // Convert USD to IDR using live rate
    const idrRate = CURRENCY_CONFIG.IDR.rate;
    const pnlIdr = Math.abs(pnlUsd) * idrRate;

    // Calculate item count
    const count = Math.floor(pnlIdr / itemPrice);
    const priceFormatted = 'Rp' + itemPrice.toLocaleString('id-ID');

    if (count > 0) {
        compEl.textContent = `≈ ${count.toLocaleString('id-ID')} ${itemName} (@ ${priceFormatted} each)`;
        compEl.style.display = 'block';
    } else {
        compEl.textContent = `< 1 ${itemName} (@ ${priceFormatted} each)`;
        compEl.style.display = 'block';
    }
}

// =====================================================================
// SHARE CARD EXPORT
// =====================================================================

async function saveCardAsPNG() {
    const card = document.getElementById('share-card');
    try {
        const raw = await html2canvas(card, {
            backgroundColor: null,
            scale: 2,
            useCORS: true,
            logging: false,
        });

        // Apply rounded corner clip (transparent outside)
        const w = raw.width;
        const h = raw.height;
        const r = 22 * 2; // match CSS border-radius with margin

        const canvas = document.createElement('canvas');
        canvas.width = w;
        canvas.height = h;
        const ctx = canvas.getContext('2d');

        // Clip to rounded rect FIRST — nothing outside will be drawn
        ctx.beginPath();
        ctx.moveTo(r, 0);
        ctx.lineTo(w - r, 0);
        ctx.quadraticCurveTo(w, 0, w, r);
        ctx.lineTo(w, h - r);
        ctx.quadraticCurveTo(w, h, w - r, h);
        ctx.lineTo(r, h);
        ctx.quadraticCurveTo(0, h, 0, h - r);
        ctx.lineTo(0, r);
        ctx.quadraticCurveTo(0, 0, r, 0);
        ctx.closePath();
        ctx.clip();

        // Now draw content — only inside rounded area
        ctx.drawImage(raw, 0, 0);

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

async function saveCardAsVideo() {
    showToast('⏳ Generating video... please wait');

    try {
        const card = document.getElementById('share-card');
        const cardRect = card.getBoundingClientRect();
        const cardW = Math.round(cardRect.width);
        const cardH = Math.round(cardRect.height);

        // 1. Capture card overlay (text/stats) as transparent image
        const origBgImage = card.style.backgroundImage;
        const origBg = card.style.background;
        const origDataBg = card.dataset.bg;
        const hadVideoClass = card.classList.contains('has-video');

        card.style.backgroundImage = 'none';
        card.style.background = 'transparent';
        card.dataset.bg = '';
        card.classList.remove('has-video');

        const videoEl = document.getElementById('sc-video-bg');
        const videoDisplay = videoEl.style.display;
        videoEl.style.display = 'none';

        const overlayCanvas = await html2canvas(card, {
            backgroundColor: null,
            scale: 1,
            useCORS: true,
            logging: false,
            width: cardW,
            height: cardH,
        });

        // Restore
        card.style.backgroundImage = origBgImage;
        card.style.background = origBg || '';
        card.dataset.bg = origDataBg;
        if (hadVideoClass) card.classList.add('has-video');
        videoEl.style.display = videoDisplay;

        // 2. Set up recording canvas
        const recCanvas = document.createElement('canvas');
        recCanvas.width = cardW;
        recCanvas.height = cardH;
        const ctx = recCanvas.getContext('2d');

        // 3. Set up MediaRecorder
        const stream = recCanvas.captureStream(30);
        const mimeType = MediaRecorder.isTypeSupported('video/mp4; codecs=avc1')
            ? 'video/mp4; codecs=avc1'
            : MediaRecorder.isTypeSupported('video/webm; codecs=vp9')
                ? 'video/webm; codecs=vp9'
                : 'video/webm';

        const recorder = new MediaRecorder(stream, {
            mimeType,
            videoBitsPerSecond: 4000000,
        });
        const chunks = [];
        recorder.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data); };

        const isWebM = mimeType.includes('webm');
        const fileExt = isWebM ? 'webm' : 'mp4';

        recorder.onstop = () => {
            const blob = new Blob(chunks, { type: mimeType });
            const link = document.createElement('a');
            const dateLabel = state.selectedDate || todayStr();
            link.download = `pnl_${dateLabel}.${fileExt}`;
            link.href = URL.createObjectURL(blob);
            link.click();
            URL.revokeObjectURL(link.href);
            showToast(`✅ Video saved as .${fileExt}!`);
        };

        recorder.start();

        // 4. Draw frames
        if (state.isGifBg && state.gifArrayBuffer) {
            const gifData = gifuct.parseGIF(state.gifArrayBuffer);
            const frames = gifuct.decompressFrames(gifData, true);

            const gifCanvas = document.createElement('canvas');
            gifCanvas.width = frames[0].dims.width;
            gifCanvas.height = frames[0].dims.height;
            const gifCtx = gifCanvas.getContext('2d');

            const loops = 3;
            for (let loop = 0; loop < loops; loop++) {
                for (const frame of frames) {
                    const { dims, patch, delay, disposalType } = frame;
                    const imgData = new ImageData(new Uint8ClampedArray(patch), dims.width, dims.height);

                    if (disposalType === 2) gifCtx.clearRect(0, 0, gifCanvas.width, gifCanvas.height);

                    const pc = document.createElement('canvas');
                    pc.width = dims.width; pc.height = dims.height;
                    pc.getContext('2d').putImageData(imgData, 0, 0);
                    gifCtx.drawImage(pc, dims.left, dims.top);

                    ctx.clearRect(0, 0, cardW, cardH);
                    ctx.drawImage(gifCanvas, 0, 0, cardW, cardH);
                    ctx.fillStyle = 'rgba(0,0,0,0.45)';
                    ctx.fillRect(0, 0, cardW, cardH);
                    ctx.drawImage(overlayCanvas, 0, 0, cardW, cardH);

                    await new Promise(r => setTimeout(r, delay || 100));
                }
            }

            recorder.stop();

        } else if (state.isVideoBg && videoEl.src) {
            videoEl.currentTime = 0;
            await videoEl.play();

            const duration = videoEl.duration || 5;
            const startTime = performance.now();
            const maxDuration = Math.min(duration, 15) * 1000;

            await new Promise((resolve) => {
                function drawFrame() {
                    const elapsed = performance.now() - startTime;
                    if (elapsed >= maxDuration || videoEl.ended) {
                        resolve();
                        return;
                    }

                    ctx.clearRect(0, 0, cardW, cardH);
                    ctx.drawImage(videoEl, 0, 0, cardW, cardH);
                    ctx.fillStyle = 'rgba(0,0,0,0.45)';
                    ctx.fillRect(0, 0, cardW, cardH);
                    ctx.drawImage(overlayCanvas, 0, 0, cardW, cardH);

                    requestAnimationFrame(drawFrame);
                }
                drawFrame();
            });

            recorder.stop();
        }

    } catch (err) {
        console.error('Save video error:', err);
        showToast('❌ Failed to save video: ' + err.message);
    }
}

async function saveCard() {
    if ((state.isGifBg && state.gifArrayBuffer) || state.isVideoBg) {
        return saveCardAsVideo();
    }
    return saveCardAsPNG();
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
            const card = document.getElementById('share-card');
            // Clear all custom backgrounds
            card.style.backgroundImage = '';
            card.classList.remove('has-video');
            const videoEl = document.getElementById('sc-video-bg');
            videoEl.pause(); videoEl.removeAttribute('src'); videoEl.load();
            if (state.videoObjectUrl) URL.revokeObjectURL(state.videoObjectUrl);
            state.customBgUrl = null;
            state.isGifBg = false;
            state.gifArrayBuffer = null;
            state.isVideoBg = false;
            state.videoObjectUrl = null;
            document.getElementById('upload-preview').style.display = 'none';
            document.getElementById('save-btn-text').textContent = 'Save PNG';

            document.querySelectorAll('.swatch').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            state.cardBg = btn.dataset.bg;
            card.dataset.bg = state.cardBg;
        });
    });

    // Custom background upload
    const uploadBtn = document.getElementById('upload-bg-btn');
    const fileInput = document.getElementById('bg-file-input');
    const uploadPreview = document.getElementById('upload-preview');
    const uploadThumb = document.getElementById('upload-thumb');
    const uploadRemove = document.getElementById('upload-remove');

    uploadBtn.addEventListener('click', () => fileInput.click());

    fileInput.addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (!file) return;

        const isImage = file.type.startsWith('image/');
        const isVideo = file.type.startsWith('video/');

        if (!isImage && !isVideo) {
            showToast('⚠️ Unsupported file type. Use PNG, JPG, GIF, or MP4.');
            return;
        }

        // Validate file size (max 50MB for video, 10MB for images)
        const maxSize = isVideo ? 50 * 1024 * 1024 : 10 * 1024 * 1024;
        if (file.size > maxSize) {
            showToast(`⚠️ File too large. Max ${isVideo ? '50' : '10'}MB.`);
            return;
        }

        const isGif = file.type === 'image/gif';
        const isAnimated = isGif || isVideo;

        // Reset previous state
        state.isGifBg = isGif;
        state.isVideoBg = isVideo;
        state.gifArrayBuffer = null;
        if (state.videoObjectUrl) URL.revokeObjectURL(state.videoObjectUrl);
        state.videoObjectUrl = null;

        // Store GIF ArrayBuffer for frame parsing
        if (isGif) {
            file.arrayBuffer().then(buf => { state.gifArrayBuffer = buf; });
        }

        // Update save button
        document.getElementById('save-btn-text').textContent = isAnimated ? 'Save Video' : 'Save PNG';

        const card = document.getElementById('share-card');
        const videoEl = document.getElementById('sc-video-bg');
        document.querySelectorAll('.swatch').forEach(b => b.classList.remove('active'));

        if (isVideo) {
            // --- Video background ---
            const blobUrl = URL.createObjectURL(file);
            state.videoObjectUrl = blobUrl;
            state.customBgUrl = blobUrl;

            // Set video source
            videoEl.src = blobUrl;
            videoEl.play();

            // Show card in video mode
            card.dataset.bg = 'custom';
            card.style.backgroundImage = 'none';
            state.cardBg = 'custom';
            card.classList.add('has-video');

            // Preview thumbnail (use video poster or first frame)
            uploadThumb.src = '';
            videoEl.addEventListener('loadeddata', () => {
                const tc = document.createElement('canvas');
                tc.width = videoEl.videoWidth;
                tc.height = videoEl.videoHeight;
                tc.getContext('2d').drawImage(videoEl, 0, 0);
                uploadThumb.src = tc.toDataURL();
            }, { once: true });
            uploadPreview.style.display = 'block';

            showToast('✅ Video background applied!');
        } else {
            // --- Image/GIF background ---
            videoEl.pause(); videoEl.removeAttribute('src'); videoEl.load();
            card.classList.remove('has-video');

            const reader = new FileReader();
            reader.onload = (evt) => {
                const dataUrl = evt.target.result;
                state.customBgUrl = dataUrl;

                uploadThumb.src = dataUrl;
                uploadPreview.style.display = 'block';

                card.dataset.bg = 'custom';
                state.cardBg = 'custom';
                card.style.backgroundImage = `linear-gradient(rgba(0,0,0,0.45), rgba(0,0,0,0.55)), url("${dataUrl}")`;

                showToast(isGif ? '✅ GIF background applied!' : '✅ Custom background applied!');
            };
            reader.readAsDataURL(file);
        }

        fileInput.value = '';
    });

    uploadRemove.addEventListener('click', () => {
        // Remove all custom backgrounds, revert to aurora
        state.customBgUrl = null;
        state.isGifBg = false;
        state.gifArrayBuffer = null;
        state.isVideoBg = false;
        if (state.videoObjectUrl) URL.revokeObjectURL(state.videoObjectUrl);
        state.videoObjectUrl = null;
        uploadPreview.style.display = 'none';
        document.getElementById('save-btn-text').textContent = 'Save PNG';

        const card = document.getElementById('share-card');
        const videoEl = document.getElementById('sc-video-bg');
        videoEl.pause(); videoEl.removeAttribute('src'); videoEl.load();
        card.classList.remove('has-video');
        card.style.backgroundImage = '';
        card.dataset.bg = 'aurora';
        state.cardBg = 'aurora';

        document.querySelectorAll('.swatch').forEach(b => b.classList.remove('active'));
        document.querySelector('.swatch.aurora').classList.add('active');

        showToast('🗑️ Background removed');
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

    // Currency select
    document.getElementById('currency-select').addEventListener('change', (e) => {
        state.currency = e.target.value;
        // Refresh share card with new currency
        if (state.pnlData) {
            const dayData = state.selectedDate
                ? state.pnlData.daily[state.selectedDate]
                : null;
            updateShareCard(state.selectedDate || todayStr(), dayData);
        }
    });

    // Fun comparison radio handlers
    document.querySelectorAll('input[name="fun-compare"]').forEach(radio => {
        radio.addEventListener('change', () => {
            const customGroup = document.getElementById('custom-item-group');
            customGroup.style.display = radio.value === 'custom' ? 'flex' : 'none';
            updateFunComparison();
        });
    });

    // Custom item inputs
    document.getElementById('custom-item-name').addEventListener('input', updateFunComparison);
    document.getElementById('custom-item-price').addEventListener('input', updateFunComparison);

    // Export buttons
    document.getElementById('save-btn').addEventListener('click', saveCard);
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

document.addEventListener('DOMContentLoaded', async () => {
    initEventListeners();
    setCardDefaults();

    // Fetch kurs real-time
    try {
        const res = await fetch('/api/rate');
        if (res.ok) {
            const data = await res.json();
            if (data.IDR) {
                CURRENCY_CONFIG.IDR.rate = data.IDR;
                console.log(`💱 Live rate: 1 USD = Rp${data.IDR.toLocaleString('id-ID')}`);
            }
        }
    } catch (e) {
        console.warn('Using fallback exchange rate:', e.message);
    }

    // Load current month
    const now = new Date();
    loadMonth(now.getFullYear(), now.getMonth() + 1);
});
