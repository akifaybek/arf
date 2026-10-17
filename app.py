"""
app.py — Arf'in tek ekranli demo arayuzu (Streamlit).

BU DOSYADA IS MANTIGI YOK: butun olcumler ve kararlar
  * agent.run_check  (deterministik metrikler + LLM planlayici)
  * chain.simulate_only / chain.execute_intent / chain.sign_attestation_with_trader
fonksiyonlarindan gelir. Burada yalnizca sahne secimi ve gosterim var.

Kullanim: streamlit run app.py
"""

import os
import time

import streamlit as st

import agent
import atk_client
import chain

# .env MUTLAK yoldan yuklenir. Streamlit scripti exec ile kosturdugu icin
# dotenv'in cagri yiginina bakan otomatik arayisi bos donebiliyor; o zaman
# CONTRACT_ADDRESS bos kalip to_checksum_address("") "Unknown format ''"
# hatasi veriyordu (sahne 3 "Kontrat cevabi" kutusunda gorulen hata).
chain.load_env()

PAGE_TITLE = "Arf — işlem öncesi icra ve likidite kalkanı"
DEFAULT_SYMBOL = "ZBCN-USDT"
SIDE = "buy"

SCENES = {
    1: {"label": "Sahne 1: 1.000 USDT", "size": 1000.0, "feed_down": False,
        "aciklama": "Tutar güvenli tutarın içinde"},
    2: {"label": "Sahne 2: 10.000 USDT", "size": 10000.0, "feed_down": False,
        "aciklama": "Tutar güvenli tutarı aşıyor"},
    3: {"label": "Sahne 3: veri kesintisi (SİMÜLASYON)", "size": 1000.0,
        "feed_down": True, "aciklama": "Veri kesilir → imza yok → zincir reddeder"},
}

# Sahne 3'te trader'in UYDURDUGU skor (demo.py ile ayni degerler)
FAKE_RISK_SCORE = 0
FAKE_MAX_SAFE_USDT = 1_000_000.0

DECISION_STYLE = {
    "ONAY": ("#1a7f37", "ONAY — emir bu tahtada güvenli"),
    "BOL": ("#9a6700", "BÖL — tutar güvenli tutarı aşıyor"),
    "RED": ("#b42318", "RED — risk skoru eşiğin üzerinde"),
    "VERI_YETERSIZ": ("#b42318", "VERİ YETERSİZ — imza yok (fail-closed)"),
}

EXPLORER = "https://explorer-test.avax.network/c-chain/tx/{}"

# Zincirde GERCEKTEN dogrulanmis kanitlar (STATUS.md'den; sabit liste).
# AlreadyUsed ve StaleScore yalnizca eth_call ile gosterildi, tx YOK —
# oldugu gibi yaziliyor, uydurma hash konmuyor.
ONCHAIN_PROOFS = [
    ("IntentApproved (fuji_smoke)",
     "0x7bef94f297de147acf74dce1139eca659e982e2ae51a51f013b2d89071ba5173"),
    ("IntentApproved (agent, 1.000 USDT)",
     "0xa5798d597f00a46e36c93a48f4423d46a18faf082d2006562140e4bd5eaacbbe"),
    ("ExceedsSafeSize (fuji_smoke, 10 parça)",
     "0x175eaee2cdce982ad58988c3d73bb08944bf3d62fbcf91dcab1a973b8f4bf0e5"),
    ("ExceedsSafeSize (agent, 3 parça)",
     "0x80aeb84999c64df29bec84dccedd6addb3b1c22adac4e69abd74fc29eb2667a6"),
    ("BadSigner (fail-closed sahnesi)",
     "0x0b05e13fa25cb379d62f715820266a32db08250b40b19e2474940b5311ede98e"),
]
SIMULATED_ONLY = [
    ("AlreadyUsed", "aynı imza ikinci kez — eth_call ile doğrulandı, tx gönderilmedi"),
    ("StaleScore", "skor 400 sn eski — eth_call ile doğrulandı, tx gönderilmedi"),
]


# =============================================================================
# Sahne kosumu (yalnizca mevcut fonksiyonlari cagirir)
# =============================================================================

