"""
test_metrics.py — metrics.py'nin deterministik oldugunu elle hesaplanabilir
sentetik tahtalarla gosterir. Ag yok, ATK cagrisi yok, memory.db'ye dokunulmaz
(hafiza her testte enjekte edilir).

Sentetik tahta (TEST_BOOK):
    ask: 100 x 1,  101 x 1,  102 x 1   -> toplam 303 USDT
    bid:  99 x 1,   98 x 1,   97 x 1   -> toplam 294 USDT
    mid = (100 + 99) / 2 = 99.5
"""

import math
import time

import pytest
from statistics import NormalDist

import atk_client
import metrics

TEST_BOOK = {
    "asks": [["100", "1", "0", "1"], ["101", "1", "0", "1"], ["102", "1", "0", "1"]],
    "bids": [["99", "1", "0", "1"], ["98", "1", "0", "1"], ["97", "1", "0", "1"]],
    "ts": "1760000000000",
}

MID = 99.5

# TEST_BOOK'un +-%2 bandindaki toplam derinligi (atk_client ile olculur):
# +-%2 = [97.51, 101.49] -> ask 100 ve 101, bid 99 ve 98 bandin icinde.
_D = atk_client.depth_within(TEST_BOOK)
TEST_BOOK_DEPTH = _D["bid_depth_usdt"] + _D["ask_depth_usdt"]


def bps(x):
    return x * 10_000


# =============================================================================
# walk_book
# =============================================================================

def test_mid_and_spread():
    assert metrics.mid_price(TEST_BOOK) == MID
    # spread = (100 - 99) / 99.5
    assert metrics.spread_bps(TEST_BOOK) == pytest.approx(bps(1 / MID))


def test_walk_book_buy_single_level():
    """100 USDT tam olarak ilk ask seviyesini tuketir: vwap = 100."""
    r = metrics.walk_book(TEST_BOOK, "buy", 100)
    assert r["fills"] is True
    assert r["levels_used"] == 1
    assert r["vwap"] == pytest.approx(100.0)
    assert r["base_filled"] == pytest.approx(1.0)
    assert r["filled_usdt"] == pytest.approx(100.0)
    # kayma MID'e gore, yarim spread dahil: (100 - 99.5) / 99.5
    assert r["slippage_bps"] == pytest.approx(bps(0.5 / MID))
    assert r["slippage_bps"] == pytest.approx(50.2512, abs=1e-3)


def test_walk_book_buy_partial_second_level():
    """150 USDT: 100@100 + 50@101 -> vwap = 150 / (1 + 50/101)."""
    r = metrics.walk_book(TEST_BOOK, "buy", 150)
    expected_base = 1 + 50 / 101
    expected_vwap = 150 / expected_base
    assert r["fills"] is True
    assert r["levels_used"] == 2
    assert r["base_filled"] == pytest.approx(expected_base)
    assert r["vwap"] == pytest.approx(expected_vwap)
    assert r["slippage_bps"] == pytest.approx(bps((expected_vwap - MID) / MID))


def test_walk_book_buy_book_runs_out():
    """1000 USDT istenir, tahtada 303 USDT var -> fills False, vwap = 101."""
    r = metrics.walk_book(TEST_BOOK, "buy", 1000)
    assert r["fills"] is False
    assert r["filled_usdt"] == pytest.approx(303.0)
    assert r["base_filled"] == pytest.approx(3.0)
    assert r["vwap"] == pytest.approx(101.0)  # (100+101+102)/3
    assert r["levels_used"] == 3
    assert r["slippage_bps"] == pytest.approx(bps((101 - MID) / MID))


def test_walk_book_sell_side():
    """Satista bid'ler yurunur: 99 USDT@99 + 1 USDT@98."""
    r = metrics.walk_book(TEST_BOOK, "sell", 100)
    expected_base = 1 + 1 / 98
    expected_vwap = 100 / expected_base
    assert r["fills"] is True
    assert r["levels_used"] == 2
    assert r["vwap"] == pytest.approx(expected_vwap)
    # satista kayma (mid - vwap) / mid, pozitif
    assert r["slippage_bps"] == pytest.approx(bps((MID - expected_vwap) / MID))
    assert r["slippage_bps"] > 0


