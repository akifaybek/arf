"""
metrics.py — Arf'in DETERMINISTIK olcum katmani. LLM burada hesap YAPMAZ;
agent.py yalnizca bu fonksiyonlarin ciktisini okur.

Icerik:
  * walk_book        — tahtayi yurut: vwap, kayma (bps), dolum
  * max_safe_size    — kayma esigini asmadan girilebilecek en buyuk tutar
  * robust_z         — medyan/MAD tabanli saglam z
  * bonferroni_threshold — 20 paritelik aile icin iki yonlu z esigi
  * depth_vs_memory  — simdiki derinlik / hafizadaki medyan derinlik
  * volume_quality   — 24s hacim / +-%2 derinlik
  * risk_score       — bilesenleri 0-10000 skoruna cevirir (VARSAYIM agirliklar)
  * check_execution_core — canli tahta + epizodik hafiza -> tek sozluk

Birimler: tahta seviyeleri [fiyat, miktar(BAZ)]; tutarlar USDT; kayma bps
(1 bps = %0.01). Kayma MID fiyata gore olculur, yani YARIM SPREAD DAHILDIR
(agent bunu "piyasa emriyle aninda al/sat maliyeti" olarak okur).

Esikler ve agirliklar olculmus degerler DEGIL, TASARIM TERCIHIDIR; her biri
asagida VARSAYIM olarak isaretli ve tek yerde (RISK_WEIGHTS / RISK_SCALES)
toplanmistir.
"""

import math
import sqlite3
import time
from pathlib import Path
from statistics import NormalDist, median

import atk_client

# MUTLAK yol: Streamlit baska bir calisma dizininden baslatilabilir
DB_PATH = str(Path(__file__).resolve().parent / "memory.db")

# Veri bu yastan eskiyse yeni imza uretilmez.
MAX_DATA_AGE_S = 120

# Hafizada bundan az nokta varsa z bilesenleri hesaplanmaz
MIN_MEMORY_POINTS = 30

# Hafizadan kac ornek okunur (60 sn araliklarla ~2 saat)
MEMORY_LOOKBACK = 120

# Kayma esigi: bunun altinda kalan en buyuk tutar "guvenli" sayilir
DEFAULT_MAX_SLIP_BPS = 100  # %1 kayma siniri

# --- VARSAYIM: risk skoru agirliklari (toplam 1.0) ---------------------------
# Hicbiri olculmus bir parametre degil; aciklanabilir olsun diye duz dogrusal.
RISK_WEIGHTS = {
    "slippage": 0.35,   # istenen tutardaki kayma
    "depth_drop": 0.20,  # hafizaya gore derinlik dususu
    "anomaly": 0.15,     # log-getiri / log-derinlik z'si (Bonferroni esigine gore)
    "spread": 0.15,      # anlik spread
    "no_fill": 0.15,     # tahta istenen tutari karsilamiyor
}

# --- VARSAYIM: bilesenleri 0..1 arasina indiren olcekler ---------------------
# "full" = o bilesenin riskinin tavan sayildigi deger.
RISK_SCALES = {
    "slippage_full_bps": 200.0,  # %2 kayma -> bilesen 1.0
    "depth_drop_full": 0.50,     # derinlik yariya inmis -> bilesen 1.0
    "spread_full_bps": 100.0,    # %1 spread -> bilesen 1.0
}

# --- VARSAYIM: hafiza yetersizse muhafazakar sabit katki --------------------
LIMITED_MEMORY_PENALTY = 1000  # 0-10000 skalasinda

RISK_SCORE_MAX = 10_000


# =============================================================================
# Tahta yurume (saf fonksiyonlar, I/O yok)
# =============================================================================

def _sorted_levels(book):
    """Tahtayi (fiyat, miktar) ciftlerine cevirir; ask artan, bid azalan.

    OKX zaten sirali donuyor; yine de sentetik/bozuk girdilere karsi
    savunma amacli siralanir.
    """
    if not book:
        return [], []
    raw_asks = book.get("asks") or []
    raw_bids = book.get("bids") or []
    asks = sorted(((float(p), float(q)) for p, q, *_ in raw_asks), key=lambda x: x[0])
    bids = sorted(((float(p), float(q)) for p, q, *_ in raw_bids), key=lambda x: -x[0])
    asks = [(p, q) for p, q in asks if p > 0 and q > 0]
    bids = [(p, q) for p, q in bids if p > 0 and q > 0]
    return asks, bids


