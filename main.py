"""
╔══════════════════════════════════════════════════════════════════════════╗
║         Yudhystirady SMC CRYPTO SIGNAL BOT — Clean Modular Edition       ║
║                                                                          ║
║  OBJECTIVE: High-frequency signals without over-filtering                ║
║                                                                          ║
║  CORE RULES:                                                             ║
║  ✅ HTF (H1/H4) Market Structure — BOS/CHoCH — REQUIRED                 ║
║  ✅ Liquidity Sweep (EQH/EQL + wick rejection) — REQUIRED               ║
║  ✅ Order Block OR Fair Value Gap — REQUIRED                            ║
║  ✅ Scoring System (max 100 pts) — fire at ≥ 60                         ║
║  ✅ RSI: scoring factor ONLY, never blocks trades                       ║
║  ✅ Macro (BTC + BTC.D): scoring factor ONLY, never blocks              ║
║  ✅ Session bonus: London / New York                                    ║
║  ✅ RR ≥ 1.5 required | Grade A ≥ 2.0 | Grade B ≥ 1.5                   ║
║  ✅ Per-pair cooldown: 30 minutes                                       ║
║  ✅ JSON output + Telegram alerts                                       ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import ccxt
import time
import hashlib
from datetime import datetime, timezone

import pandas as pd
import requests
import threading


# ═══════════════════════════════════════════════════════════════════════════
# ██  SECTION 1 — CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

TELEGRAM_TOKEN   = "8660926908:AAFA7fVSIgZpk2m1QllOgUnEnfpC9iPGIWM"

# ── Target Channel / Grup ────────────────────────────────────────────────────
# Ganti dengan ID channel/grup kamu (format: -100xxxxxxxxxx untuk channel publik)
# Cara cari ID channel: tambah @userinfobot ke grup, atau forward pesan ke @userinfobot
# PENTING: Bot harus dijadikan ADMIN di channel dengan izin "Post Messages"
TELEGRAM_CHAT_ID = "-1003790730025"   # <- ganti ke ID channel, contoh: "-1001234567890"

# ── Welcome Message ──────────────────────────────────────────────────────────
WELCOME_ENABLED  = True   # True = kirim welcome saat member baru join
WELCOME_MESSAGE  = (
    "👋 <b>Selamat datang, {name}!</b>\n"
    "────────────────────────────────────\n"
    "🤖 Bot ini mengirim sinyal trading crypto berbasis SMC (Smart Money Concepts).\n\n"
    "📋 <b>Yang akan kamu dapatkan:</b>\n"
    "  ✅ Sinyal LONG / SHORT otomatis\n"
    "  ✅ Entry, Stop Loss, TP1 dan TP2\n"
    "  ✅ Risk-Reward Ratio dan Score\n"
    "  ✅ Analisis HTF, OB, FVG, Liquidity\n\n"
    "⚠️ <i>Disclaimer: Sinyal bersifat edukatif. Selalu manage risk sendiri.</i>\n"
    "────────────────────────────────────\n"
    "🔔 Aktifkan notifikasi channel agar tidak ketinggalan sinyal!"
)

# ── Polling offset (welcome listener) ────────────────────────────────────────
_tg_offset: int = 0

PAIRS = [
    "BTC/USDT",  "ETH/USDT",   "XRP/USDT",  "SOL/USDT",
    "BNB/USDT",  "DOGE/USDT",  "ADA/USDT",  "POL/USDT",
    "TRX/USDT",  "AVAX/USDT",  "LINK/USDT", "SHIB/USDT",
    "TON/USDT",  "SUI/USDT",   "DOT/USDT",  "LTC/USDT",
    "BCH/USDT",  "NEAR/USDT",  "APT/USDT",  "UNI/USDT",
    "ICP/USDT",  "PEPE/USDT",  "ETC/USDT",  "STX/USDT",
    "FIL/USDT",  "OP/USDT",    "INJ/USDT",  "IMX/USDT",
    "ARB/USDT",  "ATOM/USDT",  "VET/USDT",  "RENDER/USDT",
    "GRT/USDT",  "SAND/USDT",  "MANA/USDT", "AAVE/USDT",
    "THETA/USDT","XLM/USDT",   "ALGO/USDT", "AXS/USDT",
    "EGLD/USDT", "HBAR/USDT",  "QNT/USDT",  "FLOW/USDT",
    "CHZ/USDT",  "GALA/USDT",  "KAVA/USDT", "ZIL/USDT",
    "HYPE/USDT",
]

# Scan modes: HTF bias → entry TF
MODES = [
    {"label": "SCALPING",  "htf_tf": "4h", "entry_tf": "15m"},
    {"label": "SCALPING",  "htf_tf": "4h", "entry_tf": "30m"},
    {"label": "INTRADAY",  "htf_tf": "1d", "entry_tf": "1h"},
]

# ── Detection Parameters ────────────────────────────────────────────────────
SWING_WINDOW         = 5       # Pivot lookback window
SWEEP_LOOKBACK       = 30      # Candles back for sweep detection
OB_LOOKBACK          = 40      # Candles back for OB search
FVG_LOOKBACK         = 40      # Candles back for FVG search
EQH_EQL_TOLERANCE    = 0.0015  # Equal highs/lows tolerance (0.15%)
WICK_BODY_RATIO_MIN  = 1.5     # Min wick-to-body for valid sweep rejection
REJECTION_TOLERANCE  = 0.003   # 0.3% close tolerance after sweep
OB_MITIGATION_LIMIT  = 2       # Max taps before OB is mitigated
MIN_DISPLACEMENT_PCT = 0.25    # Min body % for valid OB impulse
MIN_FVG_PCT          = 0.08    # Min gap size % for valid FVG
ATR_PERIOD           = 14

# ── Scoring Weights (total max = 100 pts) ───────────────────────────────────
# +20 HTF trend aligned
# +20 Liquidity sweep
# +15 Valid OB or FVG
# +10 Strong displacement
# +5  Volume spike
# +5  Session (London/NY)
# +5  RSI 50–65 (scoring only)
# +10 Macro aligned (BTC + BTC.D, scoring only)
# −5  RSI extreme (>75 or <25)
# −5  Macro conflict
SCORE_HTF_ALIGNED    = 20
SCORE_LIQUIDITY      = 20
SCORE_OB_FVG         = 15
SCORE_DISPLACEMENT   = 10
SCORE_VOLUME         = 5
SCORE_SESSION        = 5
SCORE_RSI_IDEAL      = 5
SCORE_MACRO_ALIGNED  = 10
SCORE_RSI_PENALTY    = -5      # RSI > 75 or < 25
SCORE_MACRO_CONFLICT = -5

MIN_SCORE            = 60      # Minimum score to fire signal
COOLDOWN_MINUTES     = 120      # Per-pair cooldown in minutes
SCAN_INTERVAL        = 120     # Seconds between full scans (15 min)

# RR thresholds
RR_GRADE_A   = 2.0
RR_GRADE_B   = 1.5             # Minimum to take trade

# Macro config
ALTCOIN_EXEMPTIONS   = {"BTC/USDT", "ETH/USDT"}
BTC_BIAS_TF          = "1d"
BTCD_SMA_PERIOD      = 20
RSI_PERIOD           = 14


# ═══════════════════════════════════════════════════════════════════════════
# ██  SECTION 2 — EXCHANGE LAYER
# ═══════════════════════════════════════════════════════════════════════════

KUCOIN_MAP = {
    "BTC/USDT":"XBTUSDTM","ETH/USDT":"ETHUSDTM","XRP/USDT":"XRPUSDTM",
    "SOL/USDT":"SOLUSDTM","BNB/USDT":"BNBUSDTM","DOGE/USDT":"DOGEUSDTM",
    "ADA/USDT":"ADAUSDTM","POL/USDT":"POLUSDTM","TRX/USDT":"TRXUSDTM",
    "AVAX/USDT":"AVAXUSDTM","LINK/USDT":"LINKUSDTM","SHIB/USDT":"SHIBUSDTM",
    "TON/USDT":"TONUSDTM","SUI/USDT":"SUIUSDTM","DOT/USDT":"DOTUSDTM",
    "LTC/USDT":"LTCUSDTM","BCH/USDT":"BCHUSDTM","NEAR/USDT":"NEARUSDTM",
    "APT/USDT":"APTUSDTM","UNI/USDT":"UNIUSDTM","ICP/USDT":"ICPUSDTM",
    "PEPE/USDT":"PEPEUSDTM","ETC/USDT":"ETCUSDTM","STX/USDT":"STXUSDTM",
    "FIL/USDT":"FILUSDTM","OP/USDT":"OPUSDTM","INJ/USDT":"INJUSDTM",
    "IMX/USDT":"IMXUSDTM","ARB/USDT":"ARBUSDTM","ATOM/USDT":"ATOMUSDTM",
    "VET/USDT":"VETUSDTM","RENDER/USDT":"RENDERUSDTM","GRT/USDT":"GRTUSDTM",
    "SAND/USDT":"SANDUSDTM","MANA/USDT":"MANAUSDTM","AAVE/USDT":"AAVEUSDTM",
    "THETA/USDT":"THETAUSDTM","XLM/USDT":"XLMUSDTM","ALGO/USDT":"ALGOUSDTM",
    "AXS/USDT":"AXSUSDTM","EGLD/USDT":"EGLDUSDTM","HBAR/USDT":"HBARUSDTM",
    "QNT/USDT":"QNTUSDTM","FLOW/USDT":"FLOWUSDTM","CHZ/USDT":"CHZUSDTM",
    "GALA/USDT":"GALAUSDTM","KAVA/USDT":"KAVAUSDTM","ZIL/USDT":"ZILUSDTM",
    "HYPE/USDT":"HYPEUSDTM",
}

EXCHANGES = {
    "Gate.io": ccxt.gateio({
        "enableRateLimit": True, "timeout": 15000,
        "options": {"defaultType": "future"},
    }),
    "MEXC": ccxt.mexc({
        "enableRateLimit": True, "timeout": 15000,
        "options": {"defaultType": "swap"},
    }),
    "KuCoin Futures": ccxt.kucoinfutures({
        "enableRateLimit": True, "timeout": 15000,
    }),
}

EXCHANGE_ORDER  = ["Gate.io", "MEXC", "KuCoin Futures"]
_aktif_exchange = "Gate.io"


def _convert_symbol(exchange_name: str, pair: str) -> str:
    if exchange_name == "Gate.io":
        return pair.replace("/", "_")
    if exchange_name == "KuCoin Futures":
        return KUCOIN_MAP.get(pair, pair.replace("/USDT", "USDTM"))
    return pair


def fetch_ohlcv(pair: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
    """Fetch OHLCV with automatic exchange fallback. Returns DataFrame."""
    global _aktif_exchange
    order = [_aktif_exchange] + [e for e in EXCHANGE_ORDER if e != _aktif_exchange]

    for name in order:
        try:
            symbol  = _convert_symbol(name, pair)
            candles = EXCHANGES[name].fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            if not candles or len(candles) < 50:
                raise ValueError(f"Only {len(candles) if candles else 0} candles")
            df = pd.DataFrame(candles, columns=["time","open","high","low","close","volume"])
            df["time"] = pd.to_datetime(df["time"], unit="ms")
            if _aktif_exchange != name:
                print(f"  🔄 Switched → {name}")
                _aktif_exchange = name
            return df
        except ccxt.NetworkError:
            print(f"  ⚠️  {name} network error")
        except ccxt.ExchangeError as e:
            print(f"  ⚠️  {name} exchange error: {e}")
        except Exception as e:
            print(f"  ⚠️  {name} failed: {e}")

    raise RuntimeError(f"All exchanges failed for {pair} @ {timeframe}")


# ═══════════════════════════════════════════════════════════════════════════
# ██  SECTION 3 — MARKET STRUCTURE (BOS / CHoCH)
# ═══════════════════════════════════════════════════════════════════════════

def find_swings(df: pd.DataFrame, window: int = SWING_WINDOW) -> tuple:
    """Return (highs, lows) as lists of (index, price)."""
    highs, lows = [], []
    for i in range(window, len(df) - window):
        hi_window = df["high"].iloc[i - window: i + window + 1]
        lo_window = df["low"].iloc[i - window: i + window + 1]
        if df["high"].iloc[i] == hi_window.max():
            highs.append((i, float(df["high"].iloc[i])))
        if df["low"].iloc[i] == lo_window.min():
            lows.append((i, float(df["low"].iloc[i])))
    return highs, lows


def detect_structure(df: pd.DataFrame) -> tuple:
    """
    Detect trend + structural event using swing highs/lows.
    Returns: (trend, event, last_swing_high, last_swing_low)
      trend: 'BULLISH' | 'BEARISH' | 'RANGING'
      event: 'BOS' | 'CHoCH' | None
    """
    highs, lows = find_swings(df)
    if len(highs) < 2 or len(lows) < 2:
        return "RANGING", None, None, None

    last_sh, prev_sh = highs[-1][1], highs[-2][1]
    last_sl, prev_sl = lows[-1][1],  lows[-2][1]

    hh = last_sh > prev_sh
    hl = last_sl > prev_sl
    lh = last_sh < prev_sh
    ll = last_sl < prev_sl

    if hh and hl:
        trend = "BULLISH"
        event = "BOS" if hh else "CHoCH"
    elif lh and ll:
        trend = "BEARISH"
        event = "BOS" if ll else "CHoCH"
    elif (hh and ll) or (lh and hl):
        trend  = "RANGING"
        # Detect CHoCH: bullish structure broken to downside or vice versa
        event  = "CHoCH" if (hh and ll) or (lh and hl) else None
    else:
        trend = "RANGING"
        event = None

    return trend, event, last_sh, last_sl


def get_htf_bias(df_htf: pd.DataFrame) -> tuple:
    """
    HTF mandatory gate.
    Returns: (bias, event, sh, sl)
    """
    return detect_structure(df_htf)


# ═══════════════════════════════════════════════════════════════════════════
# ██  SECTION 4 — LIQUIDITY SWEEP
# ═══════════════════════════════════════════════════════════════════════════

def detect_eqh_eql(df: pd.DataFrame) -> dict:
    """Detect Equal Highs / Equal Lows clusters within SWEEP_LOOKBACK candles."""
    recent = df.iloc[-SWEEP_LOOKBACK:]
    h_vals = recent["high"].values
    l_vals = recent["low"].values

    eqh_pool, eql_pool = [], []
    for i in range(len(h_vals)):
        for j in range(i + 1, len(h_vals)):
            if abs(h_vals[i] - h_vals[j]) / (h_vals[i] + 1e-9) <= EQH_EQL_TOLERANCE:
                eqh_pool.append(max(h_vals[i], h_vals[j]))
    for i in range(len(l_vals)):
        for j in range(i + 1, len(l_vals)):
            if abs(l_vals[i] - l_vals[j]) / (l_vals[i] + 1e-9) <= EQH_EQL_TOLERANCE:
                eql_pool.append(min(l_vals[i], l_vals[j]))

    return {
        "eqh": float(max(eqh_pool)) if eqh_pool else None,
        "eql": float(min(eql_pool)) if eql_pool else None,
    }


def detect_liquidity_sweep(df: pd.DataFrame, trend: str) -> tuple:
    """
    Detect liquidity sweep: price sweeps swing H/L or EQH/EQL and rejects.
    Rejection valid when wick > body (wick-body ratio ≥ WICK_BODY_RATIO_MIN).

    Returns: (swept: bool, sweep_type: str, level: float)
    """
    recent     = df.iloc[-SWEEP_LOOKBACK:]
    c          = df.iloc[-1]
    c_prev     = df.iloc[-2]
    eq         = detect_eqh_eql(df)
    swing_high = float(recent["high"].max())
    swing_low  = float(recent["low"].min())

    def wick_body_ok(candle, direction: str) -> bool:
        """Check wick-to-body ratio for rejection confirmation."""
        o, h, l, cl = (float(candle[x]) for x in ["open","high","low","close"])
        body = abs(cl - o)
        if body < 1e-9:
            return False
        if direction == "BULLISH":
            lower_wick = (min(o, cl) - l)
            return (lower_wick / body) >= WICK_BODY_RATIO_MIN
        else:
            upper_wick = (h - max(o, cl))
            return (upper_wick / body) >= WICK_BODY_RATIO_MIN

    if trend == "BULLISH":
        eql = eq.get("eql")
        # Check swing low sweep with rejection
        for candle in [c_prev, c]:
            swept_level = None
            if float(candle["low"]) < swing_low:
                swept_level = swing_low
            elif eql and float(candle["low"]) < eql:
                swept_level = eql

            if swept_level is not None:
                close_rejected = float(candle["close"]) > swept_level * (1 - REJECTION_TOLERANCE)
                if close_rejected and wick_body_ok(candle, "BULLISH"):
                    return True, "Bullish Sweep + Rejection", swept_level
                elif close_rejected:
                    return True, "Bullish Sweep (weak)", swept_level

    elif trend == "BEARISH":
        eqh = eq.get("eqh")
        for candle in [c_prev, c]:
            swept_level = None
            if float(candle["high"]) > swing_high:
                swept_level = swing_high
            elif eqh and float(candle["high"]) > eqh:
                swept_level = eqh

            if swept_level is not None:
                close_rejected = float(candle["close"]) < swept_level * (1 + REJECTION_TOLERANCE)
                if close_rejected and wick_body_ok(candle, "BEARISH"):
                    return True, "Bearish Sweep + Rejection", swept_level
                elif close_rejected:
                    return True, "Bearish Sweep (weak)", swept_level

    return False, None, None


# ═══════════════════════════════════════════════════════════════════════════
# ██  SECTION 5 — ORDER BLOCK
# ═══════════════════════════════════════════════════════════════════════════

def find_order_blocks(df: pd.DataFrame, trend: str) -> list:
    """
    Detect unmitigated institutional Order Blocks.
    OB = opposing candle immediately before a strong displacement impulse.
    Returns top-3 OBs sorted by strength.
    """
    ob_list = []
    start   = max(1, len(df) - OB_LOOKBACK)
    price   = float(df["close"].iloc[-1])

    for i in range(start, len(df) - 2):
        c   = df.iloc[i]
        nxt = df.iloc[i + 1]
        impulse_pct = abs(float(nxt["close"]) - float(nxt["open"])) / (float(nxt["open"]) + 1e-9) * 100

        if impulse_pct < MIN_DISPLACEMENT_PCT:
            continue

        is_valid = False
        if trend == "BULLISH" and float(c["close"]) < float(c["open"]) and float(nxt["close"]) > float(nxt["open"]):
            is_valid = True
        elif trend == "BEARISH" and float(c["close"]) > float(c["open"]) and float(nxt["close"]) < float(nxt["open"]):
            is_valid = True

        if not is_valid:
            continue

        ob = {
            "low":      float(c["low"]),
            "high":     float(c["high"]),
            "mid":      float((float(c["low"]) + float(c["high"])) / 2),
            "index":    i,
            "impulse":  impulse_pct,
        }

        # Count taps (mitigation check)
        taps = sum(
            1 for j in range(i + 2, len(df))
            if float(df.iloc[j]["low"]) <= ob["high"] and float(df.iloc[j]["high"]) >= ob["low"]
        )
        if taps >= OB_MITIGATION_LIMIT:
            continue

        ob["taps"]     = taps
        dist_pct       = abs(price - ob["mid"]) / (price + 1e-9) * 100
        ob["strength"] = impulse_pct / (1.0 + dist_pct) / (1.0 + taps)
        ob_list.append(ob)

    ob_list.sort(key=lambda x: x["strength"], reverse=True)
    return ob_list[:3]


def price_in_ob(price: float, ob_list: list, tolerance: float = 0.004) -> tuple:
    """Returns (in_ob: bool, best_ob: dict|None)."""
    if not ob_list:
        return False, None
    lo   = price * (1 - tolerance)
    hi   = price * (1 + tolerance)
    hits = [ob for ob in ob_list if ob["low"] <= hi and ob["high"] >= lo]
    return (True, max(hits, key=lambda x: x["strength"])) if hits else (False, None)


# ═══════════════════════════════════════════════════════════════════════════
# ██  SECTION 6 — FAIR VALUE GAP (FVG)
# ═══════════════════════════════════════════════════════════════════════════

def find_fvg(df: pd.DataFrame, trend: str) -> dict | None:
    """
    Find the most recent valid, unfilled (or partially filled) FVG.
    Returns the best FVG dict or None.
    """
    start    = max(1, len(df) - FVG_LOOKBACK)
    price    = float(df["close"].iloc[-1])
    fvg_list = []

    for i in range(start, len(df) - 1):
        p1 = df.iloc[i - 1]
        p3 = df.iloc[i + 1]

        if trend == "BULLISH":
            gap     = float(p3["low"]) - float(p1["high"])
            min_gap = float(p1["high"]) * MIN_FVG_PCT / 100
            if gap < min_gap:
                continue
            fvg_top, fvg_bot = float(p3["low"]), float(p1["high"])

        elif trend == "BEARISH":
            gap     = float(p1["low"]) - float(p3["high"])
            min_gap = float(p3["high"]) * MIN_FVG_PCT / 100
            if gap < min_gap:
                continue
            fvg_top, fvg_bot = float(p1["low"]), float(p3["high"])
        else:
            continue

        # Fill check: how much of the gap has price revisited?
        post     = df.iloc[i + 2:]
        fill_pct = 0.0
        if len(post) > 0:
            gap_size = fvg_top - fvg_bot
            if trend == "BULLISH":
                deepest = float(post["low"].min())
                fill_pct = min(1.0, max(0.0, (fvg_top - deepest) / gap_size)) if gap_size > 0 else 0.0
            else:
                deepest  = float(post["high"].max())
                fill_pct = min(1.0, max(0.0, (deepest - fvg_bot) / gap_size)) if gap_size > 0 else 0.0

        if fill_pct >= 0.85:
            continue  # FVG fully mitigated

        fvg_mid = (fvg_top + fvg_bot) / 2
        # Check if price is near this FVG
        in_fvg = fvg_bot * (1 - 0.005) <= price <= fvg_top * (1 + 0.005)

        fvg_list.append({
            "top":       fvg_top,
            "bottom":    fvg_bot,
            "mid":       fvg_mid,
            "fill_pct":  fill_pct,
            "index":     i,
            "in_zone":   in_fvg,
        })

    if not fvg_list:
        return None

    # Prefer FVGs that price is currently inside; else pick most recent
    in_zone = [f for f in fvg_list if f["in_zone"]]
    return in_zone[-1] if in_zone else fvg_list[-1]


def price_in_fvg(price: float, fvg: dict | None) -> bool:
    """Returns True if price is within the FVG zone (±0.5%)."""
    if not fvg:
        return False
    return fvg["bottom"] * 0.995 <= price <= fvg["top"] * 1.005


# ═══════════════════════════════════════════════════════════════════════════
# ██  SECTION 7 — DISPLACEMENT
# ═══════════════════════════════════════════════════════════════════════════

def detect_displacement(df: pd.DataFrame, trend: str) -> bool:
    """
    Strong displacement = last 1–2 candles show a large body move
    in the trend direction (body ≥ 2× MIN_DISPLACEMENT_PCT).
    """
    threshold = MIN_DISPLACEMENT_PCT * 2
    for candle in [df.iloc[-1], df.iloc[-2]]:
        o, cl = float(candle["open"]), float(candle["close"])
        body_pct = abs(cl - o) / (o + 1e-9) * 100
        if body_pct >= threshold:
            if trend == "BULLISH" and cl > o:
                return True
            if trend == "BEARISH" and cl < o:
                return True
    return False


# ═══════════════════════════════════════════════════════════════════════════
# ██  SECTION 8 — VOLUME
# ═══════════════════════════════════════════════════════════════════════════

def volume_ratio(df: pd.DataFrame, lookback: int = 20) -> float:
    """Current candle volume vs rolling average."""
    avg = df["volume"].iloc[-lookback:-1].mean()
    vol = float(df["volume"].iloc[-1])
    return round(vol / avg, 2) if avg > 0 else 0.0


# ═══════════════════════════════════════════════════════════════════════════
# ██  SECTION 9 — RSI (SCORING ONLY — NEVER BLOCKS TRADES)
# ═══════════════════════════════════════════════════════════════════════════

def calculate_rsi(df: pd.DataFrame, period: int = RSI_PERIOD) -> float:
    """Wilder-smoothed RSI. Returns 50.0 on insufficient data."""
    closes = df["close"].values
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains  = [max(d, 0.0) for d in deltas]
    losses = [abs(min(d, 0.0)) for d in deltas]
    avg_g  = sum(gains[:period]) / period
    avg_l  = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
    if avg_l == 0:
        return 100.0
    return round(100.0 - (100.0 / (1.0 + avg_g / avg_l)), 2)


def rsi_score(rsi: float) -> int:
    """
    RSI scoring factor (never blocks trades).
      +5  RSI 50–65 (ideal momentum)
      −5  RSI > 75 or < 25 (extreme — penalty)
    """
    if 50 <= rsi <= 65:
        return SCORE_RSI_IDEAL
    if rsi > 75 or rsi < 25:
        return SCORE_RSI_PENALTY
    return 0


# ═══════════════════════════════════════════════════════════════════════════
# ██  SECTION 10 — MACRO (BTC + BTC.D) — SCORING ONLY
# ═══════════════════════════════════════════════════════════════════════════

_btcd_cache: dict = {"series": None, "ts": 0.0}


def fetch_btc_dominance_series() -> list | None:
    """Fetch 30-day BTC.D series from CoinGecko (cached 15 min)."""
    global _btcd_cache
    if _btcd_cache["series"] and (time.time() - _btcd_cache["ts"]) < 900:
        return _btcd_cache["series"]
    try:
        url  = "https://api.coingecko.com/api/v3/global/market_cap_chart?vs_currency=usd&days=30"
        r    = requests.get(url, timeout=10, headers={"User-Agent": "SMC-Bot"})
        data = r.json()
        series = [float(x[1]) for x in data.get("market_cap_percentage", {}).get("btc", [])]
        if len(series) >= BTCD_SMA_PERIOD * 2:
            _btcd_cache = {"series": series, "ts": time.time()}
            return series
    except Exception:
        pass
    return None


def get_btcd_trend(series: list | None) -> str:
    """BTC.D trend via SMA20 slope. Returns 'RISING' | 'FALLING' | 'FLAT'."""
    if not series or len(series) < BTCD_SMA_PERIOD * 2:
        return "FLAT"
    sma_now  = sum(series[-BTCD_SMA_PERIOD:]) / BTCD_SMA_PERIOD
    sma_prev = sum(series[-BTCD_SMA_PERIOD * 2:-BTCD_SMA_PERIOD]) / BTCD_SMA_PERIOD
    diff_pct = (sma_now - sma_prev) / (sma_prev + 1e-9) * 100
    if diff_pct > 0.3:  return "RISING"
    if diff_pct < -0.3: return "FALLING"
    return "FLAT"


def get_btc_bias() -> str:
    """Fetch BTC/USDT 1D structural bias."""
    try:
        df_btc = fetch_ohlcv("BTC/USDT", BTC_BIAS_TF, limit=200)
        bias, _, _, _ = detect_structure(df_btc)
        return bias
    except Exception:
        return "RANGING"


def macro_score(pair: str, direction: str, btc_bias: str, btcd_trend: str) -> tuple:
    """
    Macro scoring (NEVER blocks trades).
      +10  Aligned: BTC Bull + BTC.D Falling (alt season) for LONG
               OR  BTC Bear + BTC.D Rising (alt bleed) for SHORT
      −5   Conflict: macro opposes direction
       0   Neutral / BTC or ETH pair / insufficient data

    Returns: (score: int, reason: str)
    """
    if pair in ALTCOIN_EXEMPTIONS:
        return 0, "BTC/ETH exempt"
    if btc_bias == "RANGING" or btcd_trend == "FLAT":
        return 0, "Macro data insufficient"

    if direction == "BULLISH":
        if btc_bias == "BULLISH" and btcd_trend == "FALLING":
            return SCORE_MACRO_ALIGNED, "BTC Bull + BTC.D↓ → Alt season ✅"
        if btc_bias == "BULLISH" and btcd_trend == "RISING":
            return SCORE_MACRO_CONFLICT, "BTC Bull + BTC.D↑ → BTC season, alts weak"
        if btc_bias == "BEARISH" and btcd_trend == "RISING":
            return SCORE_MACRO_CONFLICT, "BTC Bear + BTC.D↑ → Alts bleeding"
        return 0, "No strong macro edge"

    if direction == "BEARISH":
        if btc_bias == "BEARISH" and btcd_trend == "RISING":
            return SCORE_MACRO_ALIGNED, "BTC Bear + BTC.D↑ → Alt bleed ✅"
        if btc_bias == "BULLISH" and btcd_trend == "FALLING":
            return SCORE_MACRO_CONFLICT, "BTC Bull + BTC.D↓ → Alt season, avoid SHORT"
        if btc_bias == "BEARISH" and btcd_trend == "FALLING":
            return SCORE_MACRO_CONFLICT, "BTC Bear + BTC.D↓ → Alts may bounce"
        return 0, "No strong macro edge"

    return 0, "No match"


# ═══════════════════════════════════════════════════════════════════════════
# ██  SECTION 11 — SESSION
# ═══════════════════════════════════════════════════════════════════════════

def get_session() -> str:
    """Return current trading session name."""
    h = datetime.now(timezone.utc).hour
    if 7  <= h < 13: return "London"
    if 12 <= h < 21: return "New York"
    if 0  <= h < 8:  return "Asia"
    return "Off-Hours"


def session_score(session: str) -> int:
    """London or New York → +5 pts."""
    return SCORE_SESSION if session in ("London", "New York") else 0


# ═══════════════════════════════════════════════════════════════════════════
# ██  SECTION 12 — RISK-REWARD CALCULATION
# ═══════════════════════════════════════════════════════════════════════════

def calculate_atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> float:
    """ATR using true range."""
    trs = []
    for i in range(1, len(df)):
        h  = float(df.iloc[i]["high"])
        l  = float(df.iloc[i]["low"])
        pc = float(df.iloc[i - 1]["close"])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if not trs:
        return float(df["high"].iloc[-1] - df["low"].iloc[-1])
    return sum(trs[-period:]) / min(period, len(trs))


def calculate_rr(
    df: pd.DataFrame,
    direction: str,
    ob: dict | None,
    fvg: dict | None,
) -> tuple:
    """
    Calculate SL / TP1 / TP2 / RR.
    SL placed below OB/FVG zone with ATR buffer.
    TP1 = 1.5× SL dist | TP2 = 2.5× SL dist (liquidity target).

    Returns: (entry, sl, tp1, tp2, rr1, rr2)
    """
    entry    = float(df["close"].iloc[-1])
    atr      = calculate_atr(df)
    buf      = atr * 0.5
    highs, lows = find_swings(df)

    if direction == "BULLISH":
        sl_candidates = []
        if ob:          sl_candidates.append(ob["low"] - buf)
        if fvg:         sl_candidates.append(fvg["bottom"] - buf)
        if lows:        sl_candidates.append(min(lows, key=lambda x: abs(x[1] - entry))[1] - buf)
        sl   = min(sl_candidates) if sl_candidates else entry - atr * 2.0
        dist = entry - sl
        tp1  = entry + dist * RR_GRADE_B       # ≥1.5
        tp2  = entry + dist * (RR_GRADE_A + 0.5)  # ≥2.5

    else:  # BEARISH
        sl_candidates = []
        if ob:          sl_candidates.append(ob["high"] + buf)
        if fvg:         sl_candidates.append(fvg["top"] + buf)
        if highs:       sl_candidates.append(min(highs, key=lambda x: abs(x[1] - entry))[1] + buf)
        sl   = max(sl_candidates) if sl_candidates else entry + atr * 2.0
        dist = sl - entry
        tp1  = entry - dist * RR_GRADE_B
        tp2  = entry - dist * (RR_GRADE_A + 0.5)

    sl_dist  = abs(entry - sl)
    tp1_dist = abs(tp1 - entry)
    tp2_dist = abs(tp2 - entry)
    rr1      = round(tp1_dist / sl_dist, 2) if sl_dist > 0 else 0.0
    rr2      = round(tp2_dist / sl_dist, 2) if sl_dist > 0 else 0.0

    return entry, sl, tp1, tp2, rr1, rr2


# ═══════════════════════════════════════════════════════════════════════════
# ██  SECTION 13 — SCORING ENGINE
# ═══════════════════════════════════════════════════════════════════════════

def compute_score(
    htf_aligned:   bool,
    liq_swept:     bool,
    ob_or_fvg:     bool,
    ob_and_fvg:    bool,  # Both present → extra
    displacement:  bool,
    vol_rat:       float,
    session:       str,
    rsi:           float,
    macro_pts:     int,
) -> tuple:
    """
    Build confluence score and breakdown.
    Returns: (total_score: int, breakdown: dict)
    """
    bd = {
        "htf_aligned":   SCORE_HTF_ALIGNED  if htf_aligned  else 0,
        "liquidity":     SCORE_LIQUIDITY    if liq_swept    else 0,
        "ob_fvg":        SCORE_OB_FVG       if ob_or_fvg    else 0,
        "ob_fvg_bonus":  5                  if ob_and_fvg   else 0,  # Both present
        "displacement":  SCORE_DISPLACEMENT if displacement  else 0,
        "volume":        SCORE_VOLUME if vol_rat >= 1.5 else (2 if vol_rat >= 1.2 else 0),
        "session":       session_score(session),
        "rsi":           rsi_score(rsi),
        "macro":         macro_pts,
    }
    total = sum(bd.values())
    return total, bd


def grade_signal(rr: float) -> str | None:
    """Return 'A', 'B', or None (skip)."""
    if rr >= RR_GRADE_A:  return "A"
    if rr >= RR_GRADE_B:  return "B"
    return None


# ═══════════════════════════════════════════════════════════════════════════
# ██  SECTION 14 — COOLDOWN TRACKER
# ═══════════════════════════════════════════════════════════════════════════

# { "PAIR|label|entry_tf": last_signal_timestamp }
_cooldown_map: dict = {}


def is_on_cooldown(pair: str, label: str, entry_tf: str) -> bool:
    key  = f"{pair}|{label}|{entry_tf}"
    last = _cooldown_map.get(key)
    if last is None:
        return False
    elapsed = (datetime.now(timezone.utc) - last).total_seconds() / 60
    return elapsed < COOLDOWN_MINUTES


def set_cooldown(pair: str, label: str, entry_tf: str):
    key = f"{pair}|{label}|{entry_tf}"
    _cooldown_map[key] = datetime.now(timezone.utc)


# ═══════════════════════════════════════════════════════════════════════════
# ██  SECTION 15 — OUTPUT (JSON + TELEGRAM)
# ═══════════════════════════════════════════════════════════════════════════

def build_signal_json(
    pair: str, direction: str, entry: float, sl: float,
    tp1: float, tp2: float, rr: float, score: int,
    grade: str, reasons: list,
) -> dict:
    """Build the standardized JSON signal output."""
    return {
        "pair":        pair,
        "direction":   "LONG" if direction == "BULLISH" else "SHORT",
        "entry":       round(entry, 6),
        "stop_loss":   round(sl, 6),
        "take_profit": [round(tp1, 6), round(tp2, 6)],
        "RR":          rr,
        "score":       score,
        "grade":       grade,
        "reason":      reasons,
    }


def send_telegram(signal: dict, mode: dict, score_bd: dict, session: str,
                  rsi: float, btc_bias: str, btcd_trend: str, macro_reason: str):
    """Format and send Telegram alert."""
    pair    = signal["pair"]
    dir_str = signal["direction"]
    dir_em  = "🟢" if dir_str == "LONG" else "🔴"
    grade   = signal["grade"]
    grade_em = "🏆" if grade == "A" else "🥈"

    tps = signal["take_profit"]
    bar_filled = min(10, int(signal["score"] / 10))
    bar = "█" * bar_filled + "░" * (10 - bar_filled)

    breakdown_lines = "\n".join([
        f"  HTF Aligned    : +{score_bd['htf_aligned']} pts",
        f"  Liquidity      : +{score_bd['liquidity']} pts",
        f"  OB/FVG Zone    : +{score_bd['ob_fvg']}{'+'+str(score_bd['ob_fvg_bonus']) if score_bd['ob_fvg_bonus'] else ''} pts",
        f"  Displacement   : +{score_bd['displacement']} pts",
        f"  Volume         : +{score_bd['volume']} pts",
        f"  Session        : +{score_bd['session']} pts",
        f"  RSI ({rsi:.1f})     : {'+' if score_bd['rsi']>=0 else ''}{score_bd['rsi']} pts",
        f"  Macro          : {'+' if score_bd['macro']>=0 else ''}{score_bd['macro']} pts",
    ])

    reasons_str = "\n".join([f"  • {r}" for r in signal["reason"]])

    msg = (
        f"{dir_em} <b>{pair} — {dir_str}</b>  {grade_em} Grade {grade}\n"
        f"{'─'*38}\n"
        f"📊 Mode     : {mode['label']} ({mode['htf_tf']} → {mode['entry_tf']})\n"
        f"🕐 Session  : {session}\n"
        f"{'─'*38}\n"
        f"💰 Entry    : <b>${signal['entry']:,.4f}</b>\n"
        f"🛑 Stop Loss: ${signal['stop_loss']:,.4f}\n"
        f"🎯 TP1      : ${tps[0]:,.4f}  (1:{RR_GRADE_B})\n"
        f"🎯 TP2      : ${tps[1]:,.4f}  (1:{RR_GRADE_A+0.5:.1f})\n"
        f"📐 RR       : 1:{signal['RR']}\n"
        f"{'─'*38}\n"
        f"🧮 Score    : <b>{signal['score']}/100</b>\n"
        f"  [{bar}]\n"
        f"{breakdown_lines}\n"
        f"{'─'*38}\n"
        f"📋 Reasons:\n{reasons_str}\n"
        f"{'─'*38}\n"
        f"🪙 BTC ({BTC_BIAS_TF}): {btc_bias} | BTC.D: {btcd_trend}\n"
        f"  {macro_reason}\n"
        f"{'─'*38}\n"
        f"⚠️ Signal-only. No execution. Manage your own risk."
    )

    url  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}
    try:
        r = requests.post(url, data=data, timeout=10)
        if r.status_code == 200:
            print("  ✅ Telegram sent!")
        else:
            print(f"  ❌ Telegram error {r.status_code}")
    except Exception as e:
        print(f"  ❌ Telegram unreachable: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# ██  SECTION 16 — PAIR ANALYSIS (EXECUTION FLOW)
# ═══════════════════════════════════════════════════════════════════════════

def analyze_pair(
    pair: str,
    mode: dict,
    df_htf: pd.DataFrame,
    btc_bias: str,
    btcd_trend: str,
    session: str,
):
    """
    Full SMC analysis for one pair + mode.
    Execution flow:
      1. Cooldown check
      2. HTF trend → skip if ranging
      3. Liquidity sweep → skip if none
      4. OB or FVG → skip if neither
      5. Compute score
      6. Compute RR → skip if < 1.5
      7. Score ≥ 60 → send signal
    """
    label    = mode["label"]
    htf_tf   = mode["htf_tf"]
    entry_tf = mode["entry_tf"]

    # ── Step 1: Cooldown ─────────────────────────────────────────────────
    if is_on_cooldown(pair, label, entry_tf):
        return

    # ── Step 2: HTF Bias ─────────────────────────────────────────────────
    htf_bias, htf_event, _, _ = get_htf_bias(df_htf)
    if htf_bias == "RANGING":
        print(f"  ⏭  [{label}] {pair} @ {entry_tf} — HTF ranging, skip")
        return

    trade_direction = htf_bias  # BULLISH or BEARISH

    # ── Step 3: Entry TF data ─────────────────────────────────────────────
    try:
        df_entry = fetch_ohlcv(pair, entry_tf, limit=200)
        time.sleep(0.12)
    except Exception as e:
        print(f"  ❌ [{label}] {pair} @ {entry_tf} fetch failed: {e}")
        return

    # ── Entry TF structure (must align with HTF) ──────────────────────────
    entry_trend, entry_event, _, _ = detect_structure(df_entry)
    if entry_trend not in (trade_direction, "RANGING"):
        # Counter-trend on entry TF — lower quality but still scoreable
        pass

    # ── Step 3a: Liquidity Sweep ──────────────────────────────────────────
    liq_swept, liq_type, liq_level = detect_liquidity_sweep(df_entry, trade_direction)
    if not liq_swept:
        print(f"  ⏭  [{label}] {pair} @ {entry_tf} — No liquidity sweep")
        return

    # ── Step 4: Order Block + FVG ─────────────────────────────────────────
    price   = float(df_entry["close"].iloc[-1])
    ob_list = find_order_blocks(df_entry, trade_direction)
    in_ob, best_ob = price_in_ob(price, ob_list)

    fvg    = find_fvg(df_entry, trade_direction)
    in_fvg = price_in_fvg(price, fvg)

    if not in_ob and not in_fvg:
        print(f"  ⏭  [{label}] {pair} @ {entry_tf} — No OB or FVG")
        return

    # ── Step 5: Supporting factors ───────────────────────────────────────
    displacement = detect_displacement(df_entry, trade_direction)
    vol_rat      = volume_ratio(df_entry)
    rsi          = calculate_rsi(df_entry)
    m_pts, macro_reason = macro_score(pair, trade_direction, btc_bias, btcd_trend)

    # ── Step 5a: Build score ──────────────────────────────────────────────
    score, score_bd = compute_score(
        htf_aligned  = (htf_bias == trade_direction),
        liq_swept    = liq_swept,
        ob_or_fvg    = (in_ob or in_fvg),
        ob_and_fvg   = (in_ob and in_fvg),
        displacement = displacement,
        vol_rat      = vol_rat,
        session      = session,
        rsi          = rsi,
        macro_pts    = m_pts,
    )

    # ── Step 6: RR calculation ───────────────────────────────────────────
    entry, sl, tp1, tp2, rr1, rr2 = calculate_rr(
        df_entry, trade_direction,
        best_ob if in_ob else None,
        fvg if in_fvg else None,
    )

    grade = grade_signal(rr1)
    if grade is None:
        print(f"  ⛔ [{label}] {pair} @ {entry_tf} — RR {rr1} < 1.5, skip")
        return

    # ── Step 7: Score gate ────────────────────────────────────────────────
    if score < MIN_SCORE:
        print(f"  ⛔ [{label}] {pair} @ {entry_tf} — Score {score} < {MIN_SCORE}, skip")
        return

    # ── Build reason list ─────────────────────────────────────────────────
    reasons = [
        f"HTF {htf_bias} ({htf_tf}) — {htf_event or 'trend confirmed'}",
        f"Liquidity: {liq_type} @ {liq_level:.4f}" if liq_level else f"Liquidity: {liq_type}",
    ]
    if in_ob and best_ob:
        reasons.append(f"Order Block: ${best_ob['low']:.4f}–${best_ob['high']:.4f} (taps: {best_ob['taps']})")
    if in_fvg and fvg:
        reasons.append(f"FVG: ${fvg['bottom']:.4f}–${fvg['top']:.4f} ({fvg['fill_pct']*100:.0f}% filled)")
    if in_ob and in_fvg:
        reasons.append("OB + FVG confluence ✅")
    if displacement:
        reasons.append("Strong displacement confirmed")
    if vol_rat >= 1.5:
        reasons.append(f"Volume spike: {vol_rat}×")
    if session in ("London", "New York"):
        reasons.append(f"Prime session: {session}")
    reasons.append(f"RSI: {rsi:.1f} → {'+' if rsi_score(rsi) >= 0 else ''}{rsi_score(rsi)} pts")
    reasons.append(f"Macro: {macro_reason}")

    # ── Build + send signal ───────────────────────────────────────────────
    signal = build_signal_json(
        pair=pair, direction=trade_direction,
        entry=entry, sl=sl, tp1=tp1, tp2=tp2,
        rr=rr1, score=score, grade=grade,
        reasons=reasons,
    )

    print(f"\n  🚨 SIGNAL → {pair} {signal['direction']} | Score:{score} | Grade:{grade} | RR:1:{rr1}")
    print(f"     Entry:{entry:.4f} | SL:{sl:.4f} | TP1:{tp1:.4f} | TP2:{tp2:.4f}")
    print(f"     Reasons: {', '.join(reasons[:3])}")

    send_telegram(signal, mode, score_bd, session, rsi, btc_bias, btcd_trend, macro_reason)
    set_cooldown(pair, label, entry_tf)


# ═══════════════════════════════════════════════════════════════════════════
# ██  SECTION 17 — WELCOME LISTENER (POLLING)
# ═══════════════════════════════════════════════════════════════════════════
#
#  Berjalan di background thread. Setiap ada member baru join channel/grup,
#  bot kirim WELCOME_MESSAGE ke channel yang sama.
#
#  Syarat agar welcome berfungsi:
#  1. Bot harus ADMIN di channel / supergroup
#  2. TELEGRAM_CHAT_ID harus ID channel/grup (format -100xxxxxxxxxx)
#  3. Untuk channel publik: bot perlu izin "Post Messages"
#  4. Untuk supergroup: event new_chat_members muncul otomatis di getUpdates
#
#  Catatan: Telegram channel (bukan grup) tidak mengirim new_chat_members
#  ke bot via getUpdates — untuk pure channel, pertimbangkan pakai
#  supergroup/grup saja agar welcome event bisa ditangkap.
# ═══════════════════════════════════════════════════════════════════════════



def _send_raw(chat_id: str, text: str):
    """Kirim pesan mentah ke chat_id tertentu."""
    url  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    try:
        requests.post(url, data=data, timeout=10)
    except Exception as e:
        print(f"  ⚠️  Telegram send error: {e}")


def _get_updates(offset: int) -> list:
    """Ambil update terbaru dari Telegram getUpdates (long polling)."""
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
            params={"offset": offset, "timeout": 20, "allowed_updates": '["message","chat_member"]'},
            timeout=25,
        )
        return r.json().get("result", [])
    except Exception:
        return []


def welcome_polling_loop():
    """
    Background thread: polling update Telegram, deteksi member baru,
    kirim welcome message.
    """
    global _tg_offset
    print("🔔 Welcome listener aktif...")

    while True:
        try:
            updates = _get_updates(_tg_offset)
            for update in updates:
                _tg_offset = update["update_id"] + 1

                # ── Cek new_chat_members di message biasa (grup/supergroup) ──
                msg = update.get("message", {})
                new_members = msg.get("new_chat_members", [])
                chat_id = str(msg.get("chat", {}).get("id", ""))

                # ── Cek chat_member update (channel dengan admin rights) ──────
                if not new_members:
                    cm = update.get("chat_member", {})
                    new_status = cm.get("new_chat_member", {}).get("status", "")
                    old_status = cm.get("old_chat_member", {}).get("status", "")
                    # member baru = status berubah dari left/kicked → member
                    if new_status == "member" and old_status in ("left", "kicked", ""):
                        new_members = [cm.get("new_chat_member", {}).get("user", {})]
                        chat_id = str(cm.get("chat", {}).get("id", ""))

                if not new_members or not chat_id:
                    continue

                if not WELCOME_ENABLED:
                    continue

                for user in new_members:
                    # Abaikan bot lain yang join
                    if user.get("is_bot"):
                        continue

                    # Buat nama tampilan
                    first = user.get("first_name", "")
                    last  = user.get("last_name", "")
                    name  = (first + " " + last).strip() or user.get("username", "Member")
                    username = user.get("username", "")
                    mention = f"<a href='tg://user?id={user['id']}'>{name}</a>" if user.get("id") else name

                    welcome_text = WELCOME_MESSAGE.format(name=mention)
                    _send_raw(chat_id, welcome_text)
                    print(f"  👋 Welcome sent → {name} (@{username}) di chat {chat_id}")

        except Exception as e:
            print(f"  ⚠️  Welcome polling error: {e}")

        time.sleep(2)


# ═══════════════════════════════════════════════════════════════════════════
# ██  SECTION 18 — MAIN SCAN LOOP
# ═══════════════════════════════════════════════════════════════════════════

def run_bot():
    print("=" * 70)
    print("🤖  Yudhystirady CRYPTO SIGNAL BOT — Clean Modular Edition")
    print("=" * 70)
    print(f"📊 Pairs       : {len(PAIRS)}")
    print(f"🔢 Modes       : {len(MODES)} (HTF → Entry TF)")
    print(f"🧮 Score Gate  : ≥ {MIN_SCORE} pts to fire signal")
    print(f"📐 RR Gate     : ≥ {RR_GRADE_B} (Grade B) | ≥ {RR_GRADE_A} (Grade A)")
    print(f"⏱  Cooldown    : {COOLDOWN_MINUTES} min per pair/mode/TF")
    print(f"🔔 Welcome     : {'ON' if WELCOME_ENABLED else 'OFF'}")
    print(f"📢 Target Chat : {TELEGRAM_CHAT_ID}")
    print()
    print("SCORING (max ~100 pts):")
    print(f"  +{SCORE_HTF_ALIGNED} HTF aligned | +{SCORE_LIQUIDITY} Liquidity | +{SCORE_OB_FVG} OB/FVG")
    print(f"  +{SCORE_DISPLACEMENT} Displacement | +{SCORE_VOLUME} Volume | +{SCORE_SESSION} Session")
    print(f"  +{SCORE_RSI_IDEAL} RSI 50–65 | +{SCORE_MACRO_ALIGNED} Macro aligned")
    print(f"  {SCORE_RSI_PENALTY} RSI extreme | {SCORE_MACRO_CONFLICT} Macro conflict")
    print()
    print("ℹ️  RSI and Macro are SCORING FACTORS only — they never block trades.")
    print("=" * 70)

    # ── Start welcome listener di background thread ───────────────────────
    tg_thread = threading.Thread(target=welcome_polling_loop, daemon=True)
    tg_thread.start()

    htf_tfs_needed = list({m["htf_tf"] for m in MODES})

    while True:
        ts      = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        session = get_session()
        print(f"\n{'─'*70}")
        print(f"🔍 Scan [{ts}] | Session: {session} | Exchange: {_aktif_exchange}")

        # ── Fetch macro data once per cycle ──────────────────────────────
        btc_bias    = get_btc_bias()
        btcd_series = fetch_btc_dominance_series()
        btcd_trend  = get_btcd_trend(btcd_series)
        print(f"🪙 BTC Bias ({BTC_BIAS_TF}): {btc_bias} | BTC.D: {btcd_trend}")

        for pair in PAIRS:
            # ── Pre-fetch HTF data (shared across modes) ──────────────────
            htf_cache: dict = {}
            for htf_tf in htf_tfs_needed:
                try:
                    htf_cache[htf_tf] = fetch_ohlcv(pair, htf_tf, limit=200)
                    time.sleep(0.1)
                except Exception as e:
                    print(f"  ⚠️  HTF fetch failed {pair} @ {htf_tf}: {e}")
                    htf_cache[htf_tf] = None

            for mode in MODES:
                df_htf = htf_cache.get(mode["htf_tf"])
                if df_htf is None:
                    continue
                try:
                    analyze_pair(
                        pair=pair, mode=mode, df_htf=df_htf,
                        btc_bias=btc_bias, btcd_trend=btcd_trend,
                        session=session,
                    )
                except Exception as e:
                    print(f"  ❌ [{mode['label']}] {pair} error: {e}")

        print(f"\n⏳ Next scan in {SCAN_INTERVAL // 60} min...")
        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    run_bot()
