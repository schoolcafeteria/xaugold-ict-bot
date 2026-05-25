/**
 * XAUUSD Data Fetcher
 * Mengambil data candle (OHLC) dan indikator teknikal dari TradingView
 * menggunakan library @mathieuc/tradingview (WebSocket).
 *
 * Usage: node xauusd_fetcher.js [symbol] [timeframe] [limit] [--to YYYY-MM-DD] [--range N]
 * Contoh:
 *   node xauusd_fetcher.js OANDA:XAUUSD 5 200
 *   node xauusd_fetcher.js OANDA:XAUUSD 5 2000 --to 2026-05-22 --range 5000
 *
 * Output: JSON ke stdout
 */

const TradingView = require('@mathieuc/tradingview');
const { RSI, EMA, SMA, MACD, ATR } = require('technicalindicators');

// ============================================================
// Konfigurasi default
// ============================================================
const DEFAULT_SYMBOL = 'FOREXCOM:XAUUSD';
const DEFAULT_TIMEFRAME = '5';   // 5 menit
const DEFAULT_LIMIT = 200;
const SMC_INDICATOR_ID = 'PUB;CnB3fSph'; // Smart Money Concepts [LuxAlgo]
const TIMEOUT_MS = 30000; // 30 detik timeout

// ============================================================
// Parse argumen CLI
// ============================================================
const args = process.argv.slice(2);
const symbol = args[0] || DEFAULT_SYMBOL;
const timeframe = args[1] || DEFAULT_TIMEFRAME;
const limit = parseInt(args[2]) || DEFAULT_LIMIT;

// Parse optional --to dan --range flags
let toTimestamp = null;
let rangeValue = null;
for (let i = 3; i < args.length; i++) {
  if (args[i] === '--to' && args[i + 1]) {
    const d = new Date(args[i + 1] + 'T23:59:59Z');
    toTimestamp = Math.round(d.getTime() / 1000);
    i++;
  } else if (args[i] === '--range' && args[i + 1]) {
    rangeValue = parseInt(args[i + 1]);
    i++;
  }
}

// ============================================================
// Fungsi utilitas: Hitung indikator teknikal lokal
// ============================================================
function calculateIndicators(candles) {
  const closes = candles.map(c => c.close);
  const highs = candles.map(c => c.high);
  const lows = candles.map(c => c.low);

  // RSI (14)
  const rsiValues = RSI.calculate({ values: closes, period: 14 });
  // Pad awal dengan null agar panjang array sama
  const rsiPadded = new Array(closes.length - rsiValues.length).fill(null).concat(rsiValues);

  // EMA (20)
  const ema20Values = EMA.calculate({ values: closes, period: 20 });
  const ema20Padded = new Array(closes.length - ema20Values.length).fill(null).concat(ema20Values);

  // EMA (200) - Filter Trend Kuat
  const ema200Values = EMA.calculate({ values: closes, period: 200 });
  const ema200Padded = new Array(closes.length - ema200Values.length).fill(null).concat(ema200Values);

  // SMA (50)
  const sma50Values = SMA.calculate({ values: closes, period: 50 });
  const sma50Padded = new Array(closes.length - sma50Values.length).fill(null).concat(sma50Values);

  // MACD (12, 26, 9)
  const macdValues = MACD.calculate({
    values: closes,
    fastPeriod: 12,
    slowPeriod: 26,
    signalPeriod: 9,
    SimpleMAOscillator: false,
    SimpleMASignal: false,
  });
  const macdPadded = new Array(closes.length - macdValues.length).fill(null).concat(macdValues);

  // ATR (14) - untuk SL/TP dinamis
  const atrValues = ATR.calculate({ high: highs, low: lows, close: closes, period: 14 });
  const atrPadded = new Array(closes.length - atrValues.length).fill(null).concat(atrValues);

  // Gabungkan ke setiap candle
  return candles.map((candle, i) => ({
    ...candle,
    rsi_14: rsiPadded[i] !== null ? Math.round(rsiPadded[i] * 100) / 100 : null,
    ema_20: ema20Padded[i] !== null ? Math.round(ema20Padded[i] * 100) / 100 : null,
    ema_200: ema200Padded[i] !== null ? Math.round(ema200Padded[i] * 100) / 100 : null,
    sma_50: sma50Padded[i] !== null ? Math.round(sma50Padded[i] * 100) / 100 : null,
    macd: macdPadded[i] !== null ? {
      macd: Math.round(macdPadded[i].MACD * 10000) / 10000,
      signal: Math.round(macdPadded[i].signal * 10000) / 10000,
      histogram: Math.round(macdPadded[i].histogram * 10000) / 10000,
    } : null,
    atr_14: atrPadded[i] !== null ? Math.round(atrPadded[i] * 100) / 100 : null,
  }));
}

