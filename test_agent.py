"""
test_agent.py — agent dongusunun AGSIZ testleri.

Sahte LLM saglayici (FakeProvider) ve sahte veri kaynaklari (FakeDeps) ile:
hicbir ATK cagrisi, hicbir RPC istegi, hicbir Gemini istegi yapilmaz.
Imza gercekten uretilir ama anvil TEST anahtariyla (gercek oracle anahtari
testlere girmez).
"""

import time

import pytest

import agent
import llm as llm_mod
import signer

SYMBOL = "ZBCN-USDT"
TEST_CONTRACT = "0xddE4C78F831f082E8AFDF716266bd1338B591159"

# ask: 100 x 1, 101 x 1, 102 x 1 | bid: 99/98/97 x 1 -> mid 99.5
# maxSafeSize(buy, %1) = 199.0 USDT (test_metrics.py'de elle dogrulandi)
BOOK = {
    "asks": [["100", "1", "0", "1"], ["101", "1", "0", "1"], ["102", "1", "0", "1"]],
    "bids": [["99", "1", "0", "1"], ["98", "1", "0", "1"], ["97", "1", "0", "1"]],
}
MAX_SAFE_USDT = 199.0

CANDLES = [[str(1760000000000 + i * 60000), "1", "1", "1", str(100 + (i % 3)),
            "10", "1000", "0", "1"] for i in range(60)]


class FakeDeps:
    def __init__(self, book=BOOK, age_s=1.0, ok=True, memory_points=60,
                 threshold=5000, symbols=(SYMBOL,)):
        self.book, self.age_s, self.ok = book, age_s, ok
        self.memory_points = memory_points
        self.threshold = threshold
        self.symbols = set(symbols)
        self.sign_calls = 0

    def live_symbols(self):
        return self.symbols

    def orderbook(self, symbol):
        return {"ok": self.ok, "data": self.book if self.ok else None,
                "error": None if self.ok else "CLI hatasi",
                "fetched_at": time.time() - self.age_s, "latency_ms": 10}

    def candles(self, symbol, n):
        return {"ok": True, "data": CANDLES[:n], "error": None,
                "fetched_at": time.time(), "latency_ms": 10}

    def memory(self, symbol):
        n = self.memory_points
        return {"n": n, "mids": [99.5] * n, "depths": [400.0] * n, "error": None}

    def pairs(self):
        return [SYMBOL]

    def risk_threshold(self):
        return self.threshold, "test"

    def contract_address(self):
        return TEST_CONTRACT

    def sign(self, symbol, side, risk_score, max_safe_usdt, timestamp):
        self.sign_calls += 1
        return signer.sign_attestation(
            private_key_hex=signer.ANVIL_TEST_KEY, symbol=symbol, side=side,
            risk_score=risk_score, max_safe_size_usdt=max_safe_usdt,
            timestamp=timestamp, chain_id=43113, contract_addr=TEST_CONTRACT,
        )


class FakeProvider:
    """Senaryo listesini sirayla dondurur. Liste bitince son ogeyi tekrarlar."""

    name = "fake"

    def __init__(self, script, model="fake-1", raise_on=None):
        self.script = list(script)
        self.model = model
        self.raise_on = raise_on  # kacinci cagride LLMUnavailable atilacak (1-tabanli)
        self.calls = 0
        self.stats = {"provider": "fake", "model": model, "requests": 0,
                      "retries": 0, "ms": 0, "tokens": 0, "errors": []}

    def chat_with_tools(self, messages, tools, system=None, temperature=0.0):
        self.calls += 1
        self.stats["requests"] += 1
        if self.raise_on and self.calls >= self.raise_on:
            raise llm_mod.LLMUnavailable("test: saglayici kullanilamiyor")
        step = self.script[min(self.calls - 1, len(self.script) - 1)]
        return step


def tool_step(name, args):
    return {"tool_calls": [{"name": name, "args": args}], "final": None}


