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
import json
import re
from html import escape
from pathlib import Path

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

# Fuji islem kanitlari: docs/validation.md (sabit liste).
# Besinin de tx hash'i gercek; uydurma hash YOK.
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
    ("AlreadyUsed (aynı imza ikinci kez)",
     "0xa1ad95144f813310c2b6c96457b35be32f71c3290f53d632f2b46baffbf99a80"),
    ("StaleScore (skor 1655 sn eski)",
     "0x0b29025776a1f03d8304fd01144ebe88741fe1d760ec405e5b8ebac9b91233a3"),
]
# Zincirde kanitlanmayan kontrol kalmadi; liste bosaldi ama yapisi duruyor
# (ileride tx'siz dogrulanan bir sey olursa buraya yazilir).
SIMULATED_ONLY = []


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

def _display_text(value):
    """Kaynak çıktısını değiştirmeden yalnızca insan okunur gösterimi düzeltir."""
    if value is None:
        return "—"
    text = str(value).replace("Trader'in", "Trader'ın").replace("trader'in", "trader'ın")
    words = {
        "planlayici": "planlayıcı", "imzali": "imzalı", "imzasiyla": "imzasıyla",
        "gonderdigi": "gönderdiği", "gonderildi": "gönderildi", "gonderilmedi": "gönderilmedi",
        "parca": "parça", "parcaya": "parçaya", "guvenli": "güvenli", "guven": "güven",
        "yayilmis": "yayılmış", "cevabi": "cevabı", "dusuk": "düşük", "yuksek": "yüksek",
        "olcum": "ölçüm", "olculdu": "ölçüldü", "esik": "eşik", "arac": "araç",
        "cagrisi": "çağrısı", "alinamadi": "alınamadı", "uretilmedi": "üretilmedi",
        "muhafazakar": "muhafazakâr",
    }
    def translate(match):
        source = match.group(0)
        lookup = source.lower().replace("i\u0307", "i").replace("ı", "i")
        result = words.get(lookup, source)
        if source.isupper():
            return result.replace("i", "İ").replace("ı", "I").upper()
        if source[0].isupper():
            first = {"i": "İ", "ı": "I"}.get(result[0], result[0].upper())
            return first + result[1:]
        return result
    text = re.sub(r"\b(" + "|".join(words) + r")\b", translate, text, flags=re.IGNORECASE)
    text = re.sub(r"\bNone\b", "—", text)
    return text.replace("$", " USDT")


def _safe(value):
    return escape(_display_text(value), quote=True)


def _tr(value, decimals=0):
    """Yalnızca gösterim: Türkçe sayı biçimi, eksik değer için uzun çizgi."""
    if value is None:
        return "—"
    try:
        return f"{float(value):,.{decimals}f}".translate(str.maketrans(",.", ".,"))
    except (TypeError, ValueError):
        return "—"


def _short_hash(value):
    text = str(value or "—")
    return text if len(text) < 16 else text[:6] + "…" + text[-4:]


def _amount(value):
    if value is None:
        return "—"
    try:
        return _tr(value, 0 if float(value).is_integer() else 2)
    except (TypeError, ValueError):
        return "—"


def _card(body, extra=""):
    return f'<div class="arf-card {extra}">{body}</div>'


def _decision_markup(decision):
    palette = {"ONAY": "#2BB673", "BOL": "#E0A526", "RED": "#E5484D",
               "VERI_YETERSIZ": "#E5484D"}
    label = DECISION_STYLE.get(decision, (None, decision or "—"))[1]
    title, _, detail = label.partition(" — ")
    return (f'<div class="arf-card arf-decision" style="--arf-state:{palette.get(decision, "#8A93A6")}">'
            f'<div class="arf-decision-name">{_safe(title)}</div>'
            f'<div class="arf-muted">{_safe(detail)}</div></div>')


def render_badge(decision):
    st.html(_decision_markup(decision))


# Veri kesintisi sahnesinde bu araclar canli tahtaya DEGIL hafizaya bakiyor;
# karar izinde bunu acikca etiketliyoruz (karar mantigi degismiyor).
MEMORY_TOOLS = ("scan_market", "compute_metric")


