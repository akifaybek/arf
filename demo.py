"""
demo.py — Arf'in uc sahnesi, tek komutla.

    python demo.py 1            ONAY      — 1.000 USDT guvenli tutarin icinde
    python demo.py 2            BOL       — 10.000 USDT guvenli tutari asiyor
                                            (+ kontratin verecegi revert on izlemesi)
    python demo.py 3            FAIL-CLOSED — veri kesintisi SIMULASYONU:
                                            imza yok; trader kendi imzasiyla
                                            zorlarsa kontrat BadSigner ile reddeder

Bayraklar:
    --send       zincire GERCEK tx gonder (varsayilan: yalnizca eth_call)
    --no-llm     LLM'i atla, deterministik plan (sahnede kota/ag sorunu olursa)
    --symbol/--size  sahne parametrelerini degistir

Varsayilan olarak zincire hicbir sey yazilmaz: revert sebepleri eth_call
simulasyonuyla gosterilir.
"""

import argparse
import math
import os
import sys
import time

SYMBOL = "ZBCN-USDT"
SIDE = "buy"
SIZE_OK = 1000.0
SIZE_BIG = 10000.0

# Sahne 3'te trader'in UYDURDUGU skor (gercek olcum degil, simulasyon)
FAKE_RISK_SCORE = 0
FAKE_MAX_SAFE_USDT = 1_000_000.0

# --- renkler (rich kurulu degil; duz ANSI) ---------------------------------
USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def c(text, code):
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text


def bold(t):
    return c(t, "1")


def green(t):
    return c(t, "1;32")


def red(t):
    return c(t, "1;31")


def yellow(t):
    return c(t, "1;33")


def cyan(t):
    return c(t, "36")


def dim(t):
    return c(t, "2")


WIDTH = 74


def banner(title, color=cyan):
    print()
    print(color("=" * WIDTH))
    print(color(f"  {title}"))
    print(color("=" * WIDTH))


def kv(label, value, color=None):
    text = f"  {label:<20}: {value}"
    print(color(text) if color else text)


def sim_label(text):
    """Veri kesintisi senaryosunu acikca SIMULASYON olarak etiketler."""
    line = "!" * WIDTH
    print()
    print(yellow(line))
    for part in text.split("\n"):
        print(yellow(f"!!  {part.center(WIDTH - 8)}  !!"))
    print(yellow(line))


DECISION_COLOR = {"ONAY": green, "BOL": yellow, "RED": red, "VERI_YETERSIZ": red}


def print_trace(res, limit=12):
    mode = (res["llm"] or {}).get("mode")
    print(f"\n  {bold('KARAR IZI')} "
          f"({res['tool_calls_used']} arac cagrisi, mod: {mode})")
    for e in res["trace"][:limit]:
        if e["tool"]:
            print(f"    {e['i']:>2}. {cyan(e['tool'])} {dim(str(e['ms']) + ' ms')}")
        else:
            print(f"    {e['i']:>2}. {dim('[not] ' + e['summary'])}")


def print_metrics(res):
    print(f"\n  {bold('OLCUM (deterministik)')}")
    if res["status"] == "INSUFFICIENT_DATA":
        # Cagri aninda basarisiz oldugu icin "yas" anlamsiz: veri YOK
        kv("durum", red(f"{res['status']}  (olculebilir veri yok)"))
    else:
        kv("durum", f"{res['status']}  (veri yasi {res['data_age_s']} sn)")
    if res["riskScore"] is not None:
        kv("riskScore", f"{res['riskScore']} / esik {res['riskThreshold']}")
    if res["maxSafeSize"] is not None:
        kv("maxSafeSize", f"{res['maxSafeSize']:,.2f} USDT")
    if res["slippage_bps_at_size"] is not None:
        kv("kayma @ tutar", f"{res['slippage_bps_at_size']:.2f} bps")


def print_llm(res):
    lf = res.get("llm_final")
    llm = res.get("llm") or {}
    if lf:
        print(f"\n  {bold('LLM OKUMASI')} (guven: {lf.get('guven')}, "
              f"oneri: {lf.get('karar_onerisi')})")
        print(f"    hipotez: {lf.get('hipotez')}")
        for k in (lf.get("kanit") or [])[:4]:
            print(f"      - {k}")
    if llm.get("provider"):
        cost = f", ~${llm['cost_usd']:.6f}" if llm.get("cost_usd") else ""
        line = (f"{llm.get('provider')}/{llm.get('model')}, "
                f"{llm.get('requests')} istek{cost}")
        print(f"    {dim(line)}")