def final_step(decision, hipotez="test", guven="orta"):
    import json
    return {"tool_calls": [], "final": json.dumps({
        "hipotez": hipotez, "kanit": ["sentetik tahta"], "guven": guven,
        "karar_onerisi": decision, "gerekce": "test",
    })}


def metric_call(size):
    return tool_step("compute_metric", {"symbol": SYMBOL, "side": "buy", "size_usdt": size})


# =============================================================================
# Muhafazakar birlestirme
# =============================================================================

def test_llm_loose_suggestion_is_ignored():
    """Deterministik BOL, LLM ONAY diyor -> BOL kazanir, trace'e yazilir.

    250 USDT: maxSafeSize 199'un ustunde ama riskScore 3790 esigin altinda,
    yani karar BOL (RED degil) -- degerler sentetik tahtada olculdu.
    """
    deps = FakeDeps()
    provider = FakeProvider([metric_call(250.0), final_step("ONAY")])
    res = agent.run_check(SYMBOL, "buy", 250.0, provider=provider, deps=deps)

    assert res["deterministic_decision"] == "BOL"
    assert res["llm_suggestion"] == "ONAY"
    assert res["decision"] == "BOL"
    assert "reddedildi" in res["merge_note"]


def test_llm_strict_suggestion_wins():
    """Deterministik ONAY, LLM RED diyor -> RED kazanir."""
    deps = FakeDeps()
    provider = FakeProvider([metric_call(100.0), final_step("RED")])
    res = agent.run_check(SYMBOL, "buy", 100.0, provider=provider, deps=deps)

    assert res["deterministic_decision"] == "ONAY"
    assert res["decision"] == "RED"
    assert "kazandi" in res["merge_note"]


def test_llm_veri_yetersiz_suggestion_blocks_signature():
    """LLM en muhafazakari secerse imza da uretilmez."""
    deps = FakeDeps()
    provider = FakeProvider([metric_call(100.0), final_step("VERI_YETERSIZ")])
    res = agent.run_check(SYMBOL, "buy", 100.0, provider=provider, deps=deps)

    assert res["decision"] == "VERI_YETERSIZ"
    assert res["signed_attestation"] is None
    assert deps.sign_calls == 0


def test_merge_decisions_table():
    for det, sug, expected in [
        ("ONAY", "BOL", "BOL"), ("BOL", "ONAY", "BOL"), ("RED", "VERI_YETERSIZ", "VERI_YETERSIZ"),
        ("VERI_YETERSIZ", "ONAY", "VERI_YETERSIZ"), ("ONAY", None, "ONAY"),
        ("ONAY", "SACMA", "ONAY"), ("BOL", "BOL", "BOL"),
    ]:
        final, _note = agent.merge_decisions(det, sug)
        assert final == expected, f"{det}+{sug} -> {final}, beklenen {expected}"


# =============================================================================
# Butce
# =============================================================================

def test_budget_is_enforced():
    """LLM surekli arac cagiriyor -> 12'de kesilir, karar deterministik gelir."""
    deps = FakeDeps()
    provider = FakeProvider([tool_step("get_orderbook", {"symbol": SYMBOL})])
    res = agent.run_check(SYMBOL, "buy", 250.0, provider=provider, deps=deps)

    assert res["tool_calls_used"] <= agent.TOOL_BUDGET + 1  # +1: zorunlu metrik
    assert any("butce doldu" in e["summary"] for e in res["trace"] if e["tool"] is None)
    # LLM hic metrik olcmedi ama karar yine deterministik verildi
    assert res["decision"] == "BOL"
    assert res["riskScore"] is not None


def test_budget_respects_custom_value():
    deps = FakeDeps()
    provider = FakeProvider([tool_step("get_orderbook", {"symbol": SYMBOL})])
    res = agent.run_check(SYMBOL, "buy", 100.0, provider=provider, deps=deps, budget=3)
    tool_steps = [e for e in res["trace"] if e["tool"]]
    assert len(tool_steps) <= 4  # 3 butce + zorunlu metrik