def _trace_summary(entry):
    """Araç çıktısını yalnızca sunum için kısaltır; ölçüm/karar üretmez."""
    raw = str(entry.get("summary") or "")
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    # Trace çıktısı kısaltılmış JSON olabilir; yalnızca var olan alanı okuruz.
    def field(name):
        if name in data:
            return data[name]
        hit = re.search(r'"' + re.escape(name) + r'"\s*:\s*(-?\d+(?:\.\d+)?|null|true|false)', raw)
        return json.loads(hit.group(1)) if hit else None
    tool = entry.get("tool")
    if data.get("ok") is False:
        return str(data.get("error") or "Veri alınamadı.")[:180]
    if tool == "compute_metric":
        slip = field("kayma_bps")
        safe = field("maxSafeSize_usdt")
        status = data.get("status") or ("INSUFFICIENT_DATA" if "INSUFFICIENT_DATA" in raw else None)
        if status == "INSUFFICIENT_DATA":
            return "Veri yok veya bayat; imzalanabilir ölçüm yok."
        details = []
        if slip is not None:
            details.append(f"kayma {_tr(slip, 1)} bps")
        if safe is not None:
            details.append(f"güvenli tutar {_tr(safe, 2)} USDT")
        return " · ".join(details) or "İcra metrikleri hesaplandı; ayrıntılar ham çıktıda."
    if tool == "get_orderbook":
        depth = field("ask_depth_2pct_usdt")
        spread = field("spread_bps")
        if depth is not None:
            return f"Ask tarafı ±%2 derinlik {_tr(depth)} USDT."
        if spread is not None:
            return f"Tahta okundu; spread {_tr(spread, 1)} bps."
        return "Emir tahtası sorgulandı; ayrıntılar ham çıktıda."
    if tool == "get_candles":
        count = field("mum")
        return f"{_tr(count)} mum okundu; fiyat ve hacim özeti alındı." if count is not None else "Mum verisi sorgulandı."
    if tool == "scan_market":
        return "İzlenen paritelerin epizodik hafıza özeti sorgulandı."
    if tool == "sign_score":
        return "Deterministik ölçüm imzalandı." if data.get("ok") else "İmza aracı çağrıldı; sonuç ham çıktıda."
    return raw[:180] or "Araç sonucu yok."


def render_left(out):
    res = out["res"]
    feed_down = SCENES[out["scene"]]["feed_down"]
    st.subheader("Karar izi")
    if res is None:
        st.html(_card('<span class="arf-muted">Sahne seçilmedi veya koşu tamamlanamadı.</span>'))
        return
    used, budget = res["tool_calls_used"], agent.TOOL_BUDGET
    st.html(f'<div class="arf-budget"><span class="arf-mono">{used} / {budget} araç</span>'
            f'<span>{_safe((res.get("llm") or {}).get("mode") or "—")}</span></div>')
    st.progress(min(used / budget, 1.0))
    notes = []
    for e in res["trace"]:
        if not e["tool"]:
            notes.append(e["summary"])
            continue
        pill = ('<span class="arf-pill arf-memory">hafıza (canlı tahta YOK)</span>'
                if feed_down and e["tool"] in MEMORY_TOOLS else "")
        st.html('<div class="arf-trace">'
                f'<div class="arf-trace-head"><span class="arf-trace-no">{_safe(e["i"])}</span>'
                f'<span class="arf-trace-name">{_safe(e["tool"])}</span>'
                f'<span class="arf-trace-ms">{_tr(e["ms"])} ms</span></div>'
                f'<div class="arf-trace-summary">{_safe(_trace_summary(e))}</div>{pill}</div>')
        with st.expander("ham çıktı", expanded=False):
            st.code(str(e["summary"]), language="json")
    if notes:
        with st.expander("Karar notları", expanded=False):
            for note in notes:
                st.text(_display_text(note))
    lf = res.get("llm_final") or {}
    def field(label, value):
        return f'<div class="arf-field"><span class="arf-label">{label}</span>{_safe(value or "—")}</div>'
    evidence = " / ".join(str(k) for k in (lf.get("kanit") or []))
    body = '<h4>LLM okuması</h4>'
    body += field("Hipotez", lf.get("hipotez") or "Yapısal LLM çıktısı yok; deterministik karar kullanıldı.")
    body += field("Kanıt", evidence)
    body += field("Güven / öneri", " / ".join(str(lf.get(k) or "—") for k in ("guven", "karar_onerisi")))
    body += field("Karar kaynağı", decision_source(res))
    if lf.get("gerekce"):
        body += field("Gerekçe", lf["gerekce"])
    st.html(_card(body, "arf-llm"))
    llm = res.get("llm") or {}
    if llm.get("provider"):
        cost = f" · yaklaşık {_tr(llm['cost_usd'], 6)} USD" if llm.get("cost_usd") else ""
        st.caption(_display_text(f"{llm.get('provider') or '—'}/{llm.get('model') or '—'} · "
                   f"{_tr(llm.get('requests'))} istek · {_tr(llm.get('ms'))} ms{cost}"))


