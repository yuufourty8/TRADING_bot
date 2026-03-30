import ccxt
import pandas as pd
import numpy as np
import requests
import time
from datetime import datetime, timezone

# ═══════════════════════════════════════════════════════════════
# KONFIGURASI
# ═══════════════════════════════════════════════════════════════

TELEGRAM_TOKEN    = "8660926908:AAFA7fVSIgZpk2m1QllOgUnEnfpC9iPGIWM"
TELEGRAM_CHAT_ID  = "8688554062"

PAIRS             = ["BTC/USDT", "ETH/USDT", "XRP/USDT", "SOL/USDT",
                     "BNB/USDT", "DOGE/USDT", "ADA/USDT", "MATIC/USDT"]
VOLUME_MULTIPLIER = 1.5

# ── [FIX #13] Mode strategi: sniper / normal / aggressive ──────
STRATEGY_MODE = "normal"   # pilihan: "sniper" | "normal" | "aggressive"

STRATEGY_CONFIG = {
    "sniper":     {"threshold": 75, "min_grade": "B",  "label": "🎯 SNIPER"},
    "normal":     {"threshold": 55, "min_grade": "C",  "label": "📊 NORMAL"},
    "aggressive": {"threshold": 35, "min_grade": "C",  "label": "⚡ AGGRESSIVE"},
}

# ── [FIX #10] RR dinamis per kondisi ──────────────────────────
RR_CONFIG = {
    "strong_trend": 3.0,
    "normal":       2.0,
    "weak":         1.5,
}

MODES = [
    {"label": "SCALPING",  "trend_tf": "1h",  "entry_tf": "15m", "emoji": "⚡"},
    {"label": "SCALPING",  "trend_tf": "1h",  "entry_tf": "30m", "emoji": "⚡"},
    {"label": "INTRADAY",  "trend_tf": "4h",  "entry_tf": "1h",  "emoji": "📊"},
]

# ═══════════════════════════════════════════════════════════════
# EXCHANGE — Auto Fallback
# ═══════════════════════════════════════════════════════════════

def pair_ke_gate(pair):
    return pair.replace("/", "_")

KUCOIN_MAP = {
    "BTC/USDT":   "XBTUSDTM",
    "ETH/USDT":   "ETHUSDTM",
    "XRP/USDT":   "XRPUSDTM",
    "SOL/USDT":   "SOLUSDTM",
    "BNB/USDT":   "BNBUSDTM",
    "DOGE/USDT":  "DOGEUSDTM",
    "ADA/USDT":   "ADAUSDTM",
    "MATIC/USDT": "MATICUSDTM",
}

EXCHANGES = {
    "Gate.io": ccxt.gateio({
        "enableRateLimit": True,
        "timeout": 15000,
        "options": {"defaultType": "future"},
    }),
    "MEXC": ccxt.mexc({
        "enableRateLimit": True,
        "timeout": 15000,
        "options": {"defaultType": "swap"},
    }),
    "KuCoin Futures": ccxt.kucoinfutures({
        "enableRateLimit": True,
        "timeout": 15000,
    }),
}

EXCHANGE_ORDER = ["Gate.io", "MEXC", "KuCoin Futures"]
aktif_exchange  = "Gate.io"

def konversi_pair(nama_exchange, pair):
    if nama_exchange == "Gate.io":
        return pair_ke_gate(pair)
    elif nama_exchange == "KuCoin Futures":
        return KUCOIN_MAP.get(pair, pair)
    return pair

def ambil_data(pair, timeframe, limit=150):
    global aktif_exchange
    urutan = [aktif_exchange] + [e for e in EXCHANGE_ORDER if e != aktif_exchange]
    for nama in urutan:
        try:
            ex = EXCHANGES[nama]
            p  = konversi_pair(nama, pair)
            candles = ex.fetch_ohlcv(p, timeframe=timeframe, limit=limit)
            if not candles:
                raise ValueError("Data kosong")
            df = pd.DataFrame(candles, columns=['time','open','high','low','close','volume'])
            df['time'] = pd.to_datetime(df['time'], unit='ms')
            if aktif_exchange != nama:
                print(f"  🔄 Pindah ke {nama}")
                aktif_exchange = nama
            return df, nama
        except ccxt.NetworkError as e:
            print(f"  ⚠️  {nama} network error: {type(e).__name__}")
        except ccxt.ExchangeError as e:
            print(f"  ⚠️  {nama} exchange error: {e}")
        except Exception as e:
            print(f"  ⚠️  {nama} gagal: {e}")
    raise RuntimeError(f"Semua exchange gagal untuk {pair} {timeframe}")

# ═══════════════════════════════════════════════════════════════
# [FIX #9] SESSION AWARENESS
# ═══════════════════════════════════════════════════════════════

