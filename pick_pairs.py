"""
pick_pairs.py — gun boyu SABIT kalacak 20 USDT SPOT paritesini secer.

Secim deterministik: live -USDT pariteler, stablecoin ve kaldiracli tokenler
cikarilir, 24s USDT hacmine (volCcy24h) gore buyukten kucuge sirlanir ve
%40-%70 yuzdelik diliminden esit arayla 20 parite alinir (alt-orta dilim).
Her parite icin tahta bir kez cekilir, covers_band bayragi kaydedilir.
Sonuc pairs.json'a yazilir. Global siteye ASLA gecilmez.
"""

import json
from datetime import datetime, timezone

import atk_client

TARGET_COUNT = 20
PCT_LOW = 0.40
PCT_HIGH = 0.70
OUTPUT = "pairs.json"

# Baz varlik olarak haric tutulan stablecoin'ler (stable/stable paritesi istemiyoruz)
STABLE_BASES = {
    "USDC", "USDT", "DAI", "FDUSD", "TUSD", "PYUSD", "USDE", "USDP",
    "EURC", "EUROC", "BUSD", "GUSD", "LUSD", "SUSD", "USDD", "USDJ",
    "FRAX", "USD0", "USDS", "USDG", "RLUSD", "AEUR", "EURT", "XAUT",
}

# Kaldiracli token adlandirmalari (OKX'te 3L/3S/5L/5S/UP/DOWN sonekleri)
LEVERAGED_SUFFIXES = ("3L", "3S", "5L", "5S", "UP", "DOWN")


def is_leveraged(base):
    return any(base.endswith(s) for s in LEVERAGED_SUFFIXES)


def pick():
    # 1) live -USDT SPOT pariteleri
    inst = atk_client.get_instruments_spot()
    if not inst["ok"]:
        raise SystemExit(f"instruments cekilemedi: {inst['error']}")
    live = {
        x["instId"]
        for x in inst["data"]
        if x.get("state") == "live" and x.get("quoteCcy") == "USDT"
    }
    print(f"live -USDT SPOT parite: {len(live)}")

    tick = atk_client.get_tickers_spot()
    if not tick["ok"]:
        raise SystemExit(f"tickers cekilemedi: {tick['error']}")

    rows = []
    for t in tick["data"]:
        inst_id = t["instId"]
        if inst_id not in live:
            continue
        base = inst_id.split("-")[0]
        if base in STABLE_BASES or is_leveraged(base):
            continue
        rows.append({"inst": inst_id, "vol24h_usdt": float(t["volCcy24h"])})

    print(f"filtreden gecen (stable + kaldiracli cikarildi): {len(rows)}")

    # 3) hacme gore buyukten kucuge sirala, %40-%70 diliminden esit arayla sec
    rows.sort(key=lambda r: -r["vol24h_usdt"])
    n = len(rows)
    lo, hi = int(n * PCT_LOW), int(n * PCT_HIGH)
    band = rows[lo:hi]
    print(f"%{int(PCT_LOW*100)}-%{int(PCT_HIGH*100)} dilimi: {len(band)} parite "
          f"(sira {lo}..{hi})")

    if len(band) <= TARGET_COUNT:
        chosen = band
        print(f"UYARI: dilimde yalnizca {len(band)} parite var, hepsi alindi "
              f"({TARGET_COUNT} hedefin altinda). Global siteye GECILMEDI.")
    else:
        step = (len(band) - 1) / (TARGET_COUNT - 1)
        chosen = [band[round(i * step)] for i in range(TARGET_COUNT)]

    # 4) her parite icin tahta bir kez: covers_band bayragi
    picked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for r in chosen:
        ob = atk_client.get_orderbook(r["inst"])
        dw = atk_client.depth_within(ob["data"]) if ob["ok"] else None
        if dw is None:
            r.update(covers_band=None, spread_bps=None,
                     bid_depth_2pct_usdt=None, ask_depth_2pct_usdt=None,
                     note=ob["error"] or "tahta okunamadi")
        else:
            r.update(covers_band=dw["covers_band"],
                     spread_bps=round(dw["spread_bps"], 3),
                     bid_depth_2pct_usdt=round(dw["bid_depth_usdt"], 2),
                     ask_depth_2pct_usdt=round(dw["ask_depth_usdt"], 2),
                     note=None)
        r["picked_at"] = picked_at

    with open(OUTPUT, "w") as f:
        json.dump(chosen, f, indent=2)

    # 6) tabloyu ekrana bas
    print(f"\n{'#':>2} {'parite':<14} {'vol24h_usdt':>14} {'spread_bps':>10} "
          f"{'bid_2%':>12} {'ask_2%':>12}  covers_band")
    for i, r in enumerate(chosen, 1):
        sp = "-" if r["spread_bps"] is None else f"{r['spread_bps']:.2f}"
        bd = "-" if r["bid_depth_2pct_usdt"] is None else f"{r['bid_depth_2pct_usdt']:,.0f}"
        ad = "-" if r["ask_depth_2pct_usdt"] is None else f"{r['ask_depth_2pct_usdt']:,.0f}"
        print(f"{i:>2} {r['inst']:<14} {r['vol24h_usdt']:>14,.0f} {sp:>10} "
              f"{bd:>12} {ad:>12}  {r['covers_band']}")

    shallow = [r["inst"] for r in chosen if r["covers_band"] is False]
    print(f"\ncovers_band=False (tahta +-%2'ye ulasmiyor, derinlik ALT SINIR): "
          f"{shallow if shallow else 'yok'}")
    print(f"{len(chosen)} parite -> {OUTPUT} ({picked_at})")


if __name__ == "__main__":
    pick()
