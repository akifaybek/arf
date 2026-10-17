"""
fuji_smoke.py — Fuji'deki RiskCircuitBreaker'in uctan uca kanit senaryosu.

Sira:
  0) Zincir durumu beklenenle karsilastirilir (uyusmazsa DURUR).
     Canli digest karsilastirmasi: kontratin attestationDigest'i ile
     signer.py'nin ayni girdiler icin urettigi digest YAN YANA basilir.
  a) GERCEK TX  — riskScore 3000, maxSafeSize 1000 USDT, amount 800
                  -> IntentApproved bekleniyor
  b) eth_call   — ayni imza ikinci kez        -> AlreadyUsed
  c) GERCEK TX  — yeni imza, amount 10000     -> ExceedsSafeSize(.., .., 10)
                  (force_onchain: revert eden tx explorer'da gorunur)
  d) eth_call   — timestamp = simdi - 400     -> StaleScore

Toplam 2 tx gonderilir (a ve c). b ve d yalnizca eth_call'dir.
Ozel anahtarlar .env'den okunur; hicbir yere yazilmaz.

Kullanim: python fuji_smoke.py
"""

import time

import chain

SYMBOL = "ZBCN-USDT"
SIDE = "buy"

RISK_SCORE = 3000
MAX_SAFE_USDT = 1000.0
AMOUNT_OK = 800.0
AMOUNT_TOO_BIG = 10000.0
STALE_AGE_S = 400  # MAX_AGE 300'un otesi


def line(title):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def main():
    results = []

    line("0) ZINCIR DURUMU")
    state, w3, url = chain.read_state(strict=True)

    line("0b) CANLI DIGEST BYTE UYUMU (Python <-> Fuji)")
    ts = int(time.time())
    att = chain.sign_attestation_with_oracle(
        SYMBOL, SIDE, RISK_SCORE, MAX_SAFE_USDT, ts, state["contract"]
    )
    onchain = chain.onchain_digest(
        SYMBOL, SIDE, RISK_SCORE, MAX_SAFE_USDT, ts, w3=w3, url=url
    )
    print(f"girdiler : symbol={SYMBOL} side={SIDE} riskScore={RISK_SCORE} "
          f"maxSafeSize={att['maxSafeSize']} (1e6 birim) timestamp={ts}")
    print(f"kontrat  : {att['contract']}  chainId={att['chainId']}")
    print(f"Python   : {att['digest']}")
    print(f"Fuji     : {onchain}")
    match = att["digest"].lower() == onchain.lower()
    print(f"eslesme  : {'EVET' if match else 'HAYIR'}")
    if not match:
        raise SystemExit("digest eslesmedi -> tx gonderilmedi")

    # --- a) mutlu yol, gercek tx -------------------------------------------
    line(f"a) GERCEK TX — executeIntent amount={AMOUNT_OK:,.0f} USDT "
         f"(maxSafeSize {MAX_SAFE_USDT:,.0f}) -> IntentApproved bekleniyor")
    res_a = chain.execute_intent(SYMBOL, SIDE, AMOUNT_OK, att, w3=w3, url=url)
    results.append(("a) IntentApproved", res_a))

    # --- b) ayni imza tekrar, sadece eth_call ------------------------------
    line("b) eth_call — ayni imza ikinci kez -> AlreadyUsed bekleniyor (tx YOK)")
    res_b = chain.simulate_only(SYMBOL, SIDE, AMOUNT_OK, att, w3=w3, url=url)
    results.append(("b) AlreadyUsed", res_b))

    # --- c) guvenli tutar asimi, zincire yazilan revert --------------------
    line(f"c) GERCEK TX — yeni imza, amount={AMOUNT_TOO_BIG:,.0f} USDT -> "
         f"ExceedsSafeSize bekleniyor (force_onchain)")
    ts_c = int(time.time())
    att_c = chain.sign_attestation_with_oracle(
        SYMBOL, SIDE, RISK_SCORE, MAX_SAFE_USDT, ts_c, state["contract"]
    )
    res_c = chain.execute_intent(SYMBOL, SIDE, AMOUNT_TOO_BIG, att_c,
                                 w3=w3, url=url, force_onchain=True)
    results.append(("c) ExceedsSafeSize", res_c))

    # --- d) bayat skor, sadece eth_call ------------------------------------
    line(f"d) eth_call — timestamp = simdi - {STALE_AGE_S} sn -> StaleScore "
         f"bekleniyor (tx YOK)")
    ts_d = int(time.time()) - STALE_AGE_S
    att_d = chain.sign_attestation_with_oracle(
        SYMBOL, SIDE, RISK_SCORE, MAX_SAFE_USDT, ts_d, state["contract"]
    )
    res_d = chain.simulate_only(SYMBOL, SIDE, AMOUNT_OK, att_d, w3=w3, url=url)
    results.append(("d) StaleScore", res_d))

    # --- ozet ---------------------------------------------------------------
    line("OZET")
    print(f"{'senaryo':<22} {'durum':<18} {'gas':>8} {'onay ms':>8}  sonuc")
    for name, r in results:
        gas = "-" if r["gas_used"] is None else f"{r['gas_used']:,}"
        ms = "-" if r["confirm_ms"] is None else f"{r['confirm_ms']}"
        if r["status"] == "CONFIRMED":
            outcome = f"IntentApproved amount={r['event']['amount']}" if r["event"] else "onaylandi"
        else:
            outcome = r["error_text"] or "-"
        print(f"{name:<22} {r['status']:<18} {gas:>8} {ms:>8}  {outcome}")

    print("\nExplorer linkleri (zincire yazilan tx'ler):")
    for name, r in results:
        if r["sent"]:
            print(f"  {name}: {r['explorer']}")


if __name__ == "__main__":
    main()