def run_scene(scene, symbol, use_llm, send):
    cfg = SCENES[scene]
    out = {"scene": scene, "symbol": symbol, "size": cfg["size"], "res": None,
           "chain": None, "chain_label": None, "trader_signer": None,
           "error": None, "seconds": 0.0}
    t0 = time.time()

    if cfg["feed_down"]:
        os.environ[atk_client.FEED_DOWN_ENV] = "1"
    try:
        res = agent.run_check(symbol, SIDE, cfg["size"], use_llm=use_llm)
        out["res"] = res

        if scene == 3:
            # Imza alamayan trader uydurma skoru KENDI anahtariyla imzalar
            att = chain.sign_attestation_with_trader(
                symbol, SIDE, FAKE_RISK_SCORE, FAKE_MAX_SAFE_USDT, int(time.time()))
            out["trader_signer"] = att["signer"]
            out["chain_label"] = "Trader'in kendi imzasiyla gonderdigi niyet"
            out["chain"] = (chain.execute_intent(symbol, SIDE, cfg["size"], att,
                                                 force_onchain=True, verbose=False)
                            if send else
                            chain.simulate_only(symbol, SIDE, cfg["size"], att,
                                                verbose=False))
        elif res["signed_attestation"] is not None:
            att = res["signed_attestation"]
            out["chain_label"] = "Imzali niyetin kontrat cevabi"
            out["chain"] = (chain.execute_intent(symbol, SIDE, cfg["size"], att,
                                                 force_onchain=(res["decision"] != "ONAY"),
                                                 verbose=False)
                            if send else
                            chain.simulate_only(symbol, SIDE, cfg["size"], att,
                                                verbose=False))
    except Exception as exc:  # ekran cokmesin
        out["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if cfg["feed_down"]:
            os.environ.pop(atk_client.FEED_DOWN_ENV, None)
        out["seconds"] = time.time() - t0
    return out


def decision_source(res):
    if res.get("decision") != res.get("deterministic_decision"):
        return "LLM (daha muhafazakar)"
    return "deterministik kural"


# =============================================================================
# Gosterim
# =============================================================================

def render_badge(decision):
    color, text = DECISION_STYLE.get(decision, ("#444", decision or "-"))
    st.markdown(
        f"<div style='background:{color};color:#fff;padding:18px;border-radius:10px;"
        f"text-align:center;font-size:24px;font-weight:700;margin:6px 0'>{text}</div>",
        unsafe_allow_html=True)


# Veri kesintisi sahnesinde bu araclar canli tahtaya DEGIL hafizaya bakiyor;
# karar izinde bunu acikca etiketliyoruz (karar mantigi degismiyor).
MEMORY_TOOLS = ("scan_market", "compute_metric")


def render_left(out):
    res = out["res"]
    feed_down = SCENES[out["scene"]]["feed_down"]
    st.subheader("Karar izi")
    if res is None:
        st.info("Sahne seçilmedi veya koşu tamamlanamadı.")
        return

    used, budget = res["tool_calls_used"], agent.TOOL_BUDGET
    st.caption(f"Araç bütçesi: {used}/{budget}  ·  mod: {(res['llm'] or {}).get('mode')}")
    st.progress(min(used / budget, 1.0))

    for e in res["trace"]:
        if e["tool"]:
            etiket = ""
            if feed_down and e["tool"] in MEMORY_TOOLS:
                etiket = "  ·  :orange[hafıza (canlı tahta YOK)]"
            st.markdown(f"**{e['i']}. `{e['tool']}`** · {e['ms']} ms{etiket}")
            st.caption(e["summary"])
        else:
            st.markdown(f"{e['i']}. _{e['summary']}_")

    lf = res.get("llm_final")
    st.divider()
    st.subheader("LLM okuması")
    if lf:
        st.markdown(f"**Hipotez:** {lf.get('hipotez')}")
        for k in (lf.get("kanit") or []):
            st.markdown(f"- {k}")
        st.markdown(f"**Güven:** `{lf.get('guven')}`  ·  "
                    f"**Önerisi:** `{lf.get('karar_onerisi')}`")
        st.markdown(f"**Gerekçe:** {lf.get('gerekce')}")
    else:
        st.info("LLM yapısal çıktı vermedi — karar deterministik kuralla verildi.")

    llm = res.get("llm") or {}
    if llm.get("provider"):
        cost = f" · ~${llm['cost_usd']:.6f}" if llm.get("cost_usd") else ""
        st.caption(f"{llm.get('provider')}/{llm.get('model')} · "
                   f"{llm.get('requests')} istek · {llm.get('ms')} ms{cost}")
    st.caption(f"Karar kaynağı: **{decision_source(res)}**")


def render_middle(out):
    res = out["res"]
    st.subheader("Metrikler")
    if res is None:
        st.info("Ölçüm yok.")
        return

    render_badge(res["decision"])

    c1, c2 = st.columns(2)
    rs = res["riskScore"]
    c1.metric("riskScore (yüksek = riskli)",
              "-" if rs is None else f"{rs}",
              f"eşik {res['riskThreshold']}")
    c2.metric("maxSafeSize",
              "-" if res["maxSafeSize"] is None else f"{res['maxSafeSize']:,.0f} USDT")
    c3, c4 = st.columns(2)
    slip = res["slippage_bps_at_size"]
    c3.metric(f"icra maliyeti @ {out['size']:,.0f} USDT",
              "-" if slip is None else f"{slip:.1f} bps")
    age = res["data_age_s"]
    # Kisa metin: "veri yaşı" basligi dar sutunda kesilmesin
    c4.metric("veri yaşı",
              "veri yok" if res["status"] == "INSUFFICIENT_DATA" else f"{age:.2f} sn")

    st.caption(f"durum: `{res['status']}`  ·  hafıza noktası: "
               f"{res.get('memory_points', '-')}  ·  süre: {out['seconds']:.1f} sn")

    if res["split_suggestion"]:
        st.warning(f"**Bölme önerisi:** {res['split_suggestion']}")
    if res["decision"] == "VERI_YETERSIZ":
        st.error(f"İmza üretilmedi — {res['reason']}")
    elif res["signed_attestation"]:
        st.success(f"İmzalı skor üretildi · digest `{res['signed_attestation']['digest']}`")


def render_right(out):
    st.subheader("Kontrat cevabı")
    ch = out["chain"]
    if out["error"]:
        st.error(f"Koşu hatası: {out['error']}")
    if ch is None:
        if out["res"] is not None and out["res"]["signed_attestation"] is None \
                and out["scene"] != 3:
            st.info("İmza yok — kontrata hiçbir şey gönderilmedi (fail-closed).")
        else:
            st.info("Kontrat cevabı yok.")
    else:
        st.caption(out["chain_label"])
        if out.get("trader_signer"):
            st.caption(f"İmzalayan: `{out['trader_signer']}` (trader — oracle DEĞİL)")
        if ch["status"] == "CONFIRMED":
            st.success(f"**{ch['status']}** · IntentApproved")
            if ch.get("event"):
                st.json(ch["event"], expanded=False)
        else:
            st.error(f"**{ch['status']}** · {ch['error_text']}")
        meta = []
        if ch.get("gas_used"):
            meta.append(f"gas {ch['gas_used']:,}")
        if ch.get("confirm_ms"):
            meta.append(f"onay {ch['confirm_ms']} ms")
        if meta:
            st.caption(" · ".join(meta))
        if ch.get("sent") and ch.get("explorer"):
            st.markdown(f"[Explorer'da gör]({ch['explorer']})")
        elif not ch.get("sent"):
            st.caption("eth_call simülasyonu — zincire hiçbir şey yazılmadı")

    st.divider()
    st.subheader("Zincirde doğrulanmış kanıtlar")
    for label, tx in ONCHAIN_PROOFS:
        st.markdown(f"- {label}: [{tx[:18]}…]({EXPLORER.format(tx)})")
    st.caption("Yalnızca eth_call ile doğrulanan (tx gönderilmeyen) kontroller:")
    for label, note in SIMULATED_ONLY:
        st.caption(f"· {label} — {note}")


# =============================================================================
# Sayfa
# =============================================================================

def main():
    st.set_page_config(page_title="Arf", layout="wide")
    st.title(PAGE_TITLE)
    st.caption("Agent emir vermeden önce: tahta bu emri kaldırır mı, veri taze mi? "
               "Cevap imzalı bir risk skoru + maxSafeSize olarak Avalanche Fuji'deki "
               "devre kesiciye gider.")

    with st.sidebar:
        st.header("Ayarlar")
        symbol = st.text_input("Parite", value=DEFAULT_SYMBOL).strip().upper()
        use_llm = st.checkbox("LLM kullan", value=True,
                              help="Kapatılırsa aynı araçlar sabit sırayla "
                                   "çalışır (deterministik plan).")
        send = st.checkbox("Zincire gönder", value=False,
                           help="Kapalıyken yalnızca eth_call yapılır, "
                                "zincire hiçbir şey yazılmaz.")
        if send:
            st.warning("Zincire GERÇEK tx gönderilecek.")
        st.divider()
        st.caption(f"Kontrat: `{chain.contract_address()}` "
                   "(Avalanche Fuji, chainId 43113)")

    cols = st.columns(3)
    active = st.session_state.get("active_scene")
    for i, (scene, cfg) in enumerate(SCENES.items()):
        # Tiklanan sahnenin butonu vurgulanir (onceki halde hep Sahne 1 idi)
        if cols[i].button(cfg["label"], use_container_width=True,
                          type="primary" if scene == active else "secondary"):
            st.session_state["active_scene"] = scene
            with st.spinner(f"{cfg['label']} koşuluyor…"):
                st.session_state["out"] = run_scene(scene, symbol, use_llm, send)
            st.rerun()
        cols[i].caption(cfg["aciklama"])

    out = st.session_state.get("out")
    if out is None:
        st.info("Bir sahne seçin.")
        return

    if SCENES[out["scene"]]["feed_down"]:
        st.markdown(
            "<div style='background:#b42318;color:#fff;padding:14px;border-radius:8px;"
            "text-align:center;font-size:20px;font-weight:700;margin:10px 0'>"
            "SİMÜLASYON: veri kesintisi + yetkisiz imza</div>",
            unsafe_allow_html=True)
        st.caption("ARF_FEED_DOWN=1 — ATK CLI hiç çağrılmıyor; besleme kopmuş gibi "
                   "davranılıyor.")

    left, middle, right = st.columns([1.1, 1.0, 1.0])
    with left:
        render_left(out)
    with middle:
        render_middle(out)
    with right:
        render_right(out)


if __name__ == "__main__":
    # Streamlit scripti __main__ olarak kosar; bu kalip ayni dosyanin
    # testlerde (streamlit calismazken) import edilebilmesini saglar.
    main()