def render_middle(out):
    res = out["res"]
    st.subheader("Karar")
    if res is None:
        st.html(_card('<span class="arf-muted">Ölçüm yok.</span>'))
        return
    rs, threshold = res["riskScore"], res["riskThreshold"]
    width = max(0, min(100, float(rs) / threshold * 100)) if rs is not None and threshold else 0
    meter = f'<div class="arf-meter"><span style="width:{width:.2f}%"></span></div>'
    def metric(label, value, unit, tail="", extra=""):
        missing = " arf-missing" if value in ("—", "veri yok") else ""
        return _card(f'<div class="arf-label">{_safe(label)}</div>'
                     f'<div class="arf-value{missing}">{_safe(value)}</div>'
                     f'<div class="arf-unit">{_safe(unit)}</div>{tail}', extra)
    cards = metric("Güvenli emir tutarı · maxSafeSize", _amount(res["maxSafeSize"]), "USDT", extra="arf-metric-featured")
    cards += metric("Risk skoru", _tr(rs), f"/ {_tr(threshold)} eşik", meter)
    cards += metric("İcra maliyeti", _tr(res["slippage_bps_at_size"], 1), f"bps @ {_tr(out['size'])} USDT")
    no_data = res["status"] == "INSUFFICIENT_DATA"
    cards += metric("Veri yaşı", "veri yok" if no_data else _tr(res["data_age_s"], 2), "" if no_data else "sn", extra="arf-metric-age")
    st.html(f'<div class="arf-decision-board">{_decision_markup(res["decision"])}<div class="arf-grid">{cards}</div></div>')
    st.caption(_display_text(f"{res['status']} · hafıza noktası: {_tr(res.get('memory_points'))} · süre: {_tr(out['seconds'], 1)} sn"))
    if res["split_suggestion"]:
        suggestion = res["split_suggestion"]
        # Parça sayısı mevcut öneriden okunur; yeni bir icra planı hesaplanmaz.
        match = re.search(r"(\d+)\s+par[cç]a", suggestion)
        if match and int(match.group(1)) > 0:
            parts = int(match.group(1))
            suggestion = (f"{_amount(out['size'])} USDT yerine zamana yayılmış "
                          f"{parts} × {_amount(out['size'] / parts)} USDT "
                          f"(güvenli tutar {_amount(res['maxSafeSize'])} USDT)")
        st.html(_card(f'<div class="arf-label">Bölme önerisi</div><div class="arf-field">{_safe(suggestion)}</div>'))
    if res["decision"] == "VERI_YETERSIZ":
        st.html(_card(f'<div class="arf-label">İmza üretilmedi</div><div class="arf-field">{_safe(res["reason"])}</div>', "arf-error"))
    elif res["signed_attestation"]:
        digest = res["signed_attestation"]["digest"]
        st.html(_card('<div class="arf-label">İmzalı skor üretildi</div>'
                      f'<div class="arf-mono" title="{_safe(digest)}">{_safe(_short_hash(digest))}</div>'))