# =============================================================================
# LLM yok / bozuk
# =============================================================================

def test_llm_unavailable_falls_back_to_deterministic_plan():
    deps = FakeDeps()
    provider = FakeProvider([], raise_on=1)
    res = agent.run_check(SYMBOL, "buy", 100.0, provider=provider, deps=deps)

    assert res["llm"]["mode"] == "deterministik (LLM kesildi)"
    tools = [e["tool"] for e in res["trace"] if e["tool"]]
    assert tools[:4] == ["get_orderbook", "get_candles", "compute_metric", "sign_score"]
    assert res["decision"] == "ONAY"
    assert res["signed_attestation"] is not None


def test_no_llm_flag_uses_deterministic_plan():
    deps = FakeDeps()
    res = agent.run_check(SYMBOL, "buy", 100.0, deps=deps, use_llm=False)
    assert res["llm"]["mode"] == "deterministik (--no-llm)"
    assert res["llm_suggestion"] is None
    assert res["decision"] == "ONAY"


def test_invalid_final_json_gets_one_correction():
    deps = FakeDeps()
    provider = FakeProvider([
        metric_call(100.0),
        {"tool_calls": [], "final": "bu JSON degil"},
        final_step("ONAY"),
    ])
    res = agent.run_check(SYMBOL, "buy", 100.0, provider=provider, deps=deps)
    assert res["llm_final"] is not None
    assert any("duzeltme istendi" in e["summary"] for e in res["trace"] if e["tool"] is None)


def test_invalid_final_json_twice_falls_back():
    deps = FakeDeps()
    provider = FakeProvider([
        metric_call(100.0),
        {"tool_calls": [], "final": "hala JSON degil"},
    ])
    res = agent.run_check(SYMBOL, "buy", 100.0, provider=provider, deps=deps)
    assert res["llm_final"] is None
    assert res["llm_suggestion"] is None
    assert res["decision"] == "ONAY"  # deterministik yedek
    assert any("deterministik yedek" in e["summary"] for e in res["trace"] if e["tool"] is None)


def test_bad_confidence_is_rejected():
    import json
    deps = FakeDeps()
    bad = {"tool_calls": [], "final": json.dumps({
        "hipotez": "x", "kanit": [], "guven": "cok_yuksek",
        "karar_onerisi": "ONAY", "gerekce": "y"})}
    provider = FakeProvider([metric_call(100.0), bad])
    res = agent.run_check(SYMBOL, "buy", 100.0, provider=provider, deps=deps)
    assert res["llm_final"] is None


# =============================================================================
# Fail-closed
# =============================================================================

def test_insufficient_data_means_no_signature():
    deps = FakeDeps(age_s=121)
    provider = FakeProvider([metric_call(100.0), final_step("ONAY")])
    res = agent.run_check(SYMBOL, "buy", 100.0, provider=provider, deps=deps)

    assert res["status"] == "INSUFFICIENT_DATA"
    assert res["decision"] == "VERI_YETERSIZ"
    assert res["signed_attestation"] is None
    assert res["riskScore"] is None
    assert deps.sign_calls == 0


def test_cli_failure_means_no_signature():
    deps = FakeDeps(ok=False)
    res = agent.run_check(SYMBOL, "buy", 100.0, deps=deps, use_llm=False)
    assert res["decision"] == "VERI_YETERSIZ"
    assert res["signed_attestation"] is None


def test_limited_memory_still_decides():
    deps = FakeDeps(memory_points=5)
    res = agent.run_check(SYMBOL, "buy", 100.0, deps=deps, use_llm=False)
    assert res["status"] == "OK_LIMITED_MEMORY"
    assert res["decision"] == "ONAY"
    assert res["signed_attestation"] is not None


# =============================================================================
# LLM sayilari etkileyemez
# =============================================================================