def summary(scene, decision, source, seconds, tx_link=None):
    parts = [f"sahne {scene}", f"karar={decision}", f"karar_kaynagi={source}",
             f"sure={seconds:.1f} sn"]
    if tx_link:
        parts.append(f"tx={tx_link}")
    print()
    print(bold("  OZET: ") + "  ".join(parts))


def decision_source(res):
    """Karari kim belirledi: deterministik kural mi, LLM muhafazakarligi mi."""
    det = res.get("deterministic_decision")
    final = res.get("decision")
    if final != det:
        return "LLM (daha muhafazakar)"
    return "deterministik kural"


# =============================================================================
# Sahne 1 — ONAY
# =============================================================================

def scene1(args):
    import agent
    t0 = time.time()
    banner("SAHNE 1 — Guvenli emir: tahta bu tutari kaldiriyor", cyan)
    print(f"  Niyet: {bold(f'{args.symbol} {SIDE} {args.size:,.0f} USDT')}")

    res = agent.run_check(args.symbol, SIDE, args.size, use_llm=not args.no_llm)
    print_trace(res)
    print_metrics(res)
    print_llm(res)

    col = DECISION_COLOR.get(res["decision"], bold)
    print(f"\n  {bold('KARAR')}: {col(res['decision'])}  "
          f"{dim('(kaynak: ' + decision_source(res) + ')')}")
    kv("imza", "VAR  " + res["signed_attestation"]["digest"][:26] + "…"
       if res["signed_attestation"] else "YOK", green if res["signed_attestation"] else red)

    tx_link = None
    if args.send and res["signed_attestation"]:
        tx_link = send_intent(res, force_onchain=False)
    summary(1, res["decision"], decision_source(res), time.time() - t0, tx_link)
    return res


# =============================================================================
# Sahne 2 — BOL + revert on izlemesi
# =============================================================================

def scene2(args):
    import agent
    import chain
    t0 = time.time()
    banner("SAHNE 2 — Buyuk emir: guvenli tutar asiliyor", yellow)
    print(f"  Niyet: {bold(f'{args.symbol} {SIDE} {args.big:,.0f} USDT')}")

    res = agent.run_check(args.symbol, SIDE, args.big, use_llm=not args.no_llm)
    print_trace(res)
    print_metrics(res)
    print_llm(res)

    col = DECISION_COLOR.get(res["decision"], bold)
    print(f"\n  {bold('KARAR')}: {col(res['decision'])}  "
          f"{dim('(kaynak: ' + decision_source(res) + ')')}")
    if res["split_suggestion"]:
        kv("bolme onerisi", yellow(res["split_suggestion"]))

    att = res["signed_attestation"]
    tx_link = None
    if att is None:
        kv("imza", red("YOK"))
    else:
        kv("imza", "VAR  " + att["digest"][:26] + "…")
        print(f"\n  {bold('KONTRAT ON IZLEMESI')} "
              f"{dim('(eth_call, zincire yazilmaz)')}")
        try:
            out = chain.simulate_only(res["symbol"], res["side"], res["size_usdt"],
                                      att, verbose=False)
            if out["status"] == "SIMULATED_REVERT":
                kv("zincir cevabi", red(out["error_text"]))
                err = (out.get("error") or {}).get("args") or {}
                if "suggestedParts" in err:
                    kv("kontratin onerisi", yellow(
                        f"{err['suggestedParts']} parcaya bol "
                        f"(amount {err['amount']}, maxSafeSize {err['maxSafeSize']}, "
                        f"birim USDT x 1e6)"))
            else:
                kv("zincir cevabi", green("GECER (revert yok)"))
        except Exception as exc:
            kv("zincir cevabi", red(f"baglanti hatasi: {type(exc).__name__}: {exc}"))

        if args.send:
            tx_link = send_intent(res, force_onchain=True)

    summary(2, res["decision"], decision_source(res), time.time() - t0, tx_link)
    return res


# =============================================================================
# Sahne 3 — fail-closed + yetkisiz imza
# =============================================================================