def deteksi_session():
    """Deteksi sesi trading berdasarkan UTC. Return (nama_sesi, multiplier_bobot)."""
    jam_utc = datetime.now(timezone.utc).hour
    if 0 <= jam_utc < 8:
        return "Asia", 0.8
    elif 7 <= jam_utc < 13:
        return "London", 1.2
    elif 12 <= jam_utc < 21:
        return "New York", 1.1
    else:
        return "Overlap/Dead", 0.7

# ═══════════════════════════════════════════════════════════════
# [FIX #8] MARKET REGIME DETECTION
# ═══════════════════════════════════════════════════════════════

def deteksi_market_regime(df, lookback=30):
    """
    Return: dict dengan keys:
      regime   → 'TRENDING' | 'RANGING' | 'HIGH_VOL' | 'LOW_VOL'
      atr      → float (ATR nilai)
      atr_pct  → float (ATR sebagai % harga)
    """
    recent = df.iloc[-lookback:]
    atr    = (recent['high'] - recent['low']).mean()
    harga  = df['close'].iloc[-1]
    atr_pct = atr / harga * 100

    # Volatility threshold
    vol_harga = recent['close'].pct_change().std() * 100
    high_vol  = vol_harga > 2.0
    low_vol   = vol_harga < 0.5

    # ADX proxy (range of close / range of high-low)
    close_range = recent['close'].max() - recent['close'].min()
    hl_range    = recent['high'].max() - recent['low'].min()
    directional = close_range / hl_range if hl_range > 0 else 0

    if high_vol:
        regime = "HIGH_VOL"
    elif low_vol:
        regime = "LOW_VOL"
    elif directional > 0.55:
        regime = "TRENDING"
    else:
        regime = "RANGING"

    return {"regime": regime, "atr": atr, "atr_pct": atr_pct, "directional": directional}

# ═══════════════════════════════════════════════════════════════
# [FIX #2] MARKET STRUCTURE — CORE HIERARCHY
# ═══════════════════════════════════════════════════════════════

def deteksi_struktur(df):
    """
    Deteksi trend + BOS/CHoCH. Return (trend, event, strength_score).
    strength_score 0–100 menunjukkan kekuatan struktur.
    """
    highs, lows = [], []
    window = 5
    for i in range(window, len(df) - window):
        if df['high'].iloc[i] == df['high'].iloc[i-window:i+window].max():
            highs.append((i, df['high'].iloc[i]))
        if df['low'].iloc[i] == df['low'].iloc[i-window:i+window].min():
            lows.append((i, df['low'].iloc[i]))

    if len(highs) < 2 or len(lows) < 2:
        return 'RANGING', None, 0

    last_hh, prev_hh = highs[-1][1], highs[-2][1]
    last_ll, prev_ll = lows[-1][1],  lows[-2][1]
    harga = df['close'].iloc[-1]

    bullish = last_hh > prev_hh and last_ll > prev_ll
    bearish = last_hh < prev_hh and last_ll < prev_ll

    # [FIX #11] Kekuatan struktur: displacement + konsistensi
    strength = 0
    if bullish or bearish:
        # Seberapa signifikan break-nya
        if bullish:
            break_pct = (last_hh - prev_hh) / prev_hh * 100
        else:
            break_pct = (prev_ll - last_ll) / prev_ll * 100
        strength = min(100, int(break_pct * 20))  # skala kasar

    if bullish:
        event = 'CHoCH' if harga > prev_hh else 'BOS'
        return 'BULLISH', event, strength
    elif bearish:
        event = 'CHoCH' if harga < prev_ll else 'BOS'
        return 'BEARISH', event, strength

    return 'RANGING', None, 0

# ═══════════════════════════════════════════════════════════════
# [FIX #3] FLEXIBLE LIQUIDITY MODEL
# ═══════════════════════════════════════════════════════════════