// ============================================================
// Fungsi utilitas: Parse data grafik SMC (boxes, lines, labels)
// ============================================================
function parseSmcGraphics(graphics) {
  const result = {
    order_blocks: [],
    bos_lines: [],
    choch_lines: [],
    labels: [],
  };

  if (!graphics) return result;

  try {
    // Parse boxes (Order Blocks biasanya berupa box)
    if (graphics.boxes && Array.isArray(graphics.boxes)) {
      for (const box of graphics.boxes) {
        result.order_blocks.push({
          type: 'order_block',
          x1: box.x1, // bar index awal
          y1: box.y1, // harga bawah
          x2: box.x2, // bar index akhir
          y2: box.y2, // harga atas
          color: box.color || null,
        });
      }
    }

    // Parse lines (BOS dan CHoCH biasanya berupa garis)
    if (graphics.lines && Array.isArray(graphics.lines)) {
      for (const line of graphics.lines) {
        const label = (line.text || '').toLowerCase();
        const entry = {
          x1: line.x1,
          y1: line.y1,
          x2: line.x2,
          y2: line.y2,
          color: line.color || null,
          text: line.text || '',
        };
        if (label.includes('bos')) {
          result.bos_lines.push(entry);
        } else if (label.includes('choch')) {
          result.choch_lines.push(entry);
        }
      }
    }

    // Parse labels
    if (graphics.labels && Array.isArray(graphics.labels)) {
      for (const lbl of graphics.labels) {
        result.labels.push({
          x: lbl.x,
          y: lbl.y,
          text: lbl.text || '',
          color: lbl.color || null,
        });
      }
    }
  } catch (err) {
    // Jika parsing gagal, kembalikan objek kosong
  }

  return result;
}

// ============================================================
// Fungsi utama
// ============================================================
async function main() {
  let client;

  try {
    // 1. Buat client TradingView dengan login sessionid & signature Anda
    client = new TradingView.Client({
      token: 'iu8zb3ipqe32ppvja6saf2vu8ki859gk',
      signature: 'v3:MrpuUhiCjSBXW+SxPIrne6kpc2bOKBXWYJvxqg1gZcY='
    });

    // 2. Buat sesi chart
    const chart = new client.Session.Chart();

    // 3. Set market dengan timeframe dan range yang ditentukan
    const marketOpts = { timeframe: timeframe };
    if (rangeValue) marketOpts.range = rangeValue;
    if (toTimestamp) marketOpts.to = toTimestamp;
    
    chart.setMarket(symbol, marketOpts);

    // 4. Tunggu data candle dimuat
    const candles = await new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        reject(new Error(`Timeout: Tidak ada data dalam ${TIMEOUT_MS / 1000} detik`));
      }, TIMEOUT_MS);

      chart.onUpdate(() => {
        if (chart.periods && chart.periods.length > 0) {
          clearTimeout(timer);

          // Ambil candle, batasi sesuai limit
          const rawCandles = chart.periods.slice(0, limit).map(p => ({
            time: p.time,
            open: p.open,
            high: p.max,
            low: p.min,
            close: p.close,
            volume: p.volume || 0,
          }));

          // Urutkan dari yang terlama ke terbaru
          rawCandles.sort((a, b) => a.time - b.time);
          resolve(rawCandles);
        }
      });
    });

    // 5. Hitung indikator teknikal lokal
    const candlesWithIndicators = calculateIndicators(candles);

    // 6. Coba muat indikator SMC LuxAlgo (Lapis 1)
    let smcData = null;
    let smcAvailable = false;

    try {
      const indicator = await TradingView.getIndicator(SMC_INDICATOR_ID);

      if (indicator) {
        const study = new chart.Study(indicator);

        smcData = await new Promise((resolve, reject) => {
          const smcTimer = setTimeout(() => {
            reject(new Error('SMC indicator timeout'));
          }, 15000);

          study.onUpdate(() => {
            clearTimeout(smcTimer);
            const graphics = study.graphics || null;
            const periods = study.periods || [];
            resolve({ graphics, periods });
          });
        });

        smcAvailable = true;
      }
    } catch (smcErr) {
      // SMC tidak tersedia, fallback ke kalkulasi lokal nanti
      smcAvailable = false;
    }

    // 7. Parse data SMC jika tersedia
    const smcParsed = smcAvailable ? parseSmcGraphics(smcData?.graphics) : null;

    // 8. Susun output JSON
    const output = {
      meta: {
        symbol: symbol,
        timeframe: timeframe,
        candle_count: candlesWithIndicators.length,
        fetched_at: new Date().toISOString(),
        smc_available: smcAvailable,
      },
      candles: candlesWithIndicators,
      smc: smcParsed,
      latest: candlesWithIndicators.length > 0
        ? candlesWithIndicators[candlesWithIndicators.length - 1]
        : null,
    };

    // 9. Output JSON ke stdout
    console.log(JSON.stringify(output, null, 2));

    // 10. Tutup koneksi
    client.end();
    process.exit(0);

  } catch (err) {
    // Error handling: tetap output JSON valid agar Python bisa membaca
    const errorOutput = {
      meta: {
        symbol: symbol,
        timeframe: timeframe,
        candle_count: 0,
        fetched_at: new Date().toISOString(),
        smc_available: false,
        error: err.message,
      },
      candles: [],
      smc: null,
      latest: null,
    };

    console.log(JSON.stringify(errorOutput, null, 2));

    if (client) client.end();
    process.exit(1);
  }
}

main();
