"""
llm.py — saglayicidan bagimsiz function-calling arayuzu.

Tek giris: provider.chat_with_tools(messages, tools)
  -> {"tool_calls": [{"name", "args", "id"}], "final": None, "raw": <opak>}
  -> {"tool_calls": [], "final": "<metin>", "raw": <opak>}

Notr mesaj bicimi (saglayici ne olursa olsun ayni):
  {"role": "user",  "text": "..."}
  {"role": "model", "text": "...", "_raw": <opak>}
  {"role": "model", "tool_calls": [{"name", "args", "id"}], "_raw": <opak>}
  {"role": "tool",  "name": ..., "response": {...}, "id": ...}

`_raw`: saglayicinin o turda dondurdugu HAM nesne. Cagiran onu anlamaz,
sadece geri verir. Gemini 3.x icin ZORUNLU (thought_signature), Anthropic
icin tool_use id eslesmesini garanti eder.

Notr arac bicimi:
  {"name": ..., "description": ..., "parameters": <JSON Schema>}

Saglayici zinciri: LLM_PROVIDER ile baslar, sirayla diger saglayicilara
geriler; hepsi dusunce LLMUnavailable (agent deterministik plana doner).

OLCULEN (2026-10-17, gercek API cagrilari)
  Gemini:
  * `gemini-2.5-flash` / `-lite`: models.list listeliyor ama generateContent
    404 ("no longer available to new users" -> gemini-3.8-flash).
  * `gemini-3.8-flash`, `3.5-flash`, `3.5-flash-lite`, `3.7-flash`: function
    calling calisiyor. Gecikme 809 ms - 6129 ms.
  * UCRETSIZ KATMAN KOTASI: gunluk 20 istek, MODEL BASINA
    (quotaId GenerateRequestsPerDayPerProjectPerModel-FreeTier). 3.8-flash
    kotasi bir gun icinde doldu; API "11h12m sonra" dedi.
  * 503 UNAVAILABLE ("high demand") 5 turdan 1'inde goruldu.
  * Arac dongusunde modelin turunu YENIDEN KURMAK 400 veriyor:
    "Function call is missing a thought_signature in functionCall parts".
    Resmi dokuman (ai.google.dev/gemini-api/docs/thinking#signatures):
    model parcalari gecmise AYNEN geri konulmali -> `_raw`.
  Anthropic:
  * `claude-haiku-5-5` models.retrieve ile DOGRULANDI: "Claude Haiku 5.5",
    max_input 1.000.000, max_output 128.000.
  * Fiyat (platform.claude.com/docs/en/about-claude/pricing, dogrulandi):
    <=100k prompt icin girdi $0.10/MTok, cikti $0.50/MTok, cache hit
    $0.01/MTok; >100k prompt icin $0.50 / $2.50.

GIZLILIK: API anahtarlari .env'den okunur, hicbir yere yazilmaz.
"""

import os
import time

from dotenv import load_dotenv

ENV_PATH = ".env"

# --- Gemini model zinciri ---------------------------------------------------
# Kota MODEL BASINA sayildigi icin bu gercek bir yedek.
# 3.8-flash o gun kotasini tukettigi icin zincirin sonunda.
DEFAULT_GEMINI_MODELS = ("gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.8-flash")
DEFAULT_GEMINI_MODEL = DEFAULT_GEMINI_MODELS[0]

# --- Anthropic ---------------------------------------------------------------
DEFAULT_ANTHROPIC_MODEL = "claude-haiku-5-5"
ANTHROPIC_MAX_TOKENS = 2048  # VARSAYIM: final JSON + arac cagrisi icin bol bol

# --- VARSAYIM: tekrar deneme politikasi ------------------------------------
MAX_RETRIES = 2                  # ilk denemeden sonra en fazla 2 deneme
RETRY_BACKOFF_S = (2.0, 5.0)     # artan bekleme
RETRYABLE_SUBSTRINGS = ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE",
                        "500", "INTERNAL", "504", "DEADLINE", "overloaded")