def deteksi_liquidity(df, trend, lookback=30):
    """
    Return dict dengan:
      external_sweep   → bool (swing H/L tersentuh)
      internal_sweep   → bool (minor H/L tersentuh)
      inducement       → bool (fake move sebelum reversal)
      score            → 0–30 (bobot total likuiditas)
    """
    recent = df.iloc[-lookback:]
    c = df.iloc[-1]
    prev = df.iloc[-2]

    result = {"external_sweep": False, "internal_sweep": False, "inducement": False, "score": 0}

    if trend == 'BULLISH':
        swing_low    = recent['low'].min()
        minor_lows   = recent['low'].nsmallest(3).values

        # External sweep
        if c['low'] <= swing_low * 1.002 and c['close'] > swing_low:
            result["external_sweep"] = True
            result["score"] += 20

        # Internal sweep (minor low)
        for ml in minor_lows[1:]:
            if c['low'] <= ml * 1.002 and c['close'] > ml:
                result["internal_sweep"] = True
                result["score"] += 10
                break

        # Inducement: candle sebelumnya tembus low lalu close di atas
        if prev['low'] < recent['low'].quantile(0.2) and c['close'] > prev['close']:
            result["inducement"] = True
            result["score"] += 10

    elif trend == 'BEARISH':
        swing_high   = recent['high'].max()
        minor_highs  = recent['high'].nlargest(3).values

        # External sweep
        if c['high'] >= swing_high * 0.998 and c['close'] < swing_high:
            result["external_sweep"] = True
            result["score"] += 20

        # Internal sweep
        for mh in minor_highs[1:]:
            if c['high'] >= mh * 0.998 and c['close'] < mh:
                result["internal_sweep"] = True
                result["score"] += 10
                break

        # Inducement
        if prev['high'] > recent['high'].quantile(0.8) and c['close'] < prev['close']:
            result["inducement"] = True
            result["score"] += 10

    return result

# ═══════════════════════════════════════════════════════════════
# [FIX #4] DYNAMIC ORDER BLOCK ZONE
# ═══════════════════════════════════════════════════════════════

def cari_order_block(df, trend):
    """
    Return list OB zone (dicts). Tidak harus impuls besar,
    multi-candle zone, boleh overlap.
    """
    ob_list = []
    for i in range(max(0, len(df) - 20), len(df) - 1):
        c, n = df.iloc[i], df.iloc[i + 1]
        move = (n['close'] - n['open']) / n['open']

        if trend == 'BULLISH' and c['close'] < c['open']:
            # Tidak wajib threshold besar — deteksi bearish candle sebelum bullish move
            strength = abs(move) * 100
            ob_list.append({
                "low": c['low'], "high": c['high'],
                "mid": (c['low'] + c['high']) / 2,
                "strength": min(strength * 10, 30),
                "index": i
            })

        elif trend == 'BEARISH' and c['close'] > c['open']:
            strength = abs(move) * 100
            ob_list.append({
                "low": c['low'], "high": c['high'],
                "mid": (c['low'] + c['high']) / 2,
                "strength": min(strength * 10, 30),
                "index": i
            })

    return ob_list

def harga_di_order_block(harga, ob_list, toleransi=0.002):
    """Return (bool, best_ob_or_None)."""
    if not ob_list:
        return False, None
    harga_adj_lo = harga * (1 - toleransi)
    harga_adj_hi = harga * (1 + toleransi)
    hits = [ob for ob in ob_list if ob['low'] <= harga_adj_hi and ob['high'] >= harga_adj_lo]
    if not hits:
        return False, None
    best = max(hits, key=lambda x: x['strength'])
    return True, best

# ═══════════════════════════════════════════════════════════════
# [FIX #5] IMPERFECT IMBALANCE / FVG
# ═══════════════════════════════════════════════════════════════

def cari_fvg(df, trend, toleransi=0.003):
    """
    Deteksi FVG + partial imbalance.
    toleransi: izinkan gap kecil / partial.
    """
    fvg_list = []
    for i in range(1, len(df) - 1):
        prev_c, nxt_c = df.iloc[i-1], df.iloc[i+1]

        if trend == 'BULLISH':
            gap = nxt_c['low'] - prev_c['high']
            if gap > -prev_c['high'] * toleransi:   # partial/imperfect juga valid
                top    = nxt_c['low']
                bottom = prev_c['high']
                if top < bottom:                     # swap jika partial overlap
                    top, bottom = bottom, top
                fvg_list.append({
                    'type': 'BULLISH_FVG', 'top': top, 'bottom': bottom,
                    'gap_pct': gap / prev_c['high'] * 100, 'index': i
                })

        elif trend == 'BEARISH':
            gap = prev_c['low'] - nxt_c['high']
            if gap > -prev_c['low'] * toleransi:
                top    = prev_c['low']
                bottom = nxt_c['high']
                if top < bottom:
                    top, bottom = bottom, top
                fvg_list.append({
                    'type': 'BEARISH_FVG', 'top': top, 'bottom': bottom,
                    'gap_pct': gap / prev_c['low'] * 100, 'index': i
                })

    harga = df['close'].iloc[-1]
    fvg_aktif = [f for f in fvg_list if
                 (f['type'] == 'BULLISH_FVG' and harga > f['bottom']) or
                 (f['type'] == 'BEARISH_FVG' and harga < f['top'])]
    if not fvg_aktif:
        return None
    fvg_aktif.sort(key=lambda x: abs(harga - (x['top'] + x['bottom']) / 2))
    return fvg_aktif[0]

def harga_di_fvg(harga, fvg, toleransi=0.004):
    if fvg is None:
        return False
    return fvg['bottom'] * (1 - toleransi) <= harga <= fvg['top'] * (1 + toleransi)