def mid_price(book):
    """En iyi alis/satisin ortasi. Tahta kullanilamazsa None."""
    asks, bids = _sorted_levels(book)
    if not asks or not bids:
        return None
    mid = (asks[0][0] + bids[0][0]) / 2
    return mid if mid > 0 else None


def spread_bps(book):
    """Anlik spread, bps. Tahta kullanilamazsa None."""
    asks, bids = _sorted_levels(book)
    if not asks or not bids:
        return None
    mid = (asks[0][0] + bids[0][0]) / 2
    if mid <= 0:
        return None
    return (asks[0][0] - bids[0][0]) / mid * 10_000


def walk_book(book, side, notional_usdt):
    """`notional_usdt` kadarlik piyasa emrini tahtada yurutur.

    side="buy"  -> ask'lar en iyiden (en ucuzdan) yukari dogru
    side="sell" -> bid'ler en iyiden (en pahalidan) asagi dogru

    Doner: vwap, slippage_bps (MID'e gore, yarim spread DAHIL), filled_usdt,
    fills (tahta biterse False), levels_used. Tahta kullanilamazsa None.
    """
    if side not in ("buy", "sell"):
        raise ValueError(f"side 'buy' veya 'sell' olmali: {side!r}")
    if notional_usdt is None or notional_usdt <= 0:
        raise ValueError(f"notional_usdt pozitif olmali: {notional_usdt!r}")

    asks, bids = _sorted_levels(book)
    if not asks or not bids:
        return None
    mid = (asks[0][0] + bids[0][0]) / 2
    if mid <= 0:
        return None

    levels = asks if side == "buy" else bids

    cost = 0.0        # harcanan/alinan USDT
    base = 0.0        # el degistiren baz varlik
    used = 0
    remaining = float(notional_usdt)

    for price, qty in levels:
        used += 1
        level_usdt = price * qty
        if level_usdt >= remaining:
            base += remaining / price
            cost += remaining
            remaining = 0.0
            break
        base += qty
        cost += level_usdt
        remaining -= level_usdt

    fills = remaining <= 1e-9
    vwap = cost / base if base > 0 else None
    if vwap is None:
        return None

    # Kayma MID'e gore: alista vwap mid'in uzerinde, satista altinda olur.
    slip = (vwap - mid) / mid if side == "buy" else (mid - vwap) / mid

    return {
        "side": side,
        "mid": mid,
        "vwap": vwap,
        "slippage_bps": slip * 10_000,
        "requested_usdt": float(notional_usdt),
        "filled_usdt": cost,
        "base_filled": base,
        "fills": fills,
        "levels_used": used,
        "levels_available": len(levels),
    }


def max_safe_size(book, side, max_slip_bps=DEFAULT_MAX_SLIP_BPS, book_truncated=False):
    """Kayma `max_slip_bps`'i asmadan girilebilecek en buyuk USDT tutari.

    Seviye seviye kumulatif yurunur. Bir seviyenin fiyati esik fiyatin
    icindeyse seviye tamamen alinir (vwap <= alinan en kotu fiyat <= esik).
    Esigin otesindeki seviyede, vwap tam esige oturan miktar KAPALI FORMLE
    cozulur (dogrusal interpolasyon yerine kesin cozum):
        alis:  x = (t*B - C) / (p - t),  t = mid*(1 + s)
        satis: x = (C - t*B) / (t - p),  t = mid*(1 - s)
    B/C o ana kadar birikmis baz/USDT, p seviye fiyati, s kayma esigi.

    is_lower_bound: tahta esige ulasmadan bittiyse True -> gercek guvenli
    tutar daha buyuk olabilir, raporlanan deger ALT SINIR'dir.
    """
    if side not in ("buy", "sell"):
        raise ValueError(f"side 'buy' veya 'sell' olmali: {side!r}")

    asks, bids = _sorted_levels(book)
    if not asks or not bids:
        return None
    mid = (asks[0][0] + bids[0][0]) / 2
    if mid <= 0:
        return None

    s = max_slip_bps / 10_000.0
    target = mid * (1 + s) if side == "buy" else mid * (1 - s)
    levels = asks if side == "buy" else bids

    base = 0.0
    cost = 0.0
    used = 0
    exhausted = True  # esige takilmadan tahta bittiyse True kalir

    for price, qty in levels:
        inside = price <= target if side == "buy" else price >= target
        if inside:
            base += qty
            cost += price * qty
            used += 1
            continue

        # Esigin otesindeki seviye: vwap'i tam esige oturtan miktar
        denom = (price - target) if side == "buy" else (target - price)
        numer = (target * base - cost) if side == "buy" else (cost - target * base)
        x = numer / denom if denom > 0 else 0.0
        if x <= 0:
            exhausted = False
            break
        if x >= qty:
            # Seviyenin tamami alinsa bile vwap esigin icinde kaliyor
            base += qty
            cost += price * qty
            used += 1
            continue
        base += x
        cost += price * x
        used += 1
        exhausted = False
        break

    return {
        "side": side,
        "mid": mid,
        "max_slip_bps": float(max_slip_bps),
        "max_safe_usdt": cost,
        "levels_used": used,
        "levels_available": len(levels),
        "is_lower_bound": exhausted,
        "book_truncated": bool(book_truncated),
    }


