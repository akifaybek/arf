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
    assert len(app.ONCHAIN_PROOFS) >= 7
    hashes = set()
    for label, tx in app.ONCHAIN_PROOFS:
        assert tx.startswith("0x") and len(tx) == 66, label
        int(tx, 16)              # gecerli hex
        hashes.add(tx)
    assert len(hashes) == len(app.ONCHAIN_PROOFS), "ayni hash iki kez listelenmis"
    # Kontratin her revert yolu icin gercek bir tx olmali
    etiketler = " ".join(n for n, _ in app.ONCHAIN_PROOFS)
    for beklenen in ("IntentApproved", "ExceedsSafeSize", "BadSigner",
                     "AlreadyUsed", "StaleScore"):
        assert beklenen in etiketler, f"{beklenen} kaniti listede yok"
    # tx'siz dogrulanan kontroller ayri listede (uydurma hash yok)
    assert isinstance(app.SIMULATED_ONLY, list)


# =============================================================================
# Yol/env saglamligi (Streamlit baska bir calisma dizininden baslatilabilir)
# =============================================================================

def test_all_data_paths_are_absolute():
    """Goreli yol, Streamlit'te `.env`/ABI yuklenmemesine ve
    `to_checksum_address('')` -> "Unknown format ''" hatasina yol aciyordu."""
    import os
    import agent as agent_mod
    import llm
    import metrics
    for name, path in [("chain.ENV_PATH", chain.ENV_PATH),
                       ("chain.ABI_PATH", chain.ABI_PATH),
                       ("llm.ENV_PATH", llm.ENV_PATH),
                       ("metrics.DB_PATH", metrics.DB_PATH),
                       ("LiveDeps.PAIRS_PATH", agent_mod.LiveDeps.PAIRS_PATH)]:
        assert os.path.isabs(str(path)), f"{name} mutlak degil: {path}"


def test_app_loads_env_at_import():
    """app.py import edilince .env yuklenmis olmali (cwd ne olursa olsun)."""
    import os
    assert os.getenv("CONTRACT_ADDRESS"), "app import'u .env'i yuklemedi"


def test_contract_address_never_returns_empty(monkeypatch):
    monkeypatch.setenv("CONTRACT_ADDRESS", "")
    assert chain.contract_address() == chain.EXPECTED["contract"]

    monkeypatch.delenv("CONTRACT_ADDRESS", raising=False)
    # .env'den yeniden yuklenir ya da beklenen adrese duser; bos olamaz
    addr = chain.contract_address()
    assert addr.startswith("0x") and len(addr) == 42


def test_contract_address_gives_clear_error_on_garbage(monkeypatch):
    monkeypatch.setenv("CONTRACT_ADDRESS", "bu-bir-adres-degil")
    with pytest.raises(chain.ChainError) as exc:
        chain.contract_address()
    assert "CONTRACT_ADDRESS" in str(exc.value)


def test_feed_down_scene_labels_memory_tools():
    """Sahne 3'te hafizadan okuyan araclar etiketlenebilir olmali."""
    assert app.SCENES[3]["feed_down"] is True
    assert "scan_market" in app.MEMORY_TOOLS
    assert "compute_metric" in app.MEMORY_TOOLS