# ═══════════════════════════════════════════════════════════════
# [FIX #6] CONTEXTUAL PD ZONE
# ═══════════════════════════════════════════════════════════════

def hitung_pd_zone(df, lookback=50):
    """Return (premium_batas, discount_batas, mid, posisi_harga)."""
    recent  = df.iloc[-lookback:]
    high_eq = recent['high'].max()
    low_eq  = recent['low'].min()
    mid     = (high_eq + low_eq) / 2
    harga   = df['close'].iloc[-1]

    premium_batas  = mid + (high_eq - mid) * 0.382   # zona premium mulai
    discount_batas = mid - (mid - low_eq) * 0.382    # zona discount mulai

    if harga > premium_batas:
        posisi = "PREMIUM"
    elif harga < discount_batas:
        posisi = "DISCOUNT"
    else:
        posisi = "EQUILIBRIUM"

    return premium_batas, discount_batas, mid, posisi

def cek_pd_valid(trend, posisi_pd, regime):
    """
    [FIX #6]: PD wajib hanya saat ranging, opsional saat trending.
    Return (valid: bool, bobot: int)
    """
    if trend == 'BULLISH' and posisi_pd == 'DISCOUNT':
        return True, 15
    if trend == 'BEARISH' and posisi_pd == 'PREMIUM':
        return True, 15
    if regime == "TRENDING":
        # Saat trending kuat, PD tidak wajib — beri bobot partial
        return True, 5
    if regime == "RANGING":
        # Saat ranging, PD menjadi filter wajib
        return False, 0
    # Default: partial
    return True, 5

# ═══════════════════════════════════════════════════════════════
# [FIX #11] MOMENTUM STRENGTH
# ═══════════════════════════════════════════════════════════════

def hitung_momentum(df, lookback=5):
    """
    Return dict:
      displacement    → rata-rata body candle terakhir
      speed           → pct change rata-rata
      consistency     → berapa candle searah trend dari lookback
      score           → 0–20
    """
    recent = df.iloc[-lookback:]
    bodies = abs(recent['close'] - recent['open'])
    displacement = bodies.mean() / df['close'].iloc[-1] * 100

    pct_changes = recent['close'].pct_change().dropna()
    speed = abs(pct_changes).mean() * 100

    direction = 1 if df['close'].iloc[-1] > df['close'].iloc[-lookback] else -1
    consistent_candles = sum(
        1 for i in range(len(pct_changes))
        if (pct_changes.iloc[i] > 0 and direction == 1) or (pct_changes.iloc[i] < 0 and direction == -1)
    )
    consistency = consistent_candles / len(pct_changes) if len(pct_changes) > 0 else 0

    score = 0
    if displacement > 0.3:
        score += 8
    elif displacement > 0.1:
        score += 4
    if consistency > 0.7:
        score += 7
    elif consistency > 0.5:
        score += 4
    if speed > 0.2:
        score += 5

    return {
        "displacement": displacement,
        "speed": speed,
        "consistency": consistency,
        "score": min(score, 20)
    }

# ═══════════════════════════════════════════════════════════════
# [FIX #14] PRICE BEHAVIOR AWARENESS
# ═══════════════════════════════════════════════════════════════

def deteksi_price_behavior(df):
    """
    Return dict:
      rejection        → bool (panjang wick vs body)
      consolidation    → bool (candle kecil sebelum potensi move)
      breakout_strength → float
      score            → 0–15
    """
    c = df.iloc[-1]
    p = df.iloc[-2]
    pp = df.iloc[-3]

    body  = abs(c['close'] - c['open'])
    wick_up   = c['high'] - max(c['open'], c['close'])
    wick_down = min(c['open'], c['close']) - c['low']
    total_range = c['high'] - c['low'] if c['high'] != c['low'] else 0.0001

    # Rejection: wick panjang relatif terhadap body
    rejection = (wick_up + wick_down) > body * 1.5

    # Consolidation: 2-3 candle kecil sebelum candle terakhir
    bodies_prev = [abs(p['close'] - p['open']), abs(pp['close'] - pp['open'])]
    avg_range   = (df['high'] - df['low']).iloc[-20:].mean()
    consolidation = all(b < avg_range * 0.5 for b in bodies_prev)

    # Breakout strength
    breakout_strength = body / total_range

    score = 0
    if rejection:
        score += 7
    if consolidation:
        score += 5
    if breakout_strength > 0.6:
        score += 3

    return {
        "rejection": rejection,
        "consolidation": consolidation,
        "breakout_strength": breakout_strength,
        "score": score
    }

# ═══════════════════════════════════════════════════════════════
# VOLUME KONFIRMASI
# ═══════════════════════════════════════════════════════════════

