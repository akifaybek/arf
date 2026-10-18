"""
atk_client.py — OKX Agent Trade Kit (`okx`) CLI'si icin ince bir sarmalayici.

Veri SADECE buradan gelir; OKX REST/WS dogrudan cagrilmaz. Her cagri
OKX_SITE=tr ortam degiskeni ve --json bayragi ile yapilir. Hata, timeout
veya bozuk JSON durumunda exception FIRLATILMAZ; {"ok": False, ...} doner.
Boylece logger tek bir paritenin hatasinda durmaz (fail-closed, gorunur hata).
"""

import json
import os
import subprocess
import sys
import time

# ATK CLI sinirlari: docs/validation.md
ORDERBOOK_MAX_SZ = 400  # --sz 401 ve ustu: "Parameter sz error" (Code 51000)
CLI_TIMEOUT_S = 10

# Fail-closed sahnesi icin veri kesintisi SIMULASYONU.
# ARF_FEED_DOWN=1 ise hicbir CLI cagrisi yapilmaz, her istek ok=False doner.
# Boylece "veri kesilirse ne olur" sorusu gercek kod yolunda gosterilir:
# metrics -> INSUFFICIENT_DATA, agent -> VERI_YETERSIZ, imza YOK.
FEED_DOWN_ENV = "ARF_FEED_DOWN"
FEED_DOWN_ERROR = "feed_down (SIMULASYON)"


def feed_down():
    """Veri kesintisi simulasyonu acik mi (ARF_FEED_DOWN=1)."""
    return os.environ.get(FEED_DOWN_ENV, "").strip() in ("1", "true", "TRUE", "yes")


def run_okx(args):
    """`okx <args...> --json` calistirir. ASLA exception firlatmaz.

    Donus sozlugu: ok, data, error, fetched_at (unix sn), latency_ms.
    """
    cmd = ["okx"] + list(args) + ["--json"]
    env = dict(os.environ)
    env["OKX_SITE"] = "tr"

    started = time.time()
    if feed_down():
        # SIMULASYON: CLI hic cagrilmaz, besleme kopmus gibi davranilir
        return _result(False, None, FEED_DOWN_ERROR, started)
    try:
        proc = subprocess.run(
            cmd, env=env, capture_output=True, text=True, timeout=CLI_TIMEOUT_S
        )
    except subprocess.TimeoutExpired:
        return _result(False, None, f"timeout ({CLI_TIMEOUT_S}s): {' '.join(cmd)}", started)
    except Exception as exc:  # CLI bulunamadi vb.
        return _result(False, None, f"calistirilamadi: {exc}", started)

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:300]
        return _result(False, None, f"cikis kodu {proc.returncode}: {detail}", started)

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return _result(False, None, f"bozuk JSON: {exc}", started)

    return _result(True, data, None, started)


def _result(ok, data, error, started):
    return {
        "ok": ok,
        "data": data,
        "error": error,
        "fetched_at": time.time(),
        "latency_ms": int((time.time() - started) * 1000),
    }


def get_ticker(inst):
    """Tek parite ticker'i. data: tek sozluk (liste ilk elemani) veya None."""
    res = run_okx(["market", "ticker", inst])
    if res["ok"]:
        res["data"] = _first(res["data"])
        if res["data"] is None:
            res["ok"], res["error"] = False, f"{inst} icin ticker bos dondu"
    return res


def get_tickers_spot():
    """Tum SPOT ticker'lari. data: sozluk listesi (TR'de ~1184 kayit)."""
    return run_okx(["market", "tickers", "SPOT"])


def get_orderbook(inst, sz=ORDERBOOK_MAX_SZ):
    """Emir tahtasi. data: {"asks": [...], "bids": [...], "ts", "seqId"}.

    Seviye formati: [fiyat, miktar(BAZ), "0", emir_sayisi].
    """
    sz = min(int(sz), ORDERBOOK_MAX_SZ)
    res = run_okx(["market", "orderbook", inst, "--sz", str(sz)])
    if res["ok"]:
        res["data"] = _first(res["data"])
        if res["data"] is None:
            res["ok"], res["error"] = False, f"{inst} icin tahta bos dondu"
    return res


def get_candles(inst, bar="1m", limit=60):
    """Mumlar. data: [ts(ms), o, h, l, c, vol(BAZ), volCcy(USDT), _, confirm].

    Siralama YENIDEN -> ESKIYE.
    """
    return run_okx(["market", "candles", inst, "--bar", bar, "--limit", str(limit)])


def get_instruments_spot():
    """SPOT enstrumanlari. data icinde `state`, `baseCcy`, `quoteCcy`, `minSz`."""
    return run_okx(["market", "instruments", "--instType", "SPOT"])


def _first(data):
    """ATK cogu komutta tek elemanli liste donuyor; ilk elemani al."""
    if isinstance(data, list):
        return data[0] if data else None
    return data


def depth_within(book, pct=0.02):
    """Tahtanin +-pct bandindaki likiditeyi USDT cinsinden toplar.

    USDT derinlik = fiyat x miktar (miktar BAZ cinsinden, OLCULDU).
    book_truncated: donen 400 seviye bandin ucuna ULASMADI mi.
    True ise raporlanan derinlik ALT SINIR'dir (tahta kirpildi) --
    likit paritelerde normal, sigligin isareti DEGIL.
    """
    if not book:
        return None
    asks = book.get("asks") or []
    bids = book.get("bids") or []
    if not asks or not bids:
        return None

    best_ask = float(asks[0][0])
    best_bid = float(bids[0][0])
    mid = (best_ask + best_bid) / 2
    if mid <= 0:
        return None

    ask_limit = mid * (1 + pct)
    bid_limit = mid * (1 - pct)

    ask_depth = sum(float(p) * float(q) for p, q, *_ in asks if float(p) <= ask_limit)
    bid_depth = sum(float(p) * float(q) for p, q, *_ in bids if float(p) >= bid_limit)

    # Son seviye bandin disinda kaldiysa tahta bandi kapsamis demektir.
    ask_covers = float(asks[-1][0]) >= ask_limit
    bid_covers = float(bids[-1][0]) <= bid_limit

    return {
        "mid": mid,
        "spread_bps": (best_ask - best_bid) / mid * 10000,
        "bid_depth_usdt": bid_depth,
        "ask_depth_usdt": ask_depth,
        "book_truncated": not (ask_covers and bid_covers),
        "levels": (len(asks), len(bids)),
    }


def _demo(inst):
    """`python atk_client.py BTC-USDT` -- elle dogrulama icin."""
    t = get_ticker(inst)
    print(f"ticker  ok={t['ok']} latency={t['latency_ms']}ms error={t['error']}")
    if t["ok"]:
        d = t["data"]
        print(f"  last={d['last']} vol24h_usdt={float(d['volCcy24h']):,.0f}")

    b = get_orderbook(inst)
    print(f"tahta   ok={b['ok']} latency={b['latency_ms']}ms error={b['error']}")
    if b["ok"]:
        dw = depth_within(b["data"])
        if dw is None:
            print("  depth_within: tahta bos/bozuk")
        else:
            print(f"  mid={dw['mid']:.8g} spread={dw['spread_bps']:.2f}bps "
                  f"seviye={dw['levels']}")
            print(f"  bid_depth_2pct={dw['bid_depth_usdt']:,.0f} USDT  "
                  f"ask_depth_2pct={dw['ask_depth_usdt']:,.0f} USDT  "
                  f"book_truncated={dw['book_truncated']}")


if __name__ == "__main__":
    _demo(sys.argv[1] if len(sys.argv) > 1 else "BTC-USDT")