# GUNLUK kota/yetki hatalarinda tekrar denemek anlamsiz (API "11h sonra" diyor)
# ve her deneme kotadan bir istek daha yakiyor -> hemen LLMUnavailable.
FATAL_SUBSTRINGS = ("PerDayPerProject", "free_tier_requests", "per day",
                    "credit balance", "API_KEY_INVALID", "PERMISSION_DENIED",
                    "authentication_error", "404")

# Fiyat tablosu ($/MTok): girdi, cikti. Dogrulanmis kaynaklar yukarida.
PRICES_PER_MTOK = {
    "claude-haiku-5-5": (0.10, 0.50),   # <=100k prompt
    # Gemini ucretsiz katman: para degil kota harcaniyor -> 0.0
}


class LLMUnavailable(RuntimeError):
    """LLM kullanilamiyor (kota/kesinti/yapilandirma). Agent deterministik plana doner."""


def estimate_cost_usd(model, tokens_in, tokens_out):
    """Modelin bilinen fiyatiyla kaba maliyet. Fiyat bilinmiyorsa None."""
    price = PRICES_PER_MTOK.get(model)
    if price is None:
        return None
    return (tokens_in / 1e6) * price[0] + (tokens_out / 1e6) * price[1]


class BaseProvider:
    name = "base"

    def __init__(self, model=None):
        self.model = model
        self.stats = {"provider": self.name, "model": model, "requests": 0,
                      "retries": 0, "ms": 0, "tokens": 0, "tokens_in": 0,
                      "tokens_out": 0, "cost_usd": 0.0, "errors": []}

    def chat_with_tools(self, messages, tools, system=None, temperature=0.0):
        raise NotImplementedError

    def _retry(self, fn):
        """Gecici hatalarda artan beklemeyle tekrar dener; olumcul hatada durur."""
        last = None
        for attempt in range(MAX_RETRIES + 1):
            started = time.time()
            try:
                out = fn()
                self.stats["requests"] += 1
                self.stats["ms"] += int((time.time() - started) * 1000)
                return out
            except Exception as exc:
                self.stats["requests"] += 1
                self.stats["ms"] += int((time.time() - started) * 1000)
                text = f"{type(exc).__name__}: {exc}"
                self.stats["errors"].append(text[:160])
                last = text
                fatal = any(s in text for s in FATAL_SUBSTRINGS)
                retryable = any(s in text for s in RETRYABLE_SUBSTRINGS) and not fatal
                if not retryable or attempt == MAX_RETRIES:
                    break
                self.stats["retries"] += 1
                time.sleep(RETRY_BACKOFF_S[min(attempt, len(RETRY_BACKOFF_S) - 1)])
        raise LLMUnavailable(f"{self.name} cagrisi basarisiz: {last}")

    def _account(self, tokens_in, tokens_out):
        self.stats["tokens_in"] += tokens_in
        self.stats["tokens_out"] += tokens_out
        self.stats["tokens"] += tokens_in + tokens_out
        cost = estimate_cost_usd(self.model, tokens_in, tokens_out)
        if cost:
            self.stats["cost_usd"] += cost


# =============================================================================
# Anthropic (ana saglayici)
# =============================================================================