def render_right(out):
    st.subheader("Zincir")
    ch = out["chain"]
    if out["error"]:
        st.html(_card(f'<div class="arf-label">Koşu hatası</div><div class="arf-field">{_safe(out["error"])}</div>', "arf-error"))
    if ch is None:
        if out["res"] is not None and out["res"]["signed_attestation"] is None and out["scene"] != 3:
            message = "İmza yok — kontrata hiçbir şey gönderilmedi (fail-closed)."
        else:
            message = "Kontrat cevabı yok."
        st.html(_card(f'<div class="arf-label">Kontrat cevabı</div><div class="arf-muted">{message}</div>'))
    else:
        status = ch.get("status") or "—"
        err = ch.get("error") or {}
        event = ch.get("event") or {}
        ok = status in ("CONFIRMED", "SIMULATED_OK")
        name = ("IntentApproved" if status == "CONFIRMED" else
                "Kontrat onaylar — revert yok (IntentApproved bekleniyor)" if status == "SIMULATED_OK" else
                err.get("name") or "Kontrat reddi")
        if not ok and not err.get("name") and ch.get("error_text"):
            name = str(ch["error_text"]).split("(", 1)[0]
        mode = "ZİNCİRDE" if ch.get("sent") else "SİMÜLE"
        state = "#2BB673" if ok else "#E5484D"
        body = '<div class="arf-label">Kontrat cevabı</div>'
        body += f'<span class="arf-pill" style="border-color:{state}">{mode}</span>'
        body += f'<div class="arf-chain-name">{_safe(name)}</div>'
        body += f'<div class="arf-muted">{_safe(out.get("chain_label") or "")}</div>'
        args = err.get("args") or event
        if isinstance(args, dict) and args:
            body += '<dl class="arf-params">'
            for key, value in args.items():
                extra = ""
                if key in ("amount", "maxSafeSize", "maxSafe") and isinstance(value, (int, float)):
                    extra = f'<div class="arf-muted">{_tr(value / 1_000_000, 2)} USDT</div>'
                rendered = _tr(value) if isinstance(value, (int, float)) else str(value)
                body += f'<dt>{_safe(key)}</dt><dd>{_safe(rendered)}{extra}</dd>'
            body += '</dl>'
        elif not ok and ch.get("error_text"):
            body += f'<div class="arf-field arf-mono">{_safe(ch["error_text"])}</div>'
        body += f'<div class="arf-muted arf-mono">{_safe(status)}</div>'
        if ch.get("confirm_ms"):
            body += f'<div class="arf-muted">Onay {_tr(ch["confirm_ms"])} ms</div>'
        if out.get("trader_signer"):
            body += f'<div class="arf-muted">İmzalayan: <span class="arf-mono" title="{_safe(out["trader_signer"])}">{_safe(_short_hash(out["trader_signer"]))}</span> (trader — oracle DEĞİL)</div>'
        if ch.get("sent") and ch.get("explorer"):
            body += f'<a class="arf-explorer" href="{_safe(ch["explorer"])}" target="_blank" rel="noopener noreferrer">Explorer’da aç ↗</a>'
        elif not ch.get("sent"):
            body += '<div class="arf-muted">eth_call simülasyonu — zincire hiçbir şey yazılmadı</div>'
        st.html(_card(body, "arf-chain-success" if ok else ""))
    st.subheader("Zincirde doğrulanmış kanıtlar")
    body = '<p class="arf-proof-count">Kontratın demo kapsamındaki bütün revert yolları Fuji’de gerçek işlemle doğrulandı.</p>'
    body += '<div class="arf-proof-wrap"><table class="arf-proofs"><thead><tr><th scope="col">Olay</th><th scope="col">Tx</th><th scope="col">Link</th></tr></thead><tbody>'
    for label, tx in ONCHAIN_PROOFS:
        name = label.split(" (", 1)[0]
        body += f'<tr><td title="{_safe(label)}">{_safe(name)}</td><td class="arf-mono" title="{_safe(tx)}">{_safe(_short_hash(tx))}</td><td><a aria-label="{_safe(label)} işlemini explorer’da aç" href="{EXPLORER.format(tx)}" target="_blank" rel="noopener noreferrer">Aç ↗</a></td></tr>'
    body += '</tbody></table></div>'
    st.html(_card(body))
    if SIMULATED_ONLY:
        st.caption("Yalnızca eth_call ile doğrulanan (tx gönderilmeyen) kontroller:")
        for label, note in SIMULATED_ONLY:
            st.caption(f"· {label} — {note}")