# =============================================================================
# Istatistik (saf fonksiyonlar)
# =============================================================================

MAD_TO_SIGMA = 1.4826  # normal dagilimda MAD -> standart sapma olcegi


def robust_z(series):
    """Serinin SON elemaninin saglam z'si: (x - medyan) / (1.4826 * MAD).

    MAD = 0 (veya 3'ten az nokta) ise None -> "olculemez", sifir degil.
    """
    if series is None:
        return None
    vals = [float(x) for x in series if x is not None and math.isfinite(float(x))]
    if len(vals) < 3:
        return None
    med = median(vals)
    mad = median([abs(x - med) for x in vals])
    if mad == 0:
        return None
    return (vals[-1] - med) / (MAD_TO_SIGMA * mad)


def bonferroni_threshold(alpha=0.05, m=20):
    """m paritelik aile icin iki yonlu z esigi (Bonferroni duzeltmesi).

    Deger SABIT YAZILMAZ, hesaplanir: inv_cdf(1 - alpha/(2m)).
    """
    if not 0 < alpha < 1:
        raise ValueError("alpha (0,1) araliginda olmali")
    if m < 1:
        raise ValueError("m >= 1 olmali")
    return NormalDist().inv_cdf(1 - alpha / (2 * m))


def log_changes(series):
    """Ardisik oranlarin dogal logaritmasi: log(x_t / x_{t-1})."""
    out = []
    if not series:
        return out
    prev = None
    for x in series:
        if x is None or not math.isfinite(float(x)) or float(x) <= 0:
            prev = None
            continue
        x = float(x)
        if prev is not None:
            out.append(math.log(x / prev))
        prev = x
    return out


def depth_vs_memory(current_depth_usdt, memory_depths):
    """Simdiki +-%2 derinlik / hafizadaki medyan derinlik. Olculemezse None."""
    if current_depth_usdt is None or not memory_depths:
        return None
    vals = [float(x) for x in memory_depths if x is not None and float(x) > 0]
    if not vals:
        return None
    med = median(vals)
    if med <= 0:
        return None
    return float(current_depth_usdt) / med


def volume_quality(vol24h_usdt, bid_depth_usdt, ask_depth_usdt):
    """24s hacim / (+-%2 alis + satis derinligi). Derinlik yoksa None.

    Yuksek deger: tahtada gorunen likiditeye kiyasla cok islem hacmi.
    """
    if vol24h_usdt is None:
        return None
    total = (bid_depth_usdt or 0.0) + (ask_depth_usdt or 0.0)
    if total <= 0:
        return None
    return float(vol24h_usdt) / total


# =============================================================================
# Risk skoru
# =============================================================================

def _clamp01(x):
    return 0.0 if x < 0 else (1.0 if x > 1 else x)


