"""
test_app_safety.py — "zincire gonderme" kapaliyken GERCEKTEN gonderilmedigini
garanti eden regresyon testleri. Ag yok: chain fonksiyonlari sahteleniyor.

Neden var: `chain.simulate_only` bir donem adina ragmen, eth_call GECTIGINDE
tx gonderiyordu (execute_intent'teki erken donus yalnizca revert halinde
vardi). app.py sahne 1'in headless denemesinde bu yuzden istenmeyen bir
gercek tx gitti (Fuji tx 0x82f9fd48...702b). `dry_run` bayragi eklendi; bu
testler o yolu kilitliyor.
"""

import pytest

import app
import chain


# =============================================================================
# chain.simulate_only her zaman dry_run ile cagirmali
# =============================================================================

def test_simulate_only_passes_dry_run(monkeypatch):
    captured = {}

    def fake_execute(symbol, side, amount_usdt, attestation, **kwargs):
        captured.update(kwargs)
        return {"status": "SIMULATED_OK", "sent": False}

    monkeypatch.setattr(chain, "execute_intent", fake_execute)
    chain.simulate_only("ZBCN-USDT", "buy", 1000.0, {"digest": "0x00"})

    assert captured["dry_run"] is True
    assert captured["force_onchain"] is False


def test_execute_intent_has_dry_run_parameter():
    import inspect
    params = inspect.signature(chain.execute_intent).parameters
    assert "dry_run" in params
    assert params["dry_run"].default is False


# =============================================================================
# app.run_scene: send=False iken execute_intent'e HIC gidilmemeli
# =============================================================================

MINIMAL_RES = {
    "symbol": "ZBCN-USDT", "side": "buy", "size_usdt": 1000.0,
    "decision": "ONAY", "deterministic_decision": "ONAY", "llm_suggestion": None,
    "merge_note": "-", "reason": "-", "riskScore": 1000, "maxSafeSize": 5000.0,
    "riskThreshold": 5000, "slippage_bps_at_size": 10.0, "status": "OK",
    "split_suggestion": None,
    "signed_attestation": {"digest": "0xabc", "signer": "0x01",
                           "riskScore": 1000, "maxSafeSize": 5000000000,
                           "maxSafeSizeUsdt": 5000.0, "symbol": "ZBCN-USDT",
                           "side": "buy", "sideInt": 0, "timestamp": 1,
                           "signature": "0x00"},
    "llm": {"mode": "deterministik (--no-llm)"}, "llm_final": None,
    "trace": [], "tool_calls_used": 0, "data_age_s": 0.1, "total_ms": 10,
    "memory_points": 60,
}


@pytest.fixture
def no_send_guard(monkeypatch):
    """execute_intent cagrilirsa test patlar; simulate_only sayilir."""
    calls = {"simulate": 0}

    def boom(*args, **kwargs):
        raise AssertionError("send=False iken execute_intent cagrildi!")

    def fake_simulate(symbol, side, amount, att, **kwargs):
        calls["simulate"] += 1
        return {"status": "SIMULATED_REVERT", "sent": False,
                "error_text": "ExceedsSafeSize(...)", "error": {"args": {}},
                "gas_used": None, "confirm_ms": None, "explorer": None}

    monkeypatch.setattr(app.chain, "execute_intent", boom)
    monkeypatch.setattr(app.chain, "simulate_only", fake_simulate)
    return calls


def test_scene1_does_not_send_when_send_false(monkeypatch, no_send_guard):
    monkeypatch.setattr(app.agent, "run_check", lambda *a, **k: dict(MINIMAL_RES))
    out = app.run_scene(1, "ZBCN-USDT", use_llm=False, send=False)
    assert out["error"] is None
    assert no_send_guard["simulate"] == 1
    assert out["chain"]["sent"] is False


def test_scene2_does_not_send_when_send_false(monkeypatch, no_send_guard):
    res = dict(MINIMAL_RES, decision="BOL", deterministic_decision="BOL",
               split_suggestion="2 parca")
    monkeypatch.setattr(app.agent, "run_check", lambda *a, **k: res)
    out = app.run_scene(2, "ZBCN-USDT", use_llm=False, send=False)
    assert out["error"] is None
    assert no_send_guard["simulate"] == 1


def test_scene3_does_not_send_when_send_false(monkeypatch, no_send_guard):
    res = dict(MINIMAL_RES, decision="VERI_YETERSIZ", deterministic_decision="VERI_YETERSIZ",
               status="INSUFFICIENT_DATA", riskScore=None, maxSafeSize=None,
               signed_attestation=None)
    monkeypatch.setattr(app.agent, "run_check", lambda *a, **k: res)
    monkeypatch.setattr(app.chain, "sign_attestation_with_trader",
                        lambda *a, **k: {"signer": "0xtrader", "digest": "0x0"})
    out = app.run_scene(3, "ZBCN-USDT", use_llm=False, send=False)
    assert out["error"] is None
    assert no_send_guard["simulate"] == 1
    assert out["trader_signer"] == "0xtrader"


def test_scene3_sets_and_clears_feed_down_env(monkeypatch, no_send_guard):
    import atk_client
    seen = {}

    def spy_run_check(symbol, side, size, **kwargs):
        seen["feed_down_during_run"] = atk_client.feed_down()
        return dict(MINIMAL_RES, decision="VERI_YETERSIZ", signed_attestation=None,
                    status="INSUFFICIENT_DATA", riskScore=None, maxSafeSize=None)

    monkeypatch.setattr(app.agent, "run_check", spy_run_check)
    monkeypatch.setattr(app.chain, "sign_attestation_with_trader",
                        lambda *a, **k: {"signer": "0xtrader", "digest": "0x0"})
    monkeypatch.delenv(atk_client.FEED_DOWN_ENV, raising=False)

    app.run_scene(3, "ZBCN-USDT", use_llm=False, send=False)

    assert seen["feed_down_during_run"] is True      # kosu sirasinda acik
    assert atk_client.feed_down() is False           # kosudan sonra temizlendi


def test_scene_error_does_not_crash(monkeypatch):
    """Kosu patlarsa ekran cokmez: hata sozlukte doner."""
    def boom(*a, **k):
        raise RuntimeError("test patlamasi")

    monkeypatch.setattr(app.agent, "run_check", boom)
    out = app.run_scene(1, "ZBCN-USDT", use_llm=False, send=False)
    assert out["res"] is None
    assert "test patlamasi" in out["error"]


def test_onchain_proofs_are_real_hashes():
    """Kanit listesi yalnizca gercek 32 baytlik tx hash'leri icermeli."""
    assert len(app.ONCHAIN_PROOFS) >= 5
    for label, tx in app.ONCHAIN_PROOFS:
        assert tx.startswith("0x") and len(tx) == 66, label
        int(tx, 16)  # gecerli hex
    # eth_call ile dogrulanan kontroller hash'siz listelenir (uydurma yok)
    names = [n for n, _ in app.SIMULATED_ONLY]
    assert "AlreadyUsed" in names and "StaleScore" in names