# =============================================================================
# Sayfa
# =============================================================================

def main():
    st.set_page_config(page_title="Arf", layout="wide")
    st.html(Path(__file__).resolve().parent / "assets" / "arf.css")

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
        contract_addr = chain.contract_address()
        st.caption(f"Kontrat: `{contract_addr}` "
                   "(Avalanche Fuji, chainId 43113)")

    st.html('<div class="arf-topbar"><div class="arf-brand"><h1>Arf</h1>'
            '<span class="arf-tagline">işlem öncesi icra ve likidite kalkanı</span></div>'
            '<div class="arf-badges"><span class="arf-pill">Avalanche Fuji · 43113</span>'
            '<span class="arf-pill">OKX Agent Trade Kit</span>'
            f'<a class="arf-pill arf-mono" href="https://explorer-test.avax.network/c-chain/address/{_safe(contract_addr)}" '
            f'target="_blank" rel="noopener noreferrer" title="{_safe(contract_addr)}">{_safe(_short_hash(contract_addr))} ↗</a></div></div>')
    with st.container(key="scenes"):
        cols = st.columns(3)
    active = st.session_state.get("active_scene")
    for i, (scene, cfg) in enumerate(SCENES.items()):
        # Tiklanan sahnenin butonu vurgulanir (onceki halde hep Sahne 1 idi)
        if cols[i].button(cfg["label"], use_container_width=True,
                          type="primary" if scene == active else "secondary"):
            st.session_state["active_scene"] = scene
            with st.spinner("Tahta okunuyor, icra maliyeti hesaplanıyor…"):
                st.session_state["out"] = run_scene(scene, symbol, use_llm, send)
            st.rerun()
        cols[i].caption(cfg["aciklama"])

    out = st.session_state.get("out")
    if out is None:
        st.html('<div class="arf-empty"><div><span class="arf-label">Emir öncesi icra kontrolü</span>'
                '<strong>Emirden önce<br>likiditeyi gör.</strong>'
                '<p>Bir sahne seçin. Tahtanın taşıyabildiği tutarı, icra maliyetini ve kontratın cevabını birlikte inceleyin.</p></div>'
                '<ol class="arf-empty-flow"><li><span>01</span>ATK ile canlı tahta</li>'
                '<li><span>02</span>Deterministik icra ölçümü</li>'
                '<li><span>03</span>Avalanche üzerinde kontrol</li></ol></div>')
        return

    if SCENES[out["scene"]]["feed_down"]:
        st.html('<div class="arf-simulation" role="status">SİMÜLASYON — veri kesintisi + yetkisiz imza</div>')
        st.caption("ARF_FEED_DOWN=1 — ATK CLI hiç çağrılmıyor; besleme kopmuş gibi davranılıyor.")

    with st.container(key="workspace"):
        left, middle, right = st.columns([1.1, 1.0, 1.0])
    with left:
        render_left(out)
    with middle:
        render_middle(out)
    with right:
        render_right(out)

    res = out.get("res") or {}
    tx = (out.get("chain") or {}).get("tx_hash")
    st.html('<div class="arf-summary">'
            f'{_safe(res.get("decision") or "—")} · kaynak: {_safe(decision_source(res))} · '
            f'süre {_tr(out["seconds"], 1)} sn · tx: <span class="arf-mono" title="{_safe(tx or "yok")}">{_safe(_short_hash(tx) if tx else "yok")}</span></div>')


if __name__ == "__main__":
    # Streamlit scripti __main__ olarak kosar; bu kalip ayni dosyanin
    # testlerde (streamlit calismazken) import edilebilmesini saglar.
    main()