def test_walk_book_sell_cheaper_than_buy_is_not_assumed():
    """Iki yon de ayni sembolde pozitif kayma uretir (yon karismasin)."""
    buy = metrics.walk_book(TEST_BOOK, "buy", 100)
    sell = metrics.walk_book(TEST_BOOK, "sell", 100)
    assert buy["slippage_bps"] > 0 and sell["slippage_bps"] > 0
    assert buy["vwap"] > MID > sell["vwap"]


def test_walk_book_empty_and_one_sided():
    assert metrics.walk_book({"asks": [], "bids": []}, "buy", 100) is None
    assert metrics.walk_book({"asks": [["100", "1"]], "bids": []}, "buy", 100) is None
    assert metrics.walk_book(None, "buy", 100) is None


def test_walk_book_bad_args():
    with pytest.raises(ValueError):
        metrics.walk_book(TEST_BOOK, "long", 100)
    with pytest.raises(ValueError):
        metrics.walk_book(TEST_BOOK, "buy", 0)


def test_walk_book_unsorted_input_is_sorted():
    """Tahta ters sirali gelse de en iyi fiyattan yurunur."""
    shuffled = {
        "asks": [["102", "1"], ["100", "1"], ["101", "1"]],
        "bids": [["97", "1"], ["99", "1"], ["98", "1"]],
    }
    assert metrics.walk_book(shuffled, "buy", 100)["vwap"] == pytest.approx(100.0)
    assert metrics.walk_book(shuffled, "sell", 99)["vwap"] == pytest.approx(99.0)


# =============================================================================
# max_safe_size
# =============================================================================

def test_max_safe_size_known_answer_buy():
    """Esik %1 -> hedef fiyat 99.5*1.01 = 100.495.

    100 seviyesi tamamen alinir (100 USDT, 1 baz). 101 seviyesinde vwap'i tam
    hedefe oturtan miktar x = (100.495*1 - 100) / (101 - 100.495) = 99/101,
    yani 99 USDT. Guvenli tutar = 199.0 USDT, vwap = 100.495 (tam hedef).
    """
    r = metrics.max_safe_size(TEST_BOOK, "buy", max_slip_bps=100)
    assert r["max_safe_usdt"] == pytest.approx(199.0)
    assert r["levels_used"] == 2
    assert r["is_lower_bound"] is False
    # tutarlilik: bu tutarda kayma tam esikte
    walk = metrics.walk_book(TEST_BOOK, "buy", r["max_safe_usdt"])
    assert walk["slippage_bps"] == pytest.approx(100.0)


def test_max_safe_size_known_answer_sell():
    """Satis: hedef = 99.5*0.99 = 98.505. 99 seviyesi icinde (99 USDT),
    98 seviyesinde x = (99 - 98.505) / (98.505 - 98) = 0.495/0.505 baz."""
    r = metrics.max_safe_size(TEST_BOOK, "sell", max_slip_bps=100)
    x = (99 - 98.505) / (98.505 - 98)
    assert r["max_safe_usdt"] == pytest.approx(99 + 98 * x)
    walk = metrics.walk_book(TEST_BOOK, "sell", r["max_safe_usdt"])
    assert walk["slippage_bps"] == pytest.approx(100.0)


def test_max_safe_size_whole_book_is_lower_bound():
    """Esik %10 -> butun tahta esigin icinde; sonuc ALT SINIR."""
    r = metrics.max_safe_size(TEST_BOOK, "buy", max_slip_bps=1000)
    assert r["max_safe_usdt"] == pytest.approx(303.0)
    assert r["levels_used"] == 3
    assert r["is_lower_bound"] is True


def test_max_safe_size_zero_when_spread_too_wide():
    """Yarim spread bile esigi asiyorsa guvenli tutar 0."""
    wide = {"asks": [["110", "1"]], "bids": [["90", "1"]]}
    r = metrics.max_safe_size(wide, "buy", max_slip_bps=100)
    assert r["max_safe_usdt"] == pytest.approx(0.0)
    assert r["is_lower_bound"] is False


def test_max_safe_size_empty_book():
    assert metrics.max_safe_size({"asks": [], "bids": []}, "buy") is None


def test_max_safe_size_book_truncated_flag_is_carried():
    r = metrics.max_safe_size(TEST_BOOK, "buy", 100, book_truncated=True)
    assert r["book_truncated"] is True