def test_llm_numbers_never_reach_the_result():
    """LLM uydurma sayilar yazsin ve baska bir tutarla olcum yapsin:
    sonuctaki riskScore/maxSafeSize yine istenen niyetin olcumunden gelir."""
    deps = FakeDeps()
    provider = FakeProvider([
        metric_call(5.0),       # yetkili OLMAYAN olcum (baska tutar)
        metric_call(250.0),     # yetkili olcum
        final_step("ONAY", hipotez="maxSafeSize 999999 USDT ve riskScore 0"),
    ])
    res = agent.run_check(SYMBOL, "buy", 250.0, provider=provider, deps=deps)

    assert res["maxSafeSize"] == pytest.approx(MAX_SAFE_USDT)
    assert res["riskScore"] != 0
    assert res["decision"] == "BOL"               # 250 > 199
    assert "999999" in res["llm_final"]["hipotez"]  # LLM metni duruyor
    assert res["signed_attestation"]["maxSafeSize"] == signer.to_usdt_units(MAX_SAFE_USDT)


def test_signature_numbers_come_from_metric():
    deps = FakeDeps()
    res = agent.run_check(SYMBOL, "buy", 100.0, deps=deps, use_llm=False)
    att = res["signed_attestation"]
    assert att["riskScore"] == res["riskScore"]
    assert att["maxSafeSize"] == signer.to_usdt_units(res["maxSafeSize"])
    assert att["symbol"] == SYMBOL and att["side"] == "buy"


def test_sign_score_before_metric_is_refused():
    deps = FakeDeps()
    session = agent.AgentSession(SYMBOL, "buy", 100.0, deps=deps)
    out = session.call_tool("sign_score", {})
    assert out["ok"] is False
    assert "compute_metric" in out["error"]
    assert deps.sign_calls == 0


# =============================================================================
# Sembol dogrulama
# =============================================================================

def test_invalid_symbol_is_rejected_before_llm():
    deps = FakeDeps()
    provider = FakeProvider([final_step("ONAY")])
    for bad in ("zbcn-usdt", "ZBCN-USD", "ZBCN/USDT", "XAAPL-USDT", ""):
        res = agent.run_check(bad, "buy", 100.0, provider=provider, deps=deps)
        assert res["decision"] == "VERI_YETERSIZ", bad
        assert "sembol" in res["reason"]
        assert res["trace"] == []
    assert provider.calls == 0  # LLM'e hic gidilmedi


def test_tool_rejects_symbol_outside_live_list():
    deps = FakeDeps()
    session = agent.AgentSession(SYMBOL, "buy", 100.0, deps=deps)
    out = session.call_tool("get_orderbook", {"symbol": "FAKE-USDT"})
    assert out["ok"] is False
    assert "live" in out["error"]


def test_unknown_tool_is_reported():
    deps = FakeDeps()
    session = agent.AgentSession(SYMBOL, "buy", 100.0, deps=deps)
    out = session.call_tool("drop_table", {})
    assert out["ok"] is False and "bilinmeyen arac" in out["error"]


def test_bad_side_raises():
    with pytest.raises(ValueError):
        agent.run_check(SYMBOL, "long", 100.0, deps=FakeDeps(), use_llm=False)


# =============================================================================
# Bolme onerisi
# =============================================================================

def test_split_suggestion_parts_match_contract_formula():
    text = agent.split_suggestion("BOL", 10000.0, 1000.0)
    assert "10 parca" in text
    assert agent.split_suggestion("ONAY", 10000.0, 1000.0) is None
    assert "guvenli tutar yok" in agent.split_suggestion("BOL", 10000.0, 0.0)


def test_split_suggestion_in_result():
    deps = FakeDeps()
    res = agent.run_check(SYMBOL, "buy", 250.0, deps=deps, use_llm=False)
    assert res["decision"] == "BOL"
    # 250 / 199.0 -> 2 parca
    assert "2 parca" in res["split_suggestion"]