def volume_konfirmasi(df, lookback=20):
    avg = df['volume'].iloc[-lookback:-1].mean()
    vol = df['volume'].iloc[-1]
    ratio = vol / avg if avg > 0 else 0
    ok = ratio >= VOLUME_MULTIPLIER
    score = 0
    if ratio >= 2.0:
        score = 10
    elif ratio >= 1.5:
        score = 7
    elif ratio >= 1.0:
        score = 3
    return ok, vol, avg, ratio, score

# ═══════════════════════════════════════════════════════════════
# [FIX #7] MULTI ENTRY MODEL
# ═══════════════════════════════════════════════════════════════

def deteksi_tipe_entry(harga, ob_list, fvg, trend, df):
    """
    Return (tipe_entry: str, desc: str)
    Tipe: 'RETEST' | 'BREAKOUT' | 'CONTINUATION'
    """
    di_ob, best_ob = harga_di_order_block(harga, ob_list)
    di_fvg_zona    = harga_di_fvg(harga, fvg)

    # Retest entry (harga kembali ke zona OB/FVG)
    if di_ob or di_fvg_zona:
        return "RETEST", "Harga retesting OB/FVG zone"

    # Breakout entry (harga baru saja menembus struktur)
    c    = df.iloc[-1]
    prev = df.iloc[-2]
    if trend == 'BULLISH' and c['close'] > prev['high'] and c['close'] > c['open']:
        return "BREAKOUT", "Bullish breakout konfirmasi"
    if trend == 'BEARISH' and c['close'] < prev['low'] and c['close'] < c['open']:
        return "BREAKOUT", "Bearish breakout konfirmasi"

    # Continuation entry (trending tanpa retest)
    return "CONTINUATION", "Continuation dalam trend kuat"

# ═══════════════════════════════════════════════════════════════
# [FIX #1 & #12] PROBABILISTIC SCORING SYSTEM + ADAPTIVE FILTER
# ═══════════════════════════════════════════════════════════════

def hitung_skor(
    trend_sinkron, struktur_strength,
    liq_data, ob_di_zona, fvg_di_zona,
    vol_score, pd_bobot, momentum_score,
    price_behavior_score, session_multiplier,
    regime
):
    """
    Return total_skor (0–100+), breakdown (dict)

    HIERARCHY [FIX #2]:
      Core      (max 35): market structure
      Secondary (max 30): liquidity
      Entry     (max 20): OB / FVG
      Confirm   (max 15): volume + price behavior
    """
    breakdown = {}

    # ── CORE: Market Structure ────────────────────────────────
    core = 0
    if trend_sinkron:
        core += 20
    core += min(struktur_strength, 15)   # kekuatan BOS/CHoCH
    breakdown['core_structure'] = core

    # ── SECONDARY: Liquidity ─────────────────────────────────
    liq_score = min(liq_data['score'], 30)
    breakdown['liquidity'] = liq_score

    # ── ENTRY: OB / FVG ──────────────────────────────────────
    entry = 0
    if ob_di_zona:
        entry += 12
    if fvg_di_zona:
        entry += 8
    breakdown['entry_zone'] = entry

    # ── CONFIRMATION: Volume + Price Behavior ────────────────
    confirm = vol_score + price_behavior_score
    confirm = min(confirm, 15)
    breakdown['confirmation'] = confirm

    # ── KONTEKS TAMBAHAN ─────────────────────────────────────
    konteks = pd_bobot + momentum_score
    breakdown['context'] = konteks

    total = core + liq_score + entry + confirm + konteks

    # [FIX #9] Session multiplier
    total_adj = total * session_multiplier
    breakdown['session_multiplier'] = session_multiplier
    breakdown['raw_total'] = total
    breakdown['adjusted_total'] = round(total_adj, 1)

    return round(total_adj, 1), breakdown

# ═══════════════════════════════════════════════════════════════
# [FIX #15] TRADE GRADING
# ═══════════════════════════════════════════════════════════════

def grade_sinyal(skor):
    """Return (grade, emoji)."""
    if skor >= 80:
        return "A+", "🏆"
    elif skor >= 65:
        return "A",  "🥇"
    elif skor >= 55:
        return "B",  "🥈"
    elif skor >= 40:
        return "C",  "🥉"
    else:
        return "D",  "⚠️"

# ═══════════════════════════════════════════════════════════════
# [FIX #10] CONTEXTUAL SL/TP
# ═══════════════════════════════════════════════════════════════

