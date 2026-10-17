"""
llm.py — saglayicidan bagimsiz function-calling arayuzu.

Tek giris: provider.chat_with_tools(messages, tools)
  -> {"tool_calls": [{"name", "args"}], "final": None}
  -> {"tool_calls": [], "final": "<metin>"}

Notr mesaj bicimi (saglayici ne olursa olsun ayni):
  {"role": "user",  "text": "..."}
  {"role": "model", "text": "..."}
  {"role": "model", "tool_calls": [{"name": ..., "args": {...}}], "_raw": <opak>}
  {"role": "tool",  "name": ..., "response": {...}}

`_raw`: saglayicinin o turda dondurdugu HAM nesne. Cagiran onu anlamaz,
sadece geri verir. Gemini 3.x icin ZORUNLU (bkz. OLCULEN notu).

Notr arac bicimi:
  {"name": ..., "description": ..., "parameters": <JSON Schema>}

Su an yalnizca Gemini var; Anthropic/OpenAI eklemek icin BaseProvider'dan
turetip _call() yazmak yeterli.

OLCULEN (2026-10-17, gercek API):
  * `gemini-2.5-flash` ve `-lite`: generateContent 404
    ("no longer available to new users" -> models/gemini-3.8-flash).
    models.list onlari yine listeliyor; liste YETERLI KANIT DEGIL.
  * `gemini-3.8-flash`: function calling CALISIYOR (4/5 tur tam basarili).
  * 5. tur `503 UNAVAILABLE` ("high demand") verdi -> gecici sunucu hatasi
    429'dan daha olasi; ikisi de tekrar denenir.
  * Gecikme: 2129-5695 ms, ortalama 3822 ms (tur basina ~240 token).
  * Arac dongusunde modelin turunu YENIDEN KURMAK 400 INVALID_ARGUMENT
    veriyor: "Function call is missing a thought_signature in functionCall
    parts". Resmi doküman (ai.google.dev/gemini-api/docs/thinking#signatures):
    model parcalari gecmise AYNEN geri konulmali. Bu yuzden ham Content
    `_raw` olarak tasinir ve degistirilmeden geri verilir.

GIZLILIK: API anahtari .env'den okunur, hicbir yere yazilmaz.
"""

import os
import time

from dotenv import load_dotenv

ENV_PATH = ".env"

# Model zinciri: biri kota/404 verirse sonrakine gecilir (RPC yedeklemesi gibi).
# Kota MODEL BASINA sayildigi icin bu gercek bir yedek, kozmetik degil.
# OLCULDU (2026-10-17): ucu de function calling yapiyor; gecikme
# 3.5-flash-lite 809 ms < 3.5-flash 1701 ms < 3.7-flash 6129 ms.
# 3.8-flash o gun 20 istek kotasini tukettigi icin zincirin SONUNA alindi.
DEFAULT_GEMINI_MODELS = ("gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.8-flash")
DEFAULT_GEMINI_MODEL = DEFAULT_GEMINI_MODELS[0]

# --- VARSAYIM: tekrar deneme politikasi ------------------------------------
MAX_RETRIES = 2                  # ilk denemeden sonra en fazla 2 deneme
RETRY_BACKOFF_S = (2.0, 5.0)     # artan bekleme
RETRYABLE_SUBSTRINGS = ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE",
                        "500", "INTERNAL", "504", "DEADLINE")

# GUNLUK kota bittiginde tekrar denemek anlamsiz (API "11h sonra" diyor) ve
# her deneme kotadan bir istek daha yakiyor -> hemen LLMUnavailable.
# OLCULDU: ucretsiz katmanda gemini-3.8-flash gunluk 20 istek
# (quotaId GenerateRequestsPerDayPerProjectPerModel-FreeTier), kota MODEL BASINA.
FATAL_SUBSTRINGS = ("PerDayPerProject", "free_tier_requests", "per day",
                    "billing", "API_KEY_INVALID", "PERMISSION_DENIED", "404")


class LLMUnavailable(RuntimeError):
    """LLM kullanilamiyor (kota/kesinti/yapilandirma). Agent deterministik plana doner."""


class BaseProvider:
    name = "base"

    def __init__(self, model=None):
        self.model = model
        self.stats = {"provider": self.name, "model": model, "requests": 0,
                      "retries": 0, "ms": 0, "tokens": 0, "errors": []}

    def chat_with_tools(self, messages, tools):
        raise NotImplementedError

    def _retry(self, fn):
        """429/503/500 gibi gecici hatalarda artan beklemeyle tekrar dener."""
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
        self.stats["model"] = model

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
        if usage and getattr(usage, "total_token_count", None):
            self.stats["tokens"] += usage.total_token_count

        raw_content = None
        if resp.candidates and resp.candidates[0].content is not None:
            raw_content = resp.candidates[0].content

        calls = [{"name": fc.name, "args": dict(fc.args or {})}
                 for fc in (resp.function_calls or [])]
        if calls:
            return {"tool_calls": calls, "final": None, "raw": raw_content}
        return {"tool_calls": [], "final": (resp.text or "").strip(), "raw": raw_content}


def get_provider(name=None, model=None):
    """LLM_PROVIDER'a gore saglayici dondurur. Bilinmeyen ad -> LLMUnavailable."""
    load_dotenv(ENV_PATH)
    name = (name or os.getenv("LLM_PROVIDER", "gemini")).strip().lower()
    if name == "gemini":
        return GeminiProvider(model=model)
    raise LLMUnavailable(f"bilinmeyen LLM_PROVIDER: {name!r}")