def test_high_risk_is_rejected_by_threshold():
    deps = FakeDeps(threshold=100)  # cok sert esik
    res = agent.run_check(SYMBOL, "buy", 100.0, deps=deps, use_llm=False)
    assert res["decision"] == "RED"
    assert res["signed_attestation"] is not None  # imza var, zincir reddedecek


def test_unfillable_size_is_red_not_bol():
    """Tahta tutari hic karsilamiyorsa risk skoru esigi asiyor ve kontrattaki
    sirayla RED, BOL'dan ONCE geliyor (1000 USDT, tahtada 303 USDT var)."""
    deps = FakeDeps()
    res = agent.run_check(SYMBOL, "buy", 1000.0, deps=deps, use_llm=False)
    assert res["riskScore"] > deps.threshold
    assert res["decision"] == "RED"
    assert res["split_suggestion"] is None  # RED'de bolme onerisi yok
    # tahta 303 USDT tasiyor; istenen 1000 -> dolum yok, no_fill bileseni dolu
    metric_steps = [e for e in res["trace"] if e["tool"] == "compute_metric"]
    assert '"fills": false' in metric_steps[-1]["summary"]


# =============================================================================
# Saglayici zinciri (anthropic -> gemini -> deterministik)
# =============================================================================

class FailingProvider(llm_mod.BaseProvider):
    """Her cagrida kota hatasi veren saglayici (ana saglayici taklidi)."""

    name = "anthropic"

    def __init__(self, model=None):
        super().__init__(model=model or "fail-1")

    def chat_with_tools(self, messages, tools, system=None, temperature=0.0):
        self.stats["requests"] += 1
        raise llm_mod.LLMUnavailable("test: kota bitti (per day)")


class ScriptedProvider(llm_mod.BaseProvider):
    """Senaryoyu sirayla donduren saglayici (yedek taklidi)."""

    name = "gemini"
    script = [metric_call(100.0), final_step("ONAY")]

    def __init__(self, model=None):
        super().__init__(model=model or "work-1")
        self.calls = 0

    def chat_with_tools(self, messages, tools, system=None, temperature=0.0):
        self.calls += 1
        self.stats["requests"] += 1
        self.stats["tokens"] += 10
        self.stats["tokens_in"] += 8
        self.stats["tokens_out"] += 2
        return self.script[min(self.calls - 1, len(self.script) - 1)]


@pytest.fixture
def chain_providers(monkeypatch):
    """llm.PROVIDERS'i sahte saglayicilarla degistirir (ag yok)."""
    def _apply(first, second):
        monkeypatch.setattr(llm_mod, "PROVIDERS", {"anthropic": first, "gemini": second})
        return llm_mod.ProviderChain(["anthropic", "gemini"])
    return _apply


def test_provider_chain_falls_back_to_second(chain_providers):
    chain = chain_providers(FailingProvider, ScriptedProvider)
    out = chain.chat_with_tools([{"role": "user", "text": "x"}], tools=[])

    assert out["tool_calls"][0]["name"] == "compute_metric"
    assert chain.provider_name == "gemini"
    st = chain.stats
    assert st["provider"] == "gemini"
    assert st["requests"] == 2            # 1 basarisiz + 1 basarili
    assert any("anthropic" in e for e in st["errors"])


def test_provider_chain_all_fail_raises(chain_providers):
    chain = chain_providers(FailingProvider, FailingProvider)
    with pytest.raises(llm_mod.LLMUnavailable):
        chain.chat_with_tools([{"role": "user", "text": "x"}], tools=[])


def test_provider_chain_skips_dead_provider_on_next_call(chain_providers):
    """Olu saglayici bir daha denenmez (kota bosa yakilmasin)."""
    chain = chain_providers(FailingProvider, ScriptedProvider)
    chain.chat_with_tools([{"role": "user", "text": "x"}], tools=[])
    before = chain.stats["requests"]
    chain.chat_with_tools([{"role": "user", "text": "y"}], tools=[])
    # ikinci turda yalnizca calisan saglayiciya gidildi
    assert chain.stats["requests"] == before + 1