def risk_score(components, weights=None, scales=None):
    """Bilesenleri 0-10000 arasi skora cevirir (yuksek = riskli).

    components:
      slippage_bps   : istenen tutardaki kayma (None ise bilesen 0 sayilir)
      fills          : tahta istenen tutari karsiliyor mu (bool)
      depth_ratio    : simdiki derinlik / hafizadaki medyan (None olabilir)
      anomaly_z      : |z| (log-getiri ve log-derinlik z'lerinin buyugu)
      bonferroni_z   : anomaly_z'nin normalize edilecegi esik
      spread_bps     : anlik spread
      limited_memory : hafiza < MIN_MEMORY_POINTS (bool)

    VARSAYIM: agirliklar RISK_WEIGHTS, olcekler RISK_SCALES, hafiza cezasi
    LIMITED_MEMORY_PENALTY. Hicbiri olculmus degil; hepsi tasarim tercihi.
    Formul duz dogrusal: skor = 10000 * sum(w_i * n_i) (+ hafiza cezasi).
    """
    w = dict(RISK_WEIGHTS if weights is None else weights)
    sc = dict(RISK_SCALES if scales is None else scales)

    slip = components.get("slippage_bps")
    n_slip = _clamp01((slip or 0.0) / sc["slippage_full_bps"])

    ratio = components.get("depth_ratio")
    n_depth = 0.0 if ratio is None else _clamp01((1.0 - ratio) / sc["depth_drop_full"])

    z = components.get("anomaly_z")
    bz = components.get("bonferroni_z") or bonferroni_threshold()
    n_anom = 0.0 if z is None or bz <= 0 else _clamp01(abs(z) / bz)

    spr = components.get("spread_bps")
    n_spread = _clamp01((spr or 0.0) / sc["spread_full_bps"])

    n_nofill = 0.0 if components.get("fills", True) else 1.0

    raw = (
        w["slippage"] * n_slip
        + w["depth_drop"] * n_depth
        + w["anomaly"] * n_anom
        + w["spread"] * n_spread
        + w["no_fill"] * n_nofill
    )
    score = raw * RISK_SCORE_MAX
    if components.get("limited_memory"):
        score += LIMITED_MEMORY_PENALTY

    score = int(round(min(max(score, 0.0), float(RISK_SCORE_MAX))))
    return score, {
        "slippage": n_slip,
        "depth_drop": n_depth,
        "anomaly": n_anom,
        "spread": n_spread,
        "no_fill": n_nofill,
    }


# =============================================================================
# Hafiza okuma (I/O — saf fonksiyonlardan ayri)
# =============================================================================