# =============================================================================
# Istatistik
# =============================================================================

def test_robust_z_known_series():
    """[10,10,11,9,10,12]: medyan 10, |sapma| medyani 0.5 -> z = 2/(1.4826*0.5)."""
    z = metrics.robust_z([10, 10, 11, 9, 10, 12])
    assert z == pytest.approx(2 / (1.4826 * 0.5))
    assert z == pytest.approx(2.6979, abs=1e-3)


def test_robust_z_mad_zero_is_none():
    assert metrics.robust_z([1, 1, 1, 1, 5]) is None   # MAD = 0
    assert metrics.robust_z([7, 7, 7]) is None
    assert metrics.robust_z([1, 2]) is None            # 3'ten az nokta
    assert metrics.robust_z(None) is None


def test_log_changes():
    out = metrics.log_changes([100, 110, 99])
    assert out == pytest.approx([math.log(1.1), math.log(99 / 110)])
    assert metrics.log_changes([]) == []
    # sifir/None atlanir, zincir kopar
    assert metrics.log_changes([100, 0, 100]) == []


def test_bonferroni_threshold_is_computed_not_hardcoded():
    z = metrics.bonferroni_threshold(0.05, 20)
    print(f"\nbonferroni_threshold(alpha=0.05, m=20) = {z:.6f}")
    assert z == pytest.approx(NormalDist().inv_cdf(1 - 0.05 / 40))
    assert 2.9 < z < 3.1
    # duzeltme olmadan (m=1) esik dusuk olmali
    assert metrics.bonferroni_threshold(0.05, 1) < z
    with pytest.raises(ValueError):
        metrics.bonferroni_threshold(0, 20)


def test_depth_vs_memory():
    assert metrics.depth_vs_memory(50, [100, 100, 100]) == pytest.approx(0.5)
    assert metrics.depth_vs_memory(200, [100, 100, 100]) == pytest.approx(2.0)
    assert metrics.depth_vs_memory(50, []) is None
    assert metrics.depth_vs_memory(None, [100]) is None


def test_volume_quality():
    assert metrics.volume_quality(1000, 100, 100) == pytest.approx(5.0)
    assert metrics.volume_quality(1000, 0, 0) is None
    assert metrics.volume_quality(None, 100, 100) is None


# =============================================================================
# risk_score (VARSAYIM agirliklari)
# =============================================================================

def test_risk_score_floor_and_ceiling():
    clean = {
        "slippage_bps": 0.0, "fills": True, "depth_ratio": 1.0,
        "anomaly_z": 0.0, "spread_bps": 0.0, "limited_memory": False,
    }
    score, _ = metrics.risk_score(clean)
    assert score == 0

    worst = {
        "slippage_bps": 10_000.0, "fills": False, "depth_ratio": 0.0,
        "anomaly_z": 99.0, "spread_bps": 10_000.0, "limited_memory": True,
    }
    score, norm = metrics.risk_score(worst)
    assert score == 10_000
    assert all(v == pytest.approx(1.0) for v in norm.values())


def test_risk_score_single_component_matches_weight():
    """Sadece kayma dolu: skor = 10000 * agirlik(slippage)."""
    comp = {
        "slippage_bps": metrics.RISK_SCALES["slippage_full_bps"],
        "fills": True, "depth_ratio": 1.0, "anomaly_z": 0.0,
        "spread_bps": 0.0, "limited_memory": False,
    }
    score, _ = metrics.risk_score(comp)
    assert score == round(10_000 * metrics.RISK_WEIGHTS["slippage"])


def test_risk_score_limited_memory_penalty():
    comp = {
        "slippage_bps": 0.0, "fills": True, "depth_ratio": None,
        "anomaly_z": None, "spread_bps": 0.0, "limited_memory": True,
    }
    score, _ = metrics.risk_score(comp)
    assert score == metrics.LIMITED_MEMORY_PENALTY


def test_risk_score_monotonic_in_slippage():
    def s(slip):
        return metrics.risk_score({
            "slippage_bps": slip, "fills": True, "depth_ratio": 1.0,
            "anomaly_z": 0.0, "spread_bps": 0.0, "limited_memory": False,
        })[0]

    assert s(0) < s(50) < s(150) < s(10_000)


# =============================================================================
# check_execution_core — fail-closed davranisi
# =============================================================================