def test_agent_uses_chain_fallback(chain_providers):
    """anthropic coker -> gemini planlar -> karar ve imza uretilir."""
    chain = chain_providers(FailingProvider, ScriptedProvider)
    res = agent.run_check(SYMBOL, "buy", 100.0, provider=chain, deps=FakeDeps())

    assert res["decision"] == "ONAY"
    assert res["llm"]["provider"] == "gemini"
    assert res["llm"]["chain"] == ["anthropic", "gemini"]
    assert res["llm_suggestion"] == "ONAY"
    assert res["signed_attestation"] is not None
    assert res["llm"]["mode"] == "LLM planlayici"


def test_agent_chain_all_fail_goes_deterministic(chain_providers):
    chain = chain_providers(FailingProvider, FailingProvider)
    res = agent.run_check(SYMBOL, "buy", 100.0, provider=chain, deps=FakeDeps())

    assert res["llm"]["mode"] == "deterministik (LLM kesildi)"
    tools = [e["tool"] for e in res["trace"] if e["tool"]]
    assert tools[:4] == ["get_orderbook", "get_candles", "compute_metric", "sign_score"]
    assert res["decision"] == "ONAY"
    assert res["signed_attestation"] is not None


def test_provider_order_puts_env_provider_first(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    assert llm_mod.provider_order()[0] == "gemini"
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    assert llm_mod.provider_order()[0] == "anthropic"
    # bilinmeyen ad -> varsayilan sira, cokme yok
    monkeypatch.setenv("LLM_PROVIDER", "sacma")
    assert llm_mod.provider_order() == ["anthropic", "gemini"]


def test_cost_estimate_matches_official_prices():
    # Haiku 5.5 (<=100k prompt): girdi $0.10/MTok, cikti $0.50/MTok
    cost = llm_mod.estimate_cost_usd("claude-haiku-5-5", 1_000_000, 1_000_000)
    assert cost == pytest.approx(0.60)
    assert llm_mod.estimate_cost_usd("bilinmeyen-model", 1000, 1000) is None


def test_anthropic_tool_result_conversion_keeps_ids():
    """tool_use id'si tool_result'a aynen tasinmali (resmi dokuman kurali).

    `_to_messages` saf cevrim yaptigi icin self kullanmiyor; None ile cagrilir
    (saglayici kurmak API anahtari isteyecekti, test ag kullanmaz).
    """
    msgs = [
        {"role": "user", "text": "olc"},
        {"role": "model", "tool_calls": [{"name": "compute_metric", "args": {}, "id": "toolu_42"}]},
        {"role": "tool", "name": "compute_metric", "id": "toolu_42", "response": {"ok": True}},
    ]
    out = llm_mod.AnthropicProvider._to_messages(None, msgs)
    assert out[1]["role"] == "assistant"
    assert out[1]["content"][0]["id"] == "toolu_42"
    assert out[2]["content"][0]["tool_use_id"] == "toolu_42"
    assert out[2]["content"][0].get("is_error") is None


def test_anthropic_marks_failed_tool_results_as_error():
    msgs = [{"role": "tool", "name": "get_orderbook", "id": "toolu_7",
             "response": {"ok": False, "error": "tahta yok"}}]
    out = llm_mod.AnthropicProvider._to_messages(None, msgs)
    assert out[0]["content"][0]["is_error"] is True


# =============================================================================
# Fail-closed: veri kesintisi simulasyonu (ARF_FEED_DOWN=1)
# =============================================================================

class FeedDownDeps(FakeDeps):
    """Tahta ve mumlari GERCEK atk_client'tan ister.

    ARF_FEED_DOWN=1 iken atk_client CLI'yi hic cagirmaz, ok=False doner;
    boylece env -> atk_client -> metrics -> agent zinciri butunuyle test edilir
    (ag yok, subprocess yok).
    """

    def orderbook(self, symbol):
        import atk_client
        return atk_client.get_orderbook(symbol)

    def candles(self, symbol, n):
        import atk_client
        return atk_client.get_candles(symbol, n)


def test_atk_client_returns_not_ok_when_feed_down(monkeypatch):
    import atk_client
    monkeypatch.setenv(atk_client.FEED_DOWN_ENV, "1")
    assert atk_client.feed_down() is True
    for res in (atk_client.get_orderbook(SYMBOL),
                atk_client.get_ticker(SYMBOL),
                atk_client.get_candles(SYMBOL, 10),
                atk_client.get_tickers_spot(),
                atk_client.get_instruments_spot()):
        assert res["ok"] is False
        assert res["data"] is None
        assert "SIMULASYON" in res["error"]
        assert res["fetched_at"] > 0      # yas hesabi yine calisiyor


def test_feed_down_off_by_default(monkeypatch):
    import atk_client
    monkeypatch.delenv(atk_client.FEED_DOWN_ENV, raising=False)
    assert atk_client.feed_down() is False


def test_agent_fails_closed_when_feed_down(monkeypatch):
    """Veri kesilince: VERI_YETERSIZ, imza YOK, riskScore/maxSafeSize None."""
    import atk_client
    monkeypatch.setenv(atk_client.FEED_DOWN_ENV, "1")
    deps = FeedDownDeps()
    res = agent.run_check(SYMBOL, "buy", 1000.0, deps=deps, use_llm=False)

    assert res["status"] == "INSUFFICIENT_DATA"
    assert res["decision"] == "VERI_YETERSIZ"
    assert res["signed_attestation"] is None
    assert res["riskScore"] is None and res["maxSafeSize"] is None
    assert deps.sign_calls == 0
    assert "SIMULASYON" in str(res["trace"])


def test_agent_fails_closed_even_if_llm_says_onay(monkeypatch):
    """LLM 'ONAY' dese bile veri yoksa imza uretilmez (LLM gevsek kalir)."""
    import atk_client
    monkeypatch.setenv(atk_client.FEED_DOWN_ENV, "1")
    deps = FeedDownDeps()
    provider = FakeProvider([metric_call(1000.0), final_step("ONAY")])
    res = agent.run_check(SYMBOL, "buy", 1000.0, provider=provider, deps=deps)

    assert res["llm_suggestion"] == "ONAY"
    assert res["decision"] == "VERI_YETERSIZ"
    assert res["signed_attestation"] is None
    assert deps.sign_calls == 0


def test_sign_score_tool_refuses_when_feed_down(monkeypatch):
    import atk_client
    monkeypatch.setenv(atk_client.FEED_DOWN_ENV, "1")
    deps = FeedDownDeps()
    session = agent.AgentSession(SYMBOL, "buy", 1000.0, deps=deps)
    session.call_tool("compute_metric", {"symbol": SYMBOL, "side": "buy",
                                         "size_usdt": 1000.0})
    out = session.call_tool("sign_score", {})
    assert out["ok"] is False
    assert "INSUFFICIENT_DATA" in out["error"]
    assert deps.sign_calls == 0


def test_recovery_after_feed_comes_back(monkeypatch):
    """Besleme donunce ayni oturum yeniden karar verebiliyor (kalici kilit yok)."""
    import atk_client
    monkeypatch.setenv(atk_client.FEED_DOWN_ENV, "1")
    down = agent.run_check(SYMBOL, "buy", 100.0, deps=FeedDownDeps(), use_llm=False)
    assert down["decision"] == "VERI_YETERSIZ"

    monkeypatch.delenv(atk_client.FEED_DOWN_ENV, raising=False)
    up = agent.run_check(SYMBOL, "buy", 100.0, deps=FakeDeps(), use_llm=False)
    assert up["decision"] == "ONAY"
    assert up["signed_attestation"] is not None