def load_memory(inst, db_path=DB_PATH, limit=MEMORY_LOOKBACK):
    """Paritenin son `limit` basarili ornegini ESKIDEN YENIYE dondurur."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        return {"n": 0, "mids": [], "depths": [], "error": str(exc)}

    try:
        rows = conn.execute(
            "SELECT ts, mid, bid_depth_2pct_usdt, ask_depth_2pct_usdt"
            " FROM snapshots WHERE inst = ? AND ok = 1"
            " ORDER BY ts DESC LIMIT ?",
            (inst, limit),
        ).fetchall()
    except sqlite3.Error as exc:
        return {"n": 0, "mids": [], "depths": [], "error": str(exc)}
    finally:
        conn.close()

    rows.reverse()  # eskiden yeniye
    mids = [r[1] for r in rows]
    depths = [(r[2] or 0.0) + (r[3] or 0.0) for r in rows]
    return {
        "n": len(rows),
        "mids": mids,
        "depths": depths,
        "last_ts": rows[-1][0] if rows else None,
        "error": None,
    }


# =============================================================================
# Ana giris: tek paritede icra kontrolu
# =============================================================================

def check_execution_core(
    symbol,
    side,
    size_usdt,
    book_result=None,
    memory=None,
    db_path=DB_PATH,
    now=None,
    max_slip_bps=DEFAULT_MAX_SLIP_BPS,
    alpha=0.05,
    universe_size=20,
):
    """Canli tahta + epizodik hafiza -> deterministik icra karnesi.

    book_result: atk_client.get_orderbook ciktisi (test icin enjekte edilebilir).
    memory: load_memory ciktisi (verilmezse db_path'ten okunur).

    status:
      INSUFFICIENT_DATA  — tahta alinamadi veya veri > MAX_DATA_AGE_S
                           (riskScore/maxSafeSize None -> imza YOK)
      OK_LIMITED_MEMORY  — hafiza < MIN_MEMORY_POINTS; z bilesenleri None,
                           skora muhafazakar sabit katki
      OK                 — tam olcum
    """
    if side not in ("buy", "sell"):
        raise ValueError(f"side 'buy' veya 'sell' olmali: {side!r}")

    now = time.time() if now is None else float(now)
    if book_result is None:
        book_result = atk_client.get_orderbook(symbol)

    fetched_at = book_result.get("fetched_at")
    data_age_s = None if fetched_at is None else now - float(fetched_at)

    base = {
        "symbol": symbol,
        "side": side,
        "size_usdt": float(size_usdt),
        "data_age_s": None if data_age_s is None else round(data_age_s, 3),
        "bonferroni_z": bonferroni_threshold(alpha, universe_size),
    }

    # --- fail-closed: veri yok veya bayat -----------------------------------
    book = book_result.get("data") if book_result.get("ok") else None
    if (
        not book_result.get("ok")
        or book is None
        or data_age_s is None
        or data_age_s > MAX_DATA_AGE_S
    ):
        reason = book_result.get("error") or (
            f"veri {data_age_s:.1f} sn eski (sinir {MAX_DATA_AGE_S} sn)"
            if data_age_s is not None and data_age_s > MAX_DATA_AGE_S
            else "tahta yok"
        )
        return {
            **base,
            "status": "INSUFFICIENT_DATA",
            "reason": reason,
            "riskScore": None,
            "maxSafeSize": None,
            "slippage_bps_at_size": None,
            "fills": None,
            "components": {},
            "memory_points": 0 if memory is None else memory.get("n", 0),
        }

    depth = atk_client.depth_within(book)
    if depth is None:
        return {
            **base,
            "status": "INSUFFICIENT_DATA",
            "reason": "tahta bos/bozuk (depth_within None)",
            "riskScore": None,
            "maxSafeSize": None,
            "slippage_bps_at_size": None,
            "fills": None,
            "components": {},
            "memory_points": 0 if memory is None else memory.get("n", 0),
        }

    walk = walk_book(book, side, size_usdt)
    safe = max_safe_size(book, side, max_slip_bps, depth["book_truncated"])

    if memory is None:
        memory = load_memory(symbol, db_path=db_path)
    mem_n = memory.get("n", 0)
    limited = mem_n < MIN_MEMORY_POINTS

    # Hafizaya dayali bilesenler
    current_depth = depth["bid_depth_usdt"] + depth["ask_depth_usdt"]
    if limited:
        z_ret = z_depth = None
        depth_ratio = None
    else:
        z_ret = robust_z(log_changes(memory["mids"]))
        z_depth = robust_z(log_changes(memory["depths"]))
        depth_ratio = depth_vs_memory(current_depth, memory["depths"])

    zs = [abs(z) for z in (z_ret, z_depth) if z is not None]
    anomaly_z = max(zs) if zs else None

    components = {
        "slippage_bps": walk["slippage_bps"] if walk else None,
        "fills": bool(walk["fills"]) if walk else False,
        "depth_ratio": depth_ratio,
        "anomaly_z": anomaly_z,
        "bonferroni_z": base["bonferroni_z"],
        "spread_bps": depth["spread_bps"],
        "limited_memory": limited,
        # bilgi amacli (skora girmez)
        "z_log_return": z_ret,
        "z_log_depth": z_depth,
        "bid_depth_2pct_usdt": depth["bid_depth_usdt"],
        "ask_depth_2pct_usdt": depth["ask_depth_usdt"],
        "book_truncated": depth["book_truncated"],
        "max_safe_is_lower_bound": safe["is_lower_bound"] if safe else None,
    }

    score, normalized = risk_score(components)
    components["normalized"] = normalized

    return {
        **base,
        "status": "OK_LIMITED_MEMORY" if limited else "OK",
        "reason": None,
        "riskScore": score,
        "maxSafeSize": safe["max_safe_usdt"] if safe else 0.0,
        "slippage_bps_at_size": walk["slippage_bps"] if walk else None,
        "fills": bool(walk["fills"]) if walk else False,
        "components": components,
        "memory_points": mem_n,
    }