def scene3(args):
    import atk_client
    import chain
    t0 = time.time()
    banner("SAHNE 3 — Veri kesintisi: fail-closed", red)
    sim_label("SIMULASYON: veri kesintisi + yetkisiz imza\n"
              "ARF_FEED_DOWN=1 — ATK CLI hic cagrilmiyor")

    os.environ[atk_client.FEED_DOWN_ENV] = "1"
    try:
        import agent
        print(f"\n  Niyet: {bold(f'{args.symbol} {SIDE} {args.size:,.0f} USDT')}")
        res = agent.run_check(args.symbol, SIDE, args.size, use_llm=not args.no_llm)
        print_trace(res)
        print_metrics(res)

        col = DECISION_COLOR.get(res["decision"], bold)
        print(f"\n  {bold('KARAR')}: {col(res['decision'])}  "
              f"{dim('(kaynak: ' + decision_source(res) + ')')}")
        kv("sebep", res["reason"])
        kv("imza", red("YOK — veri bayat/yok, oracle imzalamiyor")
           if res["signed_attestation"] is None else green("VAR"))

        # --- trader yine de gondermeye calisiyor ---------------------------
        print(f"\n  {bold('AMA TRADER YINE DE GONDERIYOR')}")
        print(f"  {dim('Imza alamayan trader, uydurma bir skoru KENDI anahtariyla')}")
        print(f"  {dim('imzalayip kontrata gonderiyor (riskScore 0, maxSafeSize 1M USDT).')}")

        trader_att = chain.sign_attestation_with_trader(
            args.symbol, SIDE, FAKE_RISK_SCORE, FAKE_MAX_SAFE_USDT, int(time.time())
        )
        kv("imzalayan", trader_att["signer"] + dim("  (trader, oracle DEGIL)"))
        kv("uydurma skor", f"riskScore={FAKE_RISK_SCORE}, "
                           f"maxSafeSize={FAKE_MAX_SAFE_USDT:,.0f} USDT")

        tx_link = None
        if args.send:
            print(f"\n  {bold('GERCEK TX GONDERILIYOR')} "
                  f"{dim('(sabit gas, revert zincirde gorunsun)')}")
            out = chain.execute_intent(args.symbol, SIDE, args.size, trader_att,
                                       force_onchain=True, verbose=False)
            kv("zincir cevabi", red(out["error_text"] or out["status"]))
            kv("durum", out["status"])
            if out["sent"]:
                kv("gas", f"{out['gas_used']:,}  (onay {out['confirm_ms']} ms)")
                kv("tx", out["explorer"])
                tx_link = out["explorer"]
        else:
            print(f"\n  {bold('KONTRAT ON IZLEMESI')} {dim('(eth_call, zincire yazilmaz)')}")
            out = chain.simulate_only(args.symbol, SIDE, args.size, trader_att,
                                      verbose=False)
            kv("zincir cevabi", red(out["error_text"]))

        print(f"\n  {green('SONUC')}: veri bozulunca imza uretilmedi; imzasiz/yetkisiz "
              f"niyet\n          zincirde {red('reddedildi')} — fail-closed.")
        summary(3, res["decision"], decision_source(res), time.time() - t0, tx_link)
        return res
    finally:
        os.environ.pop(atk_client.FEED_DOWN_ENV, None)


# =============================================================================
# Ortak: gercek tx
# =============================================================================

def send_intent(res, force_onchain):
    import chain
    att = res["signed_attestation"]
    print(f"\n  {bold('GERCEK TX GONDERILIYOR')}: executeIntent "
          f"{res['symbol']} {res['side']} {res['size_usdt']:,.0f} USDT")
    out = chain.execute_intent(res["symbol"], res["side"], res["size_usdt"], att,
                               force_onchain=force_onchain, verbose=False)
    kv("durum", green(out["status"]) if out["status"] == "CONFIRMED"
       else red(out["status"]))
    kv("zincir cevabi", out["error_text"] or str(out.get("event")))
    if out["sent"]:
        kv("gas", f"{out['gas_used']:,}  (onay {out['confirm_ms']} ms)")
        kv("tx", out["explorer"])
        return out["explorer"]
    return None


def main():
    ap = argparse.ArgumentParser(description="Arf demo sahneleri")
    ap.add_argument("scene", type=int, choices=[1, 2, 3])
    ap.add_argument("--send", action="store_true",
                    help="zincire GERCEK tx gonder (varsayilan: yalnizca eth_call)")
    ap.add_argument("--no-llm", action="store_true", help="deterministik plan")
    ap.add_argument("--symbol", default=SYMBOL)
    ap.add_argument("--size", type=float, default=SIZE_OK)
    ap.add_argument("--big", type=float, default=SIZE_BIG)
    args = ap.parse_args()

    {1: scene1, 2: scene2, 3: scene3}[args.scene](args)


if __name__ == "__main__":
    main()
