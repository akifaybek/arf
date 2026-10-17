"""
scan_demo.py — pairs.json'daki 20 pariteyi ALIS tarafinda tarar ve demo icin
en uygun pariteleri isaretler. Parite basina TEK orderbook cagrisi yapilir
(ayni tahta hem metrik hem kayma hesabinda kullanilir).

Demo kosulu: 1000 <= maxSafeSize < 10000 USDT. Boyle bir paritede
  * 1.000 USDT'lik niyet kontratta GECER,
  * 10.000 USDT'lik niyet ExceedsSafeSize ile GERI DONER
    (suggestedParts = ceil(10000 / maxSafeSize)).

Kullanim: python scan_demo.py [--size-small 1000] [--size-big 10000]
"""

import argparse
import json
import math

import atk_client
import metrics

PAIRS_PATH = "pairs.json"

# --- VARSAYIM: demo adayi secim kurali -------------------------------------
# margin = iki sinira olan en kucuk pay (1k'ya ve 10k'ya). Buyuk olmasi,
# demo sirasinda tahta biraz oynasa bile sahnenin bozulmamasi demek.
# Risk esigi 5000 kabul edilerek (kontratta setRiskThreshold ile degisir)
# once riskScore <= 5000 olanlar, sonra margin'e gore siralanir.
DEMO_RISK_THRESHOLD = 5000


def scan(size_small=1000.0, size_big=10000.0, side="buy"):
    with open(PAIRS_PATH) as f:
        pairs = [r["inst"] for r in json.load(f)]

    rows = []
    for inst in pairs:
        book = atk_client.get_orderbook(inst)
        res = metrics.check_execution_core(inst, side, size_small, book_result=book)

        row = {"inst": inst, "status": res["status"], "riskScore": res["riskScore"],
               "maxSafeSize": res["maxSafeSize"], "slip_small": res["slippage_bps_at_size"],
               "slip_big": None, "fills_big": None, "spread_bps": None,
               "mid": None, "parts_big": None, "lower_bound": None,
               "memory_points": res["memory_points"]}

        if res["status"] != "INSUFFICIENT_DATA":
            comp = res["components"]
            row["spread_bps"] = comp["spread_bps"]
            row["lower_bound"] = comp["max_safe_is_lower_bound"]
            big = metrics.walk_book(book["data"], side, size_big)
            if big:
                row["mid"] = big["mid"]
                row["slip_big"] = big["slippage_bps"]
                row["fills_big"] = big["fills"]
            if row["maxSafeSize"] and row["maxSafeSize"] > 0:
                row["parts_big"] = math.ceil(size_big / row["maxSafeSize"])
        rows.append(row)

    return rows


def demo_margin(max_safe, size_small, size_big):
    """1k ve 10k sinirlarina olan en kucuk pay (1.0 = tam sinirda)."""
    if not max_safe or max_safe <= 0:
        return 0.0
    return min(max_safe / size_small, size_big / max_safe)


def main():
    ap = argparse.ArgumentParser(description="Arf demo taramasi (alis tarafi)")
    ap.add_argument("--size-small", type=float, default=1000.0)
    ap.add_argument("--size-big", type=float, default=10000.0)
    ap.add_argument("--side", default="buy", choices=["buy", "sell"])
    args = ap.parse_args()

    rows = scan(args.size_small, args.size_big, args.side)

    hdr = (f"{'#':>2} {'parite':<14} {'maxSafeSize':>12} {'kayma@1k':>9} "
           f"{'kayma@10k':>10} {'10k dolar':>9} {'risk':>5} {'parca':>5} "
           f"{'spread':>7} {'hafiza':>6}  durum")
    print(f"\nALIS tarafi, kayma esigi %1 (={metrics.DEFAULT_MAX_SLIP_BPS} bps), "
          f"kucuk={args.size_small:,.0f} buyuk={args.size_big:,.0f} USDT")
    print(hdr)
    print("-" * len(hdr))

    demo_rows = []
    for i, r in enumerate(rows, 1):
        mss = "-" if r["maxSafeSize"] is None else f"{r['maxSafeSize']:,.0f}"
        s1 = "-" if r["slip_small"] is None else f"{r['slip_small']:.1f}"
        s10 = "-" if r["slip_big"] is None else f"{r['slip_big']:.1f}"
        f10 = "-" if r["fills_big"] is None else ("evet" if r["fills_big"] else "HAYIR")
        rs = "-" if r["riskScore"] is None else f"{r['riskScore']}"
        pb = "-" if r["parts_big"] is None else f"{r['parts_big']}"
        sp = "-" if r["spread_bps"] is None else f"{r['spread_bps']:.1f}"
        lb = "*" if r["lower_bound"] else " "

        eligible = (
            r["maxSafeSize"] is not None
            and args.size_small <= r["maxSafeSize"] < args.size_big
            and r["status"] != "INSUFFICIENT_DATA"
        )
        mark = "  <= DEMO" if eligible else ""
        if eligible:
            demo_rows.append(r)

        print(f"{i:>2} {r['inst']:<14} {mss:>11}{lb} {s1:>9} {s10:>10} {f10:>9} "
              f"{rs:>5} {pb:>5} {sp:>7} {r['memory_points']:>6}  {r['status']}{mark}")

    print("\n* = maxSafeSize ALT SINIR (tahta kayma esigine ulasmadan bitti)")

    print(f"\nDemo kosulunu saglayan ({args.size_small:,.0f} <= maxSafeSize < "
          f"{args.size_big:,.0f}): {len(demo_rows)} parite")
    if not demo_rows:
        print("Aday yok: tahtalar ya cok derin ya cok sig. Demo tutarlarini degistir.")
        return

    # VARSAYIM: once risk esigini gecenler, sonra sinirlardan en uzak olan
    ranked = sorted(
        demo_rows,
        key=lambda r: (
            r["riskScore"] > DEMO_RISK_THRESHOLD,
            -demo_margin(r["maxSafeSize"], args.size_small, args.size_big),
            r["riskScore"],
        ),
    )
    print(f"\nEn iyi 2 aday (kural: riskScore <= {DEMO_RISK_THRESHOLD} olanlar once, "
          f"sonra sinirlara en buyuk pay):")
    for r in ranked[:2]:
        margin = demo_margin(r["maxSafeSize"], args.size_small, args.size_big)
        print(f"  {r['inst']:<14} maxSafeSize={r['maxSafeSize']:,.0f} USDT  "
              f"risk={r['riskScore']}  parca@10k={r['parts_big']}  "
              f"pay={margin:.2f}x  kayma@1k={r['slip_small']:.1f} bps  "
              f"kayma@10k={r['slip_big']:.1f} bps")


if __name__ == "__main__":
    main()