def _book_result(age_s=1.0, ok=True, data=TEST_BOOK, now=None):
    now = time.time() if now is None else now
    return {
        "ok": ok,
        "data": data,
        "error": None if ok else "CLI cikis kodu 1",
        "fetched_at": now - age_s,
        "latency_ms": 500,
    }


def _memory(n, depth=200.0, mid=99.5):
    """n noktali yapay hafiza: sabit mid/derinlik (MAD=0 -> z None)."""
    return {"n": n, "mids": [mid] * n, "depths": [depth] * n, "error": None}


def test_insufficient_data_when_stale():
    now = time.time()
    res = metrics.check_execution_core(
        "YGG-USDT", "buy", 1000,
        book_result=_book_result(age_s=121, now=now),
        memory=_memory(60), now=now,
    )
    assert res["status"] == "INSUFFICIENT_DATA"
    assert res["riskScore"] is None and res["maxSafeSize"] is None
    assert res["data_age_s"] == pytest.approx(121, abs=0.01)


def test_fresh_data_at_120s_boundary_is_accepted():
    now = time.time()
    res = metrics.check_execution_core(
        "YGG-USDT", "buy", 100,
        book_result=_book_result(age_s=119.5, now=now),
        memory=_memory(60), now=now,
    )
    assert res["status"] in ("OK", "OK_LIMITED_MEMORY")
    assert res["riskScore"] is not None


def test_insufficient_data_when_cli_failed():
    res = metrics.check_execution_core(
        "YGG-USDT", "buy", 1000,
        book_result=_book_result(ok=False, data=None),
        memory=_memory(60),
    )
    assert res["status"] == "INSUFFICIENT_DATA"
    assert res["riskScore"] is None
    assert "CLI" in res["reason"]


def test_insufficient_data_when_book_empty():
    res = metrics.check_execution_core(
        "YGG-USDT", "buy", 1000,
        book_result=_book_result(data={"asks": [], "bids": []}),
        memory=_memory(60),
    )
    assert res["status"] == "INSUFFICIENT_DATA"
    assert res["riskScore"] is None


def test_limited_memory_status_and_penalty():
    res = metrics.check_execution_core(
        "YGG-USDT", "buy", 100, book_result=_book_result(), memory=_memory(5)
    )
    assert res["status"] == "OK_LIMITED_MEMORY"
    assert res["memory_points"] == 5
    assert res["components"]["anomaly_z"] is None
    assert res["components"]["depth_ratio"] is None
    assert res["riskScore"] >= metrics.LIMITED_MEMORY_PENALTY


def test_ok_status_with_enough_memory():
    res = metrics.check_execution_core(
        "YGG-USDT", "buy", 100, book_result=_book_result(), memory=_memory(60)
    )
    assert res["status"] == "OK"
    assert res["memory_points"] == 60
    assert res["maxSafeSize"] == pytest.approx(199.0)
    assert res["slippage_bps_at_size"] == pytest.approx(bps(0.5 / MID))
    assert res["fills"] is True
    assert res["bonferroni_z"] == pytest.approx(metrics.bonferroni_threshold(0.05, 20))


def test_size_above_book_sets_fills_false():
    res = metrics.check_execution_core(
        "YGG-USDT", "buy", 1000, book_result=_book_result(), memory=_memory(60)
    )
    assert res["fills"] is False
    # no_fill bileseni devreye girdi
    assert res["components"]["normalized"]["no_fill"] == pytest.approx(1.0)


def test_depth_drop_raises_score():
    """Hafizadaki derinlik simdikinin iki kati -> derinlik dususu bileseni dolar."""
    base = metrics.check_execution_core(
        "YGG-USDT", "buy", 100, book_result=_book_result(),
        memory=_memory(60, depth=TEST_BOOK_DEPTH),
    )
    dropped = metrics.check_execution_core(
        "YGG-USDT", "buy", 100, book_result=_book_result(),
        memory=_memory(60, depth=TEST_BOOK_DEPTH * 4),
    )
    assert dropped["components"]["depth_ratio"] < base["components"]["depth_ratio"]
    assert dropped["riskScore"] > base["riskScore"]


def test_bad_side_raises():
    with pytest.raises(ValueError):
        metrics.check_execution_core("YGG-USDT", "long", 100,
                                     book_result=_book_result(), memory=_memory(60))
