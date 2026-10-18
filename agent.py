"""
agent.py — Arf'in LLM planlayici dongusu ve check_execution ucu.

Bolunme: LLM PLANLAR (hangi araci ne zaman cagiracagini secer), sayilari
metrics.py uretir, final karari deterministik kural verir. LLM'in onerisi
yalnizca DAHA MUHAFAZAKAR ise kazanir; daha gevsekse yok sayilir ve bu
trace'e yazilir.

LLM'e kullanicidan serbest metin GITMEZ: yalnizca dogrulanmis sembol, yon,
tutar ve araclarin dondurdugu yapisal ozetler gider.

Karar siralamasi (muhafazakarlik): VERI_YETERSIZ > RED > BOL > ONAY.

Kullanim:
    python agent.py ZBCN-USDT buy 1000
    python agent.py ZBCN-USDT buy 1000 --execute
    python agent.py ZBCN-USDT buy 10000 --execute --force-onchain
    python agent.py ZBCN-USDT buy 1000 --no-llm      # deterministik plan
"""

import argparse
import json
import math
import re
import statistics
import time
from pathlib import Path

import atk_client
import llm as llm_mod
import metrics
import signer

SYMBOL_RE = re.compile(r"^[A-Z0-9]+-USDT$")

# --- VARSAYIM: dikkat butcesi ----------------------------------------------
TOOL_BUDGET = 12

# --- VARSAYIM: metrik bu yastan eskiyse final karar oncesi yenilenir --------
REFRESH_AGE_S = 60

# Muhafazakarlik sirasi (buyuk = daha muhafazakar)
DECISION_RANK = {"ONAY": 0, "BOL": 1, "RED": 2, "VERI_YETERSIZ": 3}
VALID_CONFIDENCE = {"dusuk", "orta", "yuksek"}

# Hisse/ETF tokenleri secim disi (pick_pairs.py ile ayni gerekce)
STOCK_TOKEN_CATEGORY = "3"

SYSTEM_PROMPT = """Sen bir islem-oncesi icra analistisin. Gorev: verilen emir
niyetinin bu emir tahtasinda ne kadar guvenli oldugunu ARACLARLA olcmek.

Kurallar:
- Sayisal hesap YAPMA. Kayma, derinlik, risk skoru, guvenli tutar yalnizca
  compute_metric aracindan gelir. Kendi tahminini sayi gibi sunma.
- Once tahtaya ve metrige bak; gerekiyorsa mumlara ve piyasa taramasina.
- Olcumler tamamlaninca imzayi tetiklemek icin sign_score cagir
  (argumansizdir; son deterministik sonucu imzalar).
- En fazla {budget} arac cagrisi hakkin var. Bitince final cevabi ver.

Final cevabin SADECE su JSON olmali (markdown yok, aciklama yok):
{{"hipotez": "<tek cumle>", "kanit": ["<kisa kanit>", "..."],
  "guven": "dusuk|orta|yuksek",
  "karar_onerisi": "ONAY|RED|BOL|VERI_YETERSIZ",
  "gerekce": "<tek cumle>"}}

Karar anlamlari: ONAY = emir bu tahtada guvenli; BOL = tutar guvenli tutari
asiyor, parcalara bolunmeli; RED = risk skoru esigin uzerinde;
VERI_YETERSIZ = veri yok veya bayat."""


TOOLS = [
    {
        "name": "scan_market",
        "description": ("Izlenen paritelerin epizodik hafiza ozeti: son spread, "
                        "son +-%2 derinlik, hafiza nokta sayisi. Guvenli tutar "
                        "icin compute_metric gerekir."),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_orderbook",
        "description": ("Tahta ozeti: mid, spread_bps, +-%0.5/%1/%2 derinlikleri "
                        "(USDT), book_truncated, data_age_s. Ham seviyeler donmez."),
        "parameters": {
            "type": "object",
            "properties": {"symbol": {"type": "string", "description": "orn. ZBCN-USDT"}},
            "required": ["symbol"],
        },
    },
    {
        "name": "get_candles",
        "description": ("1 dakikalik mum ozeti: son getiri, volatilite (log-getiri "
                        "standart sapmasi), toplam hacim."),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "n": {"type": "integer", "description": "mum sayisi, en fazla 60"},
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "compute_metric",
        "description": ("DETERMINISTIK icra olcumu: riskScore (0-10000), maxSafeSize "
                        "(USDT), istenen tutardaki kayma, dolum, bilesenler, durum."),
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "side": {"type": "string", "enum": ["buy", "sell"]},
                "size_usdt": {"type": "number"},
            },
            "required": ["symbol", "side", "size_usdt"],
        },
    },
    {
        "name": "sign_score",
        "description": ("Son deterministik sonucu oracle anahtariyla imzalar. "
                        "Arguman almaz; sayilari degistiremez. Yalnizca veri taze "
                        "ve durum OK/OK_LIMITED_MEMORY ise imzalar."),
        "parameters": {"type": "object", "properties": {}},
    },
]


# =============================================================================
# Bagimliliklar (canli / test icin enjekte edilebilir)
# =============================================================================

class LiveDeps:
    """Gercek veri kaynaklari: ATK CLI, memory.db, Fuji."""

    PAIRS_PATH = str(Path(__file__).resolve().parent / "pairs.json")

    def __init__(self, db_path=metrics.DB_PATH, pairs_path=None):
        self.db_path = db_path
        self.pairs_path = pairs_path or self.PAIRS_PATH
        self._symbols = None
        self._threshold = None
        self._chain = None  # (w3, url)

    # --- piyasa verisi ---
    def live_symbols(self):
        if self._symbols is None:
            res = atk_client.get_instruments_spot()
            if not res["ok"]:
                self._symbols = set()
            else:
                self._symbols = {
                    x["instId"] for x in res["data"]
                    if x.get("state") == "live" and x.get("quoteCcy") == "USDT"
                    and str(x.get("instCategory")) != STOCK_TOKEN_CATEGORY
                }
        return self._symbols

    def orderbook(self, symbol):
        return atk_client.get_orderbook(symbol)

    def candles(self, symbol, n):
        return atk_client.get_candles(symbol, bar="1m", limit=n)

    def memory(self, symbol):
        return metrics.load_memory(symbol, db_path=self.db_path)

    def pairs(self):
        try:
            with open(self.pairs_path) as f:
                return [r["inst"] for r in json.load(f)]
        except OSError:
            return []

    # --- zincir ---
    def _connect(self):
        import chain
        if self._chain is None:
            self._chain = chain.connect(verbose=False)
        return self._chain

    def risk_threshold(self):
        """Esigi ZINCIRDEN okur. Okunamazsa beklenen deger + uyari."""
        import chain
        if self._threshold is None:
            try:
                w3, _url = self._connect()
                c = chain.get_contract(w3)
                self._threshold = (c.functions.riskThreshold().call(), "zincir")
            except Exception as exc:
                self._threshold = (chain.EXPECTED["riskThreshold"],
                                   f"zincir okunamadi ({type(exc).__name__}), beklenen deger")
        return self._threshold

    def contract_address(self):
        import chain
        # chain.contract_address(): .env mutlak yoldan yuklenir, bos donmez
        return chain.contract_address()

    def sign(self, symbol, side, risk_score, max_safe_usdt, timestamp):
        import chain
        return chain.sign_attestation_with_oracle(
            symbol, side, risk_score, max_safe_usdt, timestamp,
            contract_addr=self.contract_address(),
        )


# =============================================================================
# Oturum
# =============================================================================

class AgentSession:
    """Araclari yurutur, trace tutar, butceyi sayar."""

    def __init__(self, symbol, side, size_usdt, deps=None, budget=TOOL_BUDGET):
        self.symbol = symbol
        self.side = side
        self.size_usdt = float(size_usdt)
        self.deps = deps or LiveDeps()
        self.budget = budget
        self.used = 0
        self.trace = []
        self.metric = None          # istenen niyetin DETERMINISTIK olcumu
        self.attestation = None
        self.sign_requested = False

    # --- trace ---
    def note(self, text):
        self.trace.append({"i": len(self.trace) + 1, "tool": None, "args": None,
                           "summary": text, "ms": 0})

    def _record(self, tool, args, summary, ms):
        self.trace.append({"i": len(self.trace) + 1, "tool": tool, "args": args,
                           "summary": summary, "ms": ms})

    # --- sembol dogrulama ---
    def valid_symbol(self, symbol):
        if not isinstance(symbol, str) or not SYMBOL_RE.match(symbol):
            return False, "sembol bicimi gecersiz (^[A-Z0-9]+-USDT$)"
        live = self.deps.live_symbols()
        if live and symbol not in live:
            return False, "sembol SPOT live listesinde yok"
        return True, None

    # --- araclar ------------------------------------------------------------

    def tool_scan_market(self):
        rows = []
        for inst in self.deps.pairs():
            mem = self.deps.memory(inst)
            depth = mem["depths"][-1] if mem["depths"] else None
            rows.append({
                "symbol": inst,
                "son_derinlik_2pct_usdt": None if depth is None else round(depth),
                "hafiza_noktasi": mem["n"],
            })
        return {"ok": True, "pariteler": rows,
                "not": "maxSafeSize ve kayma icin compute_metric kullan"}

    def tool_get_orderbook(self, symbol=None, **_):
        ok, err = self.valid_symbol(symbol or "")
        if not ok:
            return {"ok": False, "error": err}
        res = self.deps.orderbook(symbol)
        if not res["ok"] or not res.get("data"):
            return {"ok": False, "error": res.get("error") or "tahta alinamadi"}
        book = res["data"]
        out = {"ok": True, "symbol": symbol,
               "data_age_s": round(time.time() - res["fetched_at"], 1)}
        for pct, label in ((0.005, "0.5"), (0.01, "1"), (0.02, "2")):
            d = atk_client.depth_within(book, pct=pct)
            if d is None:
                return {"ok": False, "error": "tahta bos/bozuk"}
            out[f"bid_depth_{label}pct_usdt"] = round(d["bid_depth_usdt"])
            out[f"ask_depth_{label}pct_usdt"] = round(d["ask_depth_usdt"])
            if label == "2":
                out["mid"] = d["mid"]
                out["spread_bps"] = round(d["spread_bps"], 2)
                out["book_truncated"] = d["book_truncated"]
        return out

    def tool_get_candles(self, symbol=None, n=60, **_):
        ok, err = self.valid_symbol(symbol or "")
        if not ok:
            return {"ok": False, "error": err}
        try:
            n = max(5, min(int(n or 60), 60))
        except (TypeError, ValueError):
            n = 60
        res = self.deps.candles(symbol, n)
        if not res["ok"] or not res.get("data"):
            return {"ok": False, "error": res.get("error") or "mum alinamadi"}
        rows = res["data"]
        closes = [float(r[4]) for r in rows][::-1]   # eskiden yeniye
        vols = [float(r[6]) for r in rows]           # volCcy (USDT)
        logs = metrics.log_changes(closes)
        vol_std = statistics.pstdev(logs) if len(logs) > 1 else 0.0
        return {
            "ok": True, "symbol": symbol, "mum": len(rows),
            "son_getiri_bps": round(logs[-1] * 10_000, 2) if logs else None,
            "volatilite_bps_1m": round(vol_std * 10_000, 2),
            "toplam_hacim_usdt": round(sum(vols)),
        }

    def tool_compute_metric(self, symbol=None, side=None, size_usdt=None, **_):
        ok, err = self.valid_symbol(symbol or "")
        if not ok:
            return {"ok": False, "error": err}
        if side not in ("buy", "sell"):
            return {"ok": False, "error": "side 'buy' veya 'sell' olmali"}
        try:
            size = float(size_usdt)
        except (TypeError, ValueError):
            return {"ok": False, "error": "size_usdt sayi olmali"}
        if size <= 0:
            return {"ok": False, "error": "size_usdt pozitif olmali"}

        res = metrics.check_execution_core(
            symbol, side, size,
            book_result=self.deps.orderbook(symbol),
            memory=self.deps.memory(symbol),
        )
        # Yalnizca ISTENEN niyetin olcumu karar icin baglayicidir
        authoritative = (symbol == self.symbol and side == self.side
                         and abs(size - self.size_usdt) < 1e-9)
        if authoritative:
            self.metric = res

        comp = res.get("components") or {}
        return {
            "ok": True, "yetkili_olcum": authoritative,
            "symbol": symbol, "side": side, "size_usdt": size,
            "status": res["status"], "riskScore": res["riskScore"],
            "maxSafeSize_usdt": None if res["maxSafeSize"] is None else round(res["maxSafeSize"], 2),
            "kayma_bps": None if res["slippage_bps_at_size"] is None else round(res["slippage_bps_at_size"], 2),
            "fills": res["fills"], "data_age_s": res["data_age_s"],
            "hafiza_noktasi": res["memory_points"],
            "bonferroni_z": round(res["bonferroni_z"], 3),
            "spread_bps": None if comp.get("spread_bps") is None else round(comp["spread_bps"], 2),
            "derinlik_orani": None if comp.get("depth_ratio") is None else round(comp["depth_ratio"], 3),
            "anomali_z": None if comp.get("anomaly_z") is None else round(comp["anomaly_z"], 2),
            "book_truncated": comp.get("book_truncated"),
        }

    def tool_sign_score(self, **_):
        self.sign_requested = True
        att, reason = self.sign_current()
        if att is None:
            return {"ok": False, "error": reason}
        # Birimler ACIKCA etiketli: kontrat USDT x 1e6 tamsayisi bekliyor;
        # etiketsiz birakildiginda model bunu birim tutarsizligi saniyor.
        return {"ok": True, "digest": att["digest"], "signer": att["signer"],
                "riskScore_0_10000": att["riskScore"],
                "maxSafeSize_usdt": att["maxSafeSizeUsdt"],
                "maxSafeSize_contract_units_1e6": att["maxSafeSize"],
                "not": "sayilar deterministik olcumden geldi; kontrat birimi "
                       "USDT x 1e6 (6 ondalik), USDT degeri ayrica verildi"}

    # --- imza ---------------------------------------------------------------

    def sign_current(self):
        """Yetkili olcumu imzalar. (attestation, sebep) doner."""
        m = self.metric
        if m is None:
            return None, "once compute_metric cagir (yetkili olcum yok)"
        if m["status"] == "INSUFFICIENT_DATA":
            return None, "INSUFFICIENT_DATA — imza yok (fail-closed)"
        age = m.get("data_age_s")
        if age is None or age > metrics.MAX_DATA_AGE_S:
            return None, f"veri {age} sn eski (sinir {metrics.MAX_DATA_AGE_S}) — imza yok"
        att = self.deps.sign(m["symbol"], m["side"], m["riskScore"],
                             m["maxSafeSize"], int(time.time()))
        self.attestation = att
        return att, None

    # --- arac dagitimi ------------------------------------------------------

    TOOL_MAP = {
        "scan_market": "tool_scan_market",
        "get_orderbook": "tool_get_orderbook",
        "get_candles": "tool_get_candles",
        "compute_metric": "tool_compute_metric",
        "sign_score": "tool_sign_score",
    }

    def call_tool(self, name, args):
        """Araci yurutur, trace'e yazar. Butce kontrolu cagirana ait."""
        args = args or {}
        fn_name = self.TOOL_MAP.get(name)
        started = time.time()
        if fn_name is None:
            out = {"ok": False, "error": f"bilinmeyen arac: {name}"}
        else:
            try:
                out = getattr(self, fn_name)(**args)
            except TypeError as exc:
                out = {"ok": False, "error": f"arac argumanlari hatali: {exc}"}
            except Exception as exc:
                out = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        ms = int((time.time() - started) * 1000)
        self.used += 1
        self._record(name, args, _short(out), ms)
        return out


def _short(payload, limit=220):
    """Trace icin kisa ozet (LLM'e giden tam yanit degil)."""
    try:
        text = json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(payload)
    return text if len(text) <= limit else text[:limit] + "…"


# =============================================================================
# Deterministik karar + birlestirme
# =============================================================================

def deterministic_decision(metric, threshold, size_usdt):
    """Zincirdeki kurallarin aynisi, zincir disinda."""
    if metric is None or metric["status"] == "INSUFFICIENT_DATA":
        return "VERI_YETERSIZ", "veri yok veya bayat"
    if metric["riskScore"] > threshold:
        return "RED", f"riskScore {metric['riskScore']} > esik {threshold}"
    size_units = signer.to_usdt_units(size_usdt)
    safe_units = signer.to_usdt_units(metric["maxSafeSize"])
    if safe_units == 0:
        return "BOL", "bu tahtada guvenli tutar yok"
    if size_units > safe_units:
        parts = math.ceil(size_units / safe_units)
        return "BOL", f"tutar guvenli tutari asiyor, {parts} parca"
    return "ONAY", "tutar guvenli tutarin icinde"


def merge_decisions(det, llm_suggestion):
    """Muhafazakar olan kazanir. Doner: (final, etiket)."""
    if llm_suggestion not in DECISION_RANK:
        return det, "LLM onerisi yok/gecersiz — deterministik karar"
    if DECISION_RANK[llm_suggestion] > DECISION_RANK[det]:
        return llm_suggestion, f"LLM onerisi kazandi ({llm_suggestion} > {det}): daha muhafazakar"
    if DECISION_RANK[llm_suggestion] < DECISION_RANK[det]:
        return det, f"LLM onerisi reddedildi ({llm_suggestion}): daha az muhafazakar"
    return det, "LLM onerisi deterministik kararla ayni"


def split_suggestion(decision, size_usdt, max_safe_usdt):
    if decision != "BOL":
        return None
    if not max_safe_usdt or max_safe_usdt <= 0:
        return "Bu tahtada guvenli tutar yok — bolme onerisi yok."
    parts = math.ceil(signer.to_usdt_units(size_usdt) / signer.to_usdt_units(max_safe_usdt))
    per = size_usdt / parts
    return (f"{size_usdt:,.0f}$ yerine zamana yayilmis {per:,.0f}$'lik "
            f"{parts} parca (guvenli tutar {max_safe_usdt:,.0f}$).")


# =============================================================================
# LLM final JSON
# =============================================================================

REQUIRED_KEYS = ("hipotez", "kanit", "guven", "karar_onerisi", "gerekce")


def parse_final(text):
    """LLM'in final JSON'unu dogrular. (obj, hata) doner."""
    if not text:
        return None, "bos yanit"
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        raw = raw.rsplit("```", 1)[0]
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1:
        return None, "JSON bulunamadi"
    try:
        obj = json.loads(raw[start:end + 1])
    except json.JSONDecodeError as exc:
        return None, f"JSON cozulemedi: {exc}"
    if not isinstance(obj, dict):
        return None, "JSON nesnesi degil"
    missing = [k for k in REQUIRED_KEYS if k not in obj]
    if missing:
        return None, f"eksik alanlar: {missing}"
    if obj["karar_onerisi"] not in DECISION_RANK:
        return None, f"karar_onerisi gecersiz: {obj['karar_onerisi']!r}"
    if obj["guven"] not in VALID_CONFIDENCE:
        return None, f"guven gecersiz: {obj['guven']!r}"
    if not isinstance(obj["kanit"], list):
        return None, "kanit liste olmali"
    return obj, None


# =============================================================================
# Ana akis
# =============================================================================

DETERMINISTIC_PLAN = [
    ("get_orderbook", "symbol"),
    ("get_candles", "symbol_n"),
    ("compute_metric", "intent"),
    ("sign_score", "none"),
]


def _plan_args(kind, symbol, side, size_usdt):
    if kind == "symbol":
        return {"symbol": symbol}
    if kind == "symbol_n":
        return {"symbol": symbol, "n": 60}
    if kind == "intent":
        return {"symbol": symbol, "side": side, "size_usdt": size_usdt}
    return {}


def run_check(symbol, side, size_usdt, provider=None, deps=None, use_llm=True,
              budget=TOOL_BUDGET):
    """check_execution: tek niyet icin uctan uca icra karnesi."""
    t_start = time.time()
    deps = deps or LiveDeps()
    session = AgentSession(symbol, side, size_usdt, deps=deps, budget=budget)

    # --- 0) girdi dogrulama (LLM'e serbest metin gitmez) -------------------
    if side not in ("buy", "sell"):
        raise ValueError("side 'buy' veya 'sell' olmali")
    ok, err = session.valid_symbol(symbol)
    if not ok:
        return {
            "symbol": symbol, "side": side, "size_usdt": float(size_usdt),
            "decision": "VERI_YETERSIZ", "reason": f"sembol reddedildi: {err}",
            "riskScore": None, "maxSafeSize": None, "split_suggestion": None,
            "signed_attestation": None, "llm": None, "trace": [],
            "data_age_s": None, "total_ms": int((time.time() - t_start) * 1000),
        }

    # --- 1) LLM planlayici veya deterministik plan -------------------------
    llm_info = {"provider": None, "model": None, "requests": 0, "ms": 0,
                "tokens": 0, "retries": 0, "mode": None}
    llm_suggestion = None
    llm_final = None
    fell_back = False  # LLM yarida kesildi -> deterministik plan yine calisir

    if use_llm:
        try:
            provider = provider or llm_mod.get_provider()
        except llm_mod.LLMUnavailable as exc:
            session.note(f"LLM yok — deterministik plan ({exc})")
            provider = None
            llm_info["mode"] = "deterministik (LLM yok)"
    else:
        provider = None
        llm_info["mode"] = "deterministik (--no-llm)"

    if provider is not None:
        # Zincirde aktif saglayici ilk cagridan sonra belli olur
        llm_info["provider"] = getattr(provider, "provider_name", None) or provider.name
        llm_info["model"] = provider.model
        llm_info["mode"] = "LLM planlayici"
        messages = [{
            "role": "user",
            "text": json.dumps({
                "niyet": {"symbol": symbol, "side": side, "size_usdt": float(size_usdt)},
                "gorev": "Bu niyetin icra guvenligini araclarla olc ve final JSON'u ver.",
            }, ensure_ascii=False),
        }]
        system = SYSTEM_PROMPT.format(budget=budget)

        try:
            while True:
                if session.used >= budget:
                    session.note(f"butce doldu ({budget} arac cagrisi) — "
                                 f"dongu kesildi, karar deterministik")
                    break
                step = provider.chat_with_tools(messages, TOOLS, system=system)
                if step["tool_calls"]:
                    # Modelin turu AYNEN geri gider (_raw): Gemini 3.x
                    # thought_signature'i kayip parcalari reddediyor.
                    messages.append({"role": "model", "tool_calls": step["tool_calls"],
                                     "_raw": step.get("raw")})
                    for call in step["tool_calls"]:
                        if session.used >= budget:
                            session.note(f"butce doldu ({budget}) — kalan arac "
                                         f"cagrilari atlandi")
                            break
                        out = session.call_tool(call["name"], call.get("args"))
                        # id: Anthropic tool_result eslesmesi icin sart
                        messages.append({"role": "tool", "name": call["name"],
                                         "response": out, "id": call.get("id")})
                    continue

                llm_final, perr = parse_final(step["final"])
                if llm_final is None:
                    session.note(f"LLM final JSON gecersiz ({perr}) — 1 duzeltme istendi")
                    messages.append({"role": "model", "text": step["final"] or "",
                                     "_raw": step.get("raw")})
                    messages.append({"role": "user", "text":
                                     "Yanitin gecersiz. SADECE su alanlarla tek bir JSON "
                                     "nesnesi dondur: hipotez, kanit (liste), guven "
                                     "(dusuk|orta|yuksek), karar_onerisi "
                                     "(ONAY|RED|BOL|VERI_YETERSIZ), gerekce."})
                    step2 = provider.chat_with_tools(messages, TOOLS, system=system)
                    llm_final, perr2 = parse_final(step2["final"])
                    if llm_final is None:
                        session.note(f"LLM final JSON yine gecersiz ({perr2}) — "
                                     f"deterministik yedek")
                break
        except llm_mod.LLMUnavailable as exc:
            session.note(f"LLM dongusu kesildi — deterministik plana geciliyor ({exc})")
            llm_info["mode"] = "deterministik (LLM kesildi)"
            fell_back = True

        st = provider.stats
        llm_info.update({
            "provider": st.get("provider") or llm_info["provider"],
            "model": st.get("model") or llm_info["model"],
            "requests": st.get("requests", 0),
            "ms": st.get("ms", 0),
            "tokens": st.get("tokens", 0),
            "tokens_in": st.get("tokens_in", 0),
            "tokens_out": st.get("tokens_out", 0),
            "cost_usd": round(st.get("cost_usd", 0.0), 6),
            "retries": st.get("retries", 0),
            "chain": st.get("chain"),
            "provider_switches": st.get("provider_switches", 0),
            "errors": list(st.get("errors") or [])[-3:],
        })
        session.note(f"LLM: {llm_info['provider']}/{llm_info['model']} "
                     f"({llm_info['requests']} istek, "
                     f"{llm_info['tokens_in']}+{llm_info['tokens_out']} token"
                     + (f", ~${llm_info['cost_usd']:.6f}" if llm_info["cost_usd"] else "")
                     + (f", saglayici degisimi {llm_info['provider_switches']}"
                        if llm_info["provider_switches"] else "") + ")")
        if llm_final:
            llm_suggestion = llm_final.get("karar_onerisi")

    # --- 2) deterministik plan (LLM yoksa ya da eksik kaldiysa) ------------
    if provider is None or fell_back:
        for tool, kind in DETERMINISTIC_PLAN:
            if session.used >= budget:
                break
            session.call_tool(tool, _plan_args(kind, symbol, side, size_usdt))

    if session.metric is None:
        session.note("yetkili olcum yok — compute_metric deterministik olarak calistirildi")
        session.call_tool("compute_metric", {"symbol": symbol, "side": side,
                                             "size_usdt": float(size_usdt)})

    # --- 3) tazelik: karar ve imza taze veriye dayansin -------------------
    m = session.metric
    if m is not None and m.get("data_age_s") is not None and m["data_age_s"] > REFRESH_AGE_S:
        session.note(f"metrik {m['data_age_s']:.0f} sn eski — final karar oncesi yenilendi")
        session.call_tool("compute_metric", {"symbol": symbol, "side": side,
                                             "size_usdt": float(size_usdt)})
        m = session.metric

    # --- 4) final karar: deterministik, LLM yalnizca sikilastirabilir -----
    threshold, threshold_src = deps.risk_threshold()
    det, det_reason = deterministic_decision(m, threshold, size_usdt)
    final, merge_note = merge_decisions(det, llm_suggestion)
    session.note(f"deterministik karar: {det} ({det_reason}; esik {threshold} "
                 f"[{threshold_src}]) | {merge_note}")

    # --- 5) imza: VERI_YETERSIZ disinda imzalanir -------------------------
    attestation = None
    if final != "VERI_YETERSIZ":
        att, reason = session.sign_current()
        if att is None:
            session.note(f"imza uretilemedi: {reason}")
        else:
            attestation = att
            session.note(f"imzalandi: digest {att['digest'][:18]}… "
                         f"(riskScore {att['riskScore']}, maxSafeSize {att['maxSafeSize']})")
    else:
        session.note("VERI_YETERSIZ — imza YOK (fail-closed)")

    max_safe = None if m is None else m["maxSafeSize"]
    return {
        "symbol": symbol, "side": side, "size_usdt": float(size_usdt),
        "decision": final,
        "deterministic_decision": det,
        "llm_suggestion": llm_suggestion,
        "merge_note": merge_note,
        "reason": det_reason,
        "riskScore": None if m is None else m["riskScore"],
        "maxSafeSize": max_safe,
        "riskThreshold": threshold,
        "slippage_bps_at_size": None if m is None else m["slippage_bps_at_size"],
        "status": None if m is None else m["status"],
        "split_suggestion": split_suggestion(final, float(size_usdt), max_safe),
        "signed_attestation": attestation,
        "llm": llm_info,
        "llm_final": llm_final,
        "trace": session.trace,
        "tool_calls_used": session.used,
        "data_age_s": None if m is None else m["data_age_s"],
        "total_ms": int((time.time() - t_start) * 1000),
    }


# Dis arayuz adi: check_execution
check_execution = run_check


# =============================================================================
# CLI
# =============================================================================

def print_report(res, show_attestation=False):
    print(f"\n{'='*78}")
    print(f"ARF — islem oncesi icra kontrolu: {res['symbol']} {res['side']} "
          f"{res['size_usdt']:,.0f} USDT")
    print(f"{'='*78}")

    print(f"\nKARAR IZI ({res['tool_calls_used']}/{TOOL_BUDGET} arac cagrisi, "
          f"mod: {(res['llm'] or {}).get('mode')})")
    for e in res["trace"]:
        if e["tool"]:
            print(f"  {e['i']:>2}. {e['tool']}({_short(e['args'], 60)}) "
                  f"{e['ms']:>5} ms")
            print(f"      -> {e['summary']}")
        else:
            print(f"  {e['i']:>2}. [not] {e['summary']}")

    if res.get("llm_final"):
        lf = res["llm_final"]
        print(f"\nLLM OKUMASI (guven: {lf.get('guven')}, oneri: {lf.get('karar_onerisi')})")
        print(f"  hipotez: {lf.get('hipotez')}")
        for k in (lf.get("kanit") or [])[:5]:
            print(f"  - {k}")
        print(f"  gerekce: {lf.get('gerekce')}")

    print(f"\nSONUC")
    print(f"  karar           : {res['decision']}   "
          f"(deterministik: {res['deterministic_decision']}, "
          f"LLM: {res['llm_suggestion']})")
    print(f"  birlestirme     : {res['merge_note']}")
    print(f"  durum           : {res['status']}  veri yasi: {res['data_age_s']} sn")
    rs = res["riskScore"]
    print(f"  riskScore       : {rs} / esik {res['riskThreshold']}")
    if res["maxSafeSize"] is not None:
        print(f"  maxSafeSize     : {res['maxSafeSize']:,.2f} USDT")
    if res["slippage_bps_at_size"] is not None:
        print(f"  kayma @ tutar   : {res['slippage_bps_at_size']:.2f} bps")
    if res["split_suggestion"]:
        print(f"  bolme onerisi   : {res['split_suggestion']}")
    att = res["signed_attestation"]
    print(f"  imza            : {'VAR' if att else 'YOK'}"
          + (f"  digest {att['digest']}" if att else ""))
    if att and show_attestation:
        print(f"  imzalayan       : {att['signer']}")
    llm = res["llm"] or {}
    print(f"  LLM             : {llm.get('provider')}/{llm.get('model')}  "
          f"istek={llm.get('requests')} tekrar={llm.get('retries')} "
          f"token={llm.get('tokens_in')}+{llm.get('tokens_out')} "
          f"llm_ms={llm.get('ms')}"
          + (f"  maliyet=~${llm['cost_usd']:.6f}" if llm.get("cost_usd") else ""))
    if llm.get("chain"):
        print(f"  LLM zinciri     : {' -> '.join(llm['chain'])}  "
              f"(saglayici degisimi: {llm.get('provider_switches', 0)})")
    for e in (llm.get("errors") or []):
        print(f"  LLM hatasi      : {e}")
    print(f"  toplam sure     : {res['total_ms']} ms")


def main():
    ap = argparse.ArgumentParser(description="Arf — islem oncesi icra kontrolu")
    ap.add_argument("symbol")
    ap.add_argument("side", choices=["buy", "sell"])
    ap.add_argument("size_usdt", type=float)
    ap.add_argument("--no-llm", action="store_true", help="deterministik plan")
    ap.add_argument("--execute", action="store_true", help="niyeti Fuji'ye gonder")
    ap.add_argument("--force-onchain", action="store_true",
                    help="--execute ile: revert eden tx de zincire yazilsin")
    ap.add_argument("--json", action="store_true", help="ciktiyi JSON olarak bas")
    args = ap.parse_args()

    res = run_check(args.symbol, args.side, args.size_usdt, use_llm=not args.no_llm)

    if args.json:
        safe = dict(res)
        print(json.dumps(safe, ensure_ascii=False, indent=2, default=str))
    else:
        print_report(res)

    if not args.execute:
        return

    att = res["signed_attestation"]
    if att is None:
        print("\n[zincir] imza yok — tx gonderilmedi (fail-closed)")
        return

    import chain
    print(f"\n[zincir] executeIntent gonderiliyor: {res['symbol']} {res['side']} "
          f"{res['size_usdt']:,.0f} USDT (digest {att['digest'][:18]}…)")
    out = chain.execute_intent(res["symbol"], res["side"], res["size_usdt"], att,
                               force_onchain=args.force_onchain)
    print(f"\n[zincir] durum : {out['status']}")
    print(f"[zincir] sonuc : {out['error_text'] or out.get('event')}")
    if out["sent"]:
        print(f"[zincir] gas   : {out['gas_used']:,}  onay: {out['confirm_ms']} ms")
        print(f"[zincir] link  : {out['explorer']}")


if __name__ == "__main__":
    main()