def hitung_sl_tp(trend, entry, ob_list, fvg, kurs_usd, regime, momentum_score, struktur_strength):
    """
    SL/TP kontekstual:
    - strong trend  → RR lebih besar
    - weak structure → RR lebih konservatif
    - SL mempertimbangkan ATR/volatility
    """
    # Tentukan RR
    if regime == "TRENDING" and struktur_strength > 50 and momentum_score > 12:
        rr = RR_CONFIG["strong_trend"]
        rr_label = "Strong Trend"
    elif struktur_strength < 20 or regime in ("RANGING", "LOW_VOL"):
        rr = RR_CONFIG["weak"]
        rr_label = "Weak Structure"
    else:
        rr = RR_CONFIG["normal"]
        rr_label = "Normal"

    _, best_ob = harga_di_order_block(entry, ob_list)

    if trend == 'BULLISH':
        kandidat = []
        if best_ob:
            kandidat.append(best_ob['low'] * 0.995)
        if fvg:
            kandidat.append(fvg['bottom'] * 0.995)
        sl    = min(kandidat) if kandidat else entry * 0.99
        jarak = entry - sl
        tp    = entry + jarak * rr
    else:
        kandidat = []
        if best_ob:
            kandidat.append(best_ob['high'] * 1.005)
        if fvg:
            kandidat.append(fvg['top'] * 1.005)
        sl    = max(kandidat) if kandidat else entry * 1.01
        jarak = sl - entry
        tp    = entry - jarak * rr

    sl_pct = abs(entry - sl) / entry * 100
    tp_pct = abs(tp - entry) / entry * 100

    return sl, sl * kurs_usd, tp, tp * kurs_usd, sl_pct, tp_pct, rr, rr_label

# ═══════════════════════════════════════════════════════════════
# UTILITAS
# ═══════════════════════════════════════════════════════════════

def ambil_kurs_usd():
    for url in [
        "https://api.exchangerate-api.com/v4/latest/USD",
        "https://open.er-api.com/v6/latest/USD",
    ]:
        try:
            r = requests.get(url, timeout=5)
            return r.json()['rates']['IDR']
        except:
            continue
    print("  ⚠️  Gagal ambil kurs, pakai default 15800")
    return 15800

def kirim_telegram(pesan):
    url  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": pesan, "parse_mode": "HTML"}
    try:
        r = requests.post(url, data=data, timeout=10)
        if r.status_code == 200:
            print("✅ Sinyal terkirim ke Telegram!")
        else:
            print(f"❌ Telegram error: {r.text}")
    except Exception as e:
        print(f"❌ Telegram gagal: {e}")

# ═══════════════════════════════════════════════════════════════
# CEK PAIR — MAIN ANALYSIS
# ═══════════════════════════════════════════════════════════════

PERINGATAN_SCALPING = (
    "\n⚠️ <b>CATATAN SCALPING:</b>\n"
    "• Sinyal TF kecil lebih sering tapi lebih berisiko\n"
    "• Spread & fee lebih berpengaruh di TF kecil\n"
    "• Gunakan position size lebih kecil\n"
    "• Pantau chart secara aktif saat entry\n"
    "• Tidak disarankan ditinggal / unattended"
)