class AnthropicProvider(BaseProvider):
    """Claude Messages API + tool use (resmi `anthropic` SDK'si).

    Tool use dongusu resmi dokumana gore: asistanin tool_use bloklari gecmise
    AYNEN konur, sonuclar tek bir user mesajinda `tool_result` bloklari olarak
    ve ayni `tool_use_id` ile geri verilir.
    """

    name = "anthropic"

    def __init__(self, model=None, api_key=None):
        load_dotenv(ENV_PATH)
        model = model or os.getenv("ANTHROPIC_MODEL", DEFAULT_ANTHROPIC_MODEL)
        super().__init__(model=model)
        key = (api_key or os.getenv("ANTHROPIC_API_KEY", "")).strip()
        if not key:
            raise LLMUnavailable(".env icinde ANTHROPIC_API_KEY yok")
        try:
            import anthropic
        except ImportError as exc:
            raise LLMUnavailable(f"anthropic SDK kurulu degil: {exc}") from None
        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=key)

    # --- notr bicim -> Anthropic bicimi ------------------------------------

    def _to_messages(self, messages):
        """Notr gecmisi Anthropic mesajlarina cevirir.

        Modelin turu `_raw` (icerik bloklari listesi) olarak geldiyse aynen
        konur; baska saglayicidan gelmisse tool_use id'leri sentezlenir
        (zincir ortasinda saglayici degisirse gecmis bozulmasin).
        """
        out = []
        synth_ids = {}
        for m in messages:
            role = m.get("role")
            if role == "tool":
                tool_id = m.get("id") or synth_ids.get(m.get("name"))
                block = {
                    "type": "tool_result",
                    "tool_use_id": tool_id or f"toolu_synth_{m.get('name')}",
                    "content": _as_text(m.get("response")),
                }
                if isinstance(m.get("response"), dict) and m["response"].get("ok") is False:
                    block["is_error"] = True
                # Ardisik tool sonuclari TEK user mesajinda toplanir
                if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list) \
                        and out[-1]["content"] and out[-1]["content"][0].get("type") == "tool_result":
                    out[-1]["content"].append(block)
                else:
                    out.append({"role": "user", "content": [block]})
            elif m.get("tool_calls"):
                raw = m.get("_raw")
                if isinstance(raw, list):
                    out.append({"role": "assistant", "content": raw})
                else:
                    blocks = []
                    for i, c in enumerate(m["tool_calls"]):
                        tid = c.get("id") or f"toolu_synth_{c['name']}"
                        synth_ids[c["name"]] = tid
                        blocks.append({"type": "tool_use", "id": tid,
                                       "name": c["name"], "input": c.get("args") or {}})
                    out.append({"role": "assistant", "content": blocks})
            else:
                text = m.get("text", "")
                out.append({"role": "assistant" if role == "model" else "user",
                            "content": text or "(bos)"})
        return out

    @staticmethod
    def _to_tools(tools):
        return [{
            "name": s["name"],
            "description": s["description"],
            "input_schema": s.get("parameters") or {"type": "object", "properties": {}},
        } for s in tools]

    def chat_with_tools(self, messages, tools, system=None, temperature=0.0):
        payload = {
            "model": self.model,
            "max_tokens": ANTHROPIC_MAX_TOKENS,
            "messages": self._to_messages(messages),
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = self._to_tools(tools)

        def call():
            return self._client.messages.create(**payload)

        resp = self._retry(call)

        usage = getattr(resp, "usage", None)
        if usage:
            self._account(getattr(usage, "input_tokens", 0) or 0,
                          getattr(usage, "output_tokens", 0) or 0)

        calls, texts = [], []
        for block in resp.content:
            if block.type == "tool_use":
                calls.append({"name": block.name, "args": dict(block.input or {}),
                              "id": block.id})
            elif block.type == "text":
                texts.append(block.text)

        if calls:
            return {"tool_calls": calls, "final": None, "raw": list(resp.content)}
        return {"tool_calls": [], "final": "\n".join(texts).strip(),
                "raw": list(resp.content)}


def _as_text(payload):
    """Arac sonucunu Anthropic'in bekledigi metne cevirir."""
    import json
    if isinstance(payload, str):
        return payload
    try:
        return json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(payload)


# =============================================================================
# Gemini (yedek saglayici)
# =============================================================================

class GeminiProvider(BaseProvider):
    name = "gemini"

    SYSTEM_SUFFIX = (
        "Sadece verilen araclarla calis. Sayisal sonuclari kendin hesaplama; "
        "araclarin dondurdugu degerleri kullan."
    )

    def __init__(self, model=None, api_key=None, models=None):
        load_dotenv(ENV_PATH)
        # Sira: parametre > LLM_MODEL > LLM_MODELS > varsayilan zincir
        chain = []
        for cand in ([model] if model else []) + [os.getenv("LLM_MODEL", "").strip()]:
            if cand and cand not in chain:
                chain.append(cand)
        for cand in (models or []) + os.getenv("LLM_MODELS", "").split(","):
            cand = (cand or "").strip()
            if cand and cand not in chain:
                chain.append(cand)
        for cand in DEFAULT_GEMINI_MODELS:
            if cand not in chain:
                chain.append(cand)
        self.models = chain
        super().__init__(model=chain[0])
        self.stats["model_chain"] = list(chain)
        self.stats["model_switches"] = 0

        key = (api_key or os.getenv("LLM_API_KEY", "")).strip()
        if not key:
            raise LLMUnavailable(".env icinde LLM_API_KEY yok")
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise LLMUnavailable(f"google-genai kurulu degil: {exc}") from None
        self._genai = genai
        self._types = types
        self._client = genai.Client(api_key=key)

    # --- notr bicim -> Gemini bicimi ---------------------------------------

    def _to_contents(self, messages):
        t = self._types
        contents = []
        for m in messages:
            role = m.get("role")
            raw = m.get("_raw")
            if raw is not None and isinstance(raw, t.Content):
                # Modelin kendi turu: thought_signature dahil AYNEN geri gider
                contents.append(raw)
                continue
            if role == "tool":
                contents.append(t.Content(role="user", parts=[
                    t.Part.from_function_response(name=m["name"], response=m["response"])
                ]))
            elif m.get("tool_calls"):
                parts = [t.Part.from_function_call(name=c["name"], args=c.get("args") or {})
                         for c in m["tool_calls"]]
                contents.append(t.Content(role="model", parts=parts))
            else:
                contents.append(t.Content(
                    role="model" if role == "model" else "user",
                    parts=[t.Part.from_text(text=m.get("text", ""))],
                ))
        return contents

    def _to_tools(self, tools):
        t = self._types
        decls = [
            t.FunctionDeclaration(
                name=spec["name"],
                description=spec["description"],
                parameters_json_schema=spec.get("parameters") or {"type": "object", "properties": {}},
            )
            for spec in tools
        ]
        return [t.Tool(function_declarations=decls)]

    # --- ana cagri ----------------------------------------------------------

    def chat_with_tools(self, messages, tools, system=None, temperature=0.0):
        """Model zincirini sirayla dener; kota/404'te sonraki modele gecer."""
        last = None
        for idx, model in enumerate(self.models):
            self.model = model
            self.stats["model"] = model
            try:
                return self._one(model, messages, tools, system, temperature)
            except LLMUnavailable as exc:
                last = exc
                if idx + 1 < len(self.models):
                    self.stats["model_switches"] += 1
                    self.stats["errors"].append(
                        f"{model} -> {self.models[idx + 1]} (sebep: {str(exc)[:80]})")
                    continue
                raise
        raise LLMUnavailable(f"tum modeller basarisiz: {last}")

    def _one(self, model, messages, tools, system=None, temperature=0.0):
        t = self._types
        config = t.GenerateContentConfig(
            tools=self._to_tools(tools) if tools else None,
            automatic_function_calling=t.AutomaticFunctionCallingConfig(disable=True),
            temperature=temperature,
            system_instruction=(f"{system}\n{self.SYSTEM_SUFFIX}" if system else None),
        )
        contents = self._to_contents(messages)

        def call():
            return self._client.models.generate_content(
                model=model, contents=contents, config=config
            )

        resp = self._retry(call)

        usage = getattr(resp, "usage_metadata", None)
        if usage:
            self._account(getattr(usage, "prompt_token_count", 0) or 0,
                          getattr(usage, "candidates_token_count", 0) or 0)

        raw_content = None
        if resp.candidates and resp.candidates[0].content is not None:
            raw_content = resp.candidates[0].content

        calls = [{"name": fc.name, "args": dict(fc.args or {}), "id": None}
                 for fc in (resp.function_calls or [])]
        if calls:
            return {"tool_calls": calls, "final": None, "raw": raw_content}
        return {"tool_calls": [], "final": (resp.text or "").strip(), "raw": raw_content}


# =============================================================================
# Saglayici zinciri
# =============================================================================

PROVIDERS = {"anthropic": AnthropicProvider, "gemini": GeminiProvider}


class ProviderChain:
    """Saglayicilari sirayla dener; biri cokerse sonrakine gecer.

    Agent'in gordugu arayuz tek bir saglayicidan ayirt edilemez.
    Saglayicilar TEMBEL kurulur: yedegin anahtari yoksa ana saglayici
    calistigi surece sorun olmaz.
    """

    name = "chain"

    def __init__(self, order):
        self.order = list(order)
        self._built = {}
        self._active = None
        self._switches = 0
        self._dead = {}

    # --- agent'in okudugu alanlar ---
    @property
    def model(self):
        p = self._built.get(self._active)
        return p.model if p else None

    @property
    def provider_name(self):
        return self._active

    @property
    def stats(self):
        merged = {"provider": self._active or self.order[0], "model": self.model,
                  "requests": 0, "retries": 0, "ms": 0, "tokens": 0,
                  "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0,
                  "errors": [], "chain": list(self.order),
                  "provider_switches": self._switches}
        for name in self.order:
            p = self._built.get(name)
            if not p:
                continue
            for k in ("requests", "retries", "ms", "tokens", "tokens_in",
                      "tokens_out", "cost_usd"):
                merged[k] += p.stats.get(k, 0)
            merged["errors"].extend(f"[{name}] {e}" for e in p.stats.get("errors", []))
        for name, reason in self._dead.items():
            merged["errors"].append(f"[{name}] KULLANILAMADI: {reason}")
        return merged

    def _get(self, name):
        if name in self._built:
            return self._built[name]
        cls = PROVIDERS.get(name)
        if cls is None:
            raise LLMUnavailable(f"bilinmeyen saglayici: {name!r}")
        p = cls()
        self._built[name] = p
        return p

    def chat_with_tools(self, messages, tools, system=None, temperature=0.0):
        last = None
        for name in self.order:
            if name in self._dead:
                continue
            try:
                provider = self._get(name)
            except LLMUnavailable as exc:
                self._dead[name] = str(exc)[:120]
                last = exc
                continue
            if self._active != name:
                if self._active is not None:
                    self._switches += 1
                self._active = name
            try:
                return provider.chat_with_tools(messages, tools, system=system,
                                                temperature=temperature)
            except LLMUnavailable as exc:
                self._dead[name] = str(exc)[:120]
                last = exc
                continue
        raise LLMUnavailable(f"tum saglayicilar basarisiz: {last}")


def provider_order(primary=None):
    """LLM_PROVIDER once, sonra kalan saglayicilar (yedek)."""
    load_dotenv(ENV_PATH)
    primary = (primary or os.getenv("LLM_PROVIDER", "anthropic")).strip().lower()
    order = [primary] if primary in PROVIDERS else []
    for name in ("anthropic", "gemini"):
        if name not in order:
            order.append(name)
    return order


def get_provider(name=None, model=None):
    """Zincir dondurur: LLM_PROVIDER -> diger saglayicilar -> LLMUnavailable."""
    order = provider_order(name)
    chain = ProviderChain(order)
    if model:
        # Tek saglayici + sabit model istenmisse zinciri atla
        cls = PROVIDERS.get(order[0])
        if cls:
            return cls(model=model)
    return chain