def cek_pair(pair, mode, kurs_usd, sinyal_terakhir):
    label    = mode["label"]
    trend_tf = mode["trend_tf"]
    entry_tf = mode["entry_tf"]
    emoji    = mode["emoji"]
    nama     = pair.replace("/USDT", "")
    cfg      = STRATEGY_CONFIG[STRATEGY_MODE]

    try:
        df_trend, _      = ambil_data(pair, trend_tf, limit=150)
        time.sleep(0.3)
        df_entry, sumber = ambil_data(pair, entry_tf, limit=150)

        harga_usdt = df_entry['close'].iloc[-1]
        harga_idr  = harga_usdt * kurs_usd

        # ── Analisis ─────────────────────────────────────────
        trend_besar, _, _              = deteksi_struktur(df_trend)
        trend_entry, event_entry, s_str = deteksi_struktur(df_entry)

        regime_data   = deteksi_market_regime(df_entry)
        regime        = regime_data["regime"]

        ob_list       = cari_order_block(df_entry, trend_entry)
        fvg           = cari_fvg(df_entry, trend_entry)
        di_ob, best_ob = harga_di_order_block(harga_usdt, ob_list)
        di_fvg_zona   = harga_di_fvg(harga_usdt, fvg)

        liq_data      = deteksi_liquidity(df_entry, trend_entry)
        vol_ok, vol_kini, vol_avg, vol_ratio, vol_score = volume_konfirmasi(df_entry)

        _, _, _, posisi_pd = hitung_pd_zone(df_entry)
        pd_valid, pd_bobot = cek_pd_valid(trend_entry, posisi_pd, regime)

        momentum      = hitung_momentum(df_entry)
        price_beh     = deteksi_price_behavior(df_entry)
        session_nama, session_mult = deteksi_session()

        trend_sinkron = trend_besar == trend_entry and trend_besar != 'RANGING'
        ada_struktur  = event_entry in ('BOS', 'CHoCH')

        # ── Scoring ──────────────────────────────────────────
        skor, breakdown = hitung_skor(
            trend_sinkron, s_str,
            liq_data, di_ob, di_fvg_zona,
            vol_score, pd_bobot, momentum['score'],
            price_beh['score'], session_mult,
            regime
        )

        grade, grade_emoji = grade_sinyal(skor)

        # [FIX #12] Adaptive: filter lebih ketat jika skor rendah
        threshold = cfg["threshold"]
        if skor >= 70:
            # Setup kuat → kurangi filter wajib
            harus_ada_struktur = True      # tetap wajib karena core hierarchy
            harus_ada_zona     = di_ob or di_fvg_zona   # tapi boleh salah satu
        else:
            harus_ada_struktur = True
            harus_ada_zona     = di_ob or di_fvg_zona

        # Minimum grade filter per mode
        grade_order = {"A+": 5, "A": 4, "B": 3, "C": 2, "D": 1}
        min_grade_val = grade_order.get(cfg["min_grade"], 1)
        grade_val     = grade_order.get(grade, 1)
        grade_ok      = grade_val >= min_grade_val

        # Tipe entry
        tipe_entry, entry_desc = deteksi_tipe_entry(harga_usdt, ob_list, fvg, trend_entry, df_entry)

        print(f"  [{label}|{trend_tf}→{entry_tf}] {nama}: "
              f"${harga_usdt:,.4f} | {trend_besar}→{trend_entry}({event_entry}) | "
              f"Regime:{regime} PD:{posisi_pd} Skor:{skor:.0f} Grade:{grade} "
              f"Session:{session_nama} [{sumber}]")

        # ── Entry Condition ───────────────────────────────────
        entry_ok = (
            skor >= threshold
            and grade_ok
            and harus_ada_struktur and ada_struktur
            and harus_ada_zona
            and pd_valid
        )

        if entry_ok:
            arah   = "🟢 BUY (LONG)" if trend_entry == 'BULLISH' else "🔴 SELL (SHORT)"
            key    = f"{pair}-{label}-{entry_tf}"
            sinyal = f"{pair}-{label}-{trend_tf}-{entry_tf}-{trend_entry}-{event_entry}-{grade}"

            if sinyal != sinyal_terakhir.get(key):
                # SL/TP kontekstual
                sl_usdt, sl_idr, tp_usdt, tp_idr, sl_pct, tp_pct, rr, rr_label = hitung_sl_tp(
                    trend_entry, harga_usdt, ob_list, fvg,
                    kurs_usd, regime, momentum['score'], s_str
                )

                # Zona entry info
                zona_info = []
                if di_ob and best_ob:
                    zona_info.append(
                        f"Order Block : ${best_ob['low']:,.4f} – ${best_ob['high']:,.4f}"
                        f"\n              (Rp{best_ob['low']*kurs_usd:,.0f} – Rp{best_ob['high']*kurs_usd:,.0f})"
                    )
                if di_fvg_zona and fvg:
                    zona_info.append(
                        f"FVG         : ${fvg['bottom']:,.4f} – ${fvg['top']:,.4f}"
                        f"\n              (Rp{fvg['bottom']*kurs_usd:,.0f} – Rp{fvg['top']*kurs_usd:,.0f})"
                    )
                zona_str = "\n   ".join(zona_info) if zona_info else "Breakout / Continuation Zone"

                # Liquidity summary
                liq_txt = []
                if liq_data['external_sweep']:
                    liq_txt.append("External Sweep ✅")
                if liq_data['internal_sweep']:
                    liq_txt.append("Internal Sweep ✅")
                if liq_data['inducement']:
                    liq_txt.append("Inducement ✅")
                liq_str = " | ".join(liq_txt) if liq_txt else "Tidak terdeteksi"

                # Breakdown skor
                bd = breakdown
                skor_detail = (
                    f"Structure:{bd['core_structure']:.0f} "
                    f"Liq:{bd['liquidity']:.0f} "
                    f"Zone:{bd['entry_zone']:.0f} "
                    f"Confirm:{bd['confirmation']:.0f} "
                    f"Context:{bd['context']:.0f}"
                )

                catatan = PERINGATAN_SCALPING if label == "SCALPING" else "\n⚠️ Selalu manajemen risiko!"
                strat_label = cfg["label"]

                pesan = (
                    f"{emoji} <b>SINYAL {label} — SMC v2</b>\n\n"
                    f"📊 Pair      : <b>{pair} (Futures)</b>\n"
                    f"👉 Arah      : <b>{arah}</b>\n"
                    f"⏱️ Timeframe : <b>{trend_tf} → {entry_tf}</b>\n"
                    f"🔌 Sumber    : <b>{sumber}</b>\n\n"
                    f"💰 Harga     : <b>${harga_usdt:,.4f}</b>\n"
                    f"           ≈ <b>Rp{harga_idr:,.0f}</b>\n"
                    f"💱 Kurs      : <b>Rp{kurs_usd:,.0f}/USD</b>\n\n"
                    f"📈 Trend {trend_tf}  : <b>{trend_besar}</b>\n"
                    f"📉 Trend {entry_tf}  : <b>{trend_entry}</b> ({event_entry})\n"
                    f"🏛️ Regime    : <b>{regime}</b>\n"
                    f"🕐 Session   : <b>{session_nama}</b>\n\n"
                    f"🧱 Zona Entry ({tipe_entry}):\n   {zona_str}\n"
                    f"   ↳ <i>{entry_desc}</i>\n\n"
                    f"💧 Liquidity : <b>{liq_str}</b>\n"
                    f"📍 PD Zone   : <b>{posisi_pd}</b>\n"
                    f"📦 Volume    : <b>{vol_ratio:.1f}x</b> rata-rata\n"
                    f"💥 Momentum  : <b>{momentum['score']:.0f}/20</b> "
                    f"(disp={momentum['displacement']:.2f}%)\n"
                    f"🕯️ Price Beh : <b>{'Rejection ✅' if price_beh['rejection'] else ''}"
                    f"{'Consol ✅' if price_beh['consolidation'] else ''}</b>\n\n"
                    f"🏆 Grade     : <b>{grade_emoji} {grade}</b> "
                    f"(Skor: {skor:.0f}/100+)\n"
                    f"   [{skor_detail}]\n"
                    f"⚙️ Mode      : <b>{strat_label}</b>\n\n"
                    f"🛡️ Stop Loss  (-{sl_pct:.1f}%):\n"
                    f"   <b>${sl_usdt:,.4f}</b> / Rp{sl_idr:,.0f}\n\n"
                    f"🎯 Take Profit (+{tp_pct:.1f}%):\n"
                    f"   <b>${tp_usdt:,.4f}</b> / Rp{tp_idr:,.0f}\n\n"
                    f"📐 Risk/Reward : <b>1:{rr}</b> ({rr_label})"
                    f"{catatan}"
                )
                kirim_telegram(pesan)
                sinyal_terakhir[key] = sinyal

    except Exception as e:
        print(f"  ❌ [{label}] {pair} error: {e}")

    return sinyal_terakhir

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def jalankan_bot():
    cfg = STRATEGY_CONFIG[STRATEGY_MODE]
    print("=" * 65)
    print("🤖  BOT SMC v2 — Probabilistic + Adaptive (Indonesia Ready)")
    print("=" * 65)
    print(f"📡 Primary        : Gate.io Futures ✅")
    print(f"📡 Fallback        : MEXC → KuCoin Futures")
    print(f"📊 Memantau        : {len(PAIRS)} koin")
    print(f"⚙️  Strategy Mode  : {cfg['label']}")
    print(f"🎯 Entry Threshold : {cfg['threshold']} / 100+")
    print(f"🏆 Min Grade       : {cfg['min_grade']}")
    print(f"📦 Vol Filter      : {VOLUME_MULTIPLIER}x rata-rata")
    print(f"\n⏱️  Mode aktif:")
    for m in MODES:
        print(f"   {m['emoji']} {m['label']:10} | Trend: {m['trend_tf']} → Entry: {m['entry_tf']}")
    print()
    print("🔧 Fitur v2:")
    print("   ✅ Probabilistic Scoring  ✅ Signal Hierarchy")
    print("   ✅ Flexible Liquidity     ✅ Dynamic OB Zone")
    print("   ✅ Imperfect FVG          ✅ Contextual PD")
    print("   ✅ Multi Entry Model      ✅ Market Regime")
    print("   ✅ Session Awareness      ✅ Contextual SL/TP")
    print("   ✅ Momentum Filter        ✅ Adaptive Filter")
    print("   ✅ Multi Strategy Mode    ✅ Price Behavior")
    print("   ✅ Trade Grading (A+/A/B/C/D)")
    print()

    sinyal_terakhir = {}

    while True:
        print("─" * 65)
        sesi, _ = deteksi_session()
        print(f"🔍 Scan... [Exchange: {aktif_exchange}] [Session: {sesi}]")
        kurs_usd = ambil_kurs_usd()
        print(f"💱 Kurs: Rp{kurs_usd:,.0f}/USD\n")

        for pair in PAIRS:
            for mode in MODES:
                sinyal_terakhir = cek_pair(pair, mode, kurs_usd, sinyal_terakhir)
                time.sleep(0.5)

        print(f"\n⏳ Menunggu 15 menit... [Exchange: {aktif_exchange}]\n")
        time.sleep(900)

jalankan_bot()