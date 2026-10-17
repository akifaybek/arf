"""
chain.py — Avalanche Fuji (chainId 43113) baglantisi ve RiskCircuitBreaker
cagrilari. Veri yolu: imzali skor -> eth_call simulasyonu -> (gerekirse) tx.

GIZLILIK: ozel anahtarlar yalnizca .env'den okunur (python-dotenv), yalnizca
imzalamada kullanilir; hicbir log satirina, dosyaya, hata mesajina veya donus
sozluguge YAZILMAZ. RPC adresleri de maskelenerek loglanir (bir RPC URL'i
API anahtari tasiyabilir).

Kullanim:
    python chain.py            # baglanti + zincir durumu (tx YOK)
"""

import json
import os
import re
import time
from urllib.parse import urlparse

from dotenv import load_dotenv
from eth_abi import decode as abi_decode
from eth_account import Account
from eth_utils import keccak, to_checksum_address
from web3 import Web3
from web3.exceptions import ContractLogicError
from web3.logs import DISCARD

import signer

CHAIN_ID = 43113

# forge'un derleme ciktisi: Remix'e verilen flat dosya ile AYNI kaynak
ABI_PATH = "out/RiskCircuitBreaker.sol/RiskCircuitBreaker.json"

EXPLORER_TX = "https://explorer-test.avax.network/c-chain/tx/{}"

RPC_TIMEOUT_S = 20

# --- VARSAYIM: revert eden tx'i zincire yazdirmak icin sabit gas limiti -----
# Gas tahmini yapilmaz (tahmin revert'te patlar); 300k, kontratin mutlu yol
# tuketiminin (~75k) kat kat ustunde.
FORCE_GAS_LIMIT = 300_000

# --- Deploy edilen kontratin BEKLENEN durumu (Remix ciktisi, public bilgi) ---
# read_state() bunlarla karsilastirir; uyusmazsa islem yapilmaz.
EXPECTED = {
    "contract": "0xddE4C78F831f082E8AFDF716266bd1338B591159",
    "owner": "0xbe965C314D2655360142b05DF34c760e08980F68",
    "oracle": "0x3267103eB5d4F4F6350d0D03327De7637a56d385",
    "riskThreshold": 5000,
    "trader": "0x5D07498C9Aa3F85c996Dae68e819d8b6AAF8233D",
    "paused": False,
}


class ChainError(RuntimeError):
    """Zincir tarafinda devam edilemeyecek durum (anahtar/adres/ag uyusmazligi)."""


# =============================================================================
# Yapilandirma
# =============================================================================

def load_env():
    load_dotenv()


def mask_rpc(url):
    """Logda gosterilecek guvenli hali: sadece host (yol/anahtar gizli)."""
    try:
        host = urlparse(url).netloc or "?"
    except Exception:
        return "?"
    return host


def rpc_candidates():
    """FUJI_RPC_URL + FUJI_RPC_URLS (virgulle ayrilmis) sirali liste."""
    urls = []
    primary = os.getenv("FUJI_RPC_URL", "").strip()
    if primary:
        urls.append(primary)
    extra = os.getenv("FUJI_RPC_URLS", "")
    for u in extra.split(","):
        u = u.strip()
        if u and u not in urls:
            urls.append(u)
    if not urls:
        raise ChainError(".env icinde FUJI_RPC_URL yok")
    return urls


def load_abi(path=ABI_PATH):
    with open(path) as f:
        return json.load(f)["abi"]


# =============================================================================
# Baglanti
# =============================================================================

def connect(verbose=True):
    """Adaylari sirayla dener; chain_id 43113 olani dondurur.

    429 / timeout / baglanti hatasinda sonrakine gecer. Doner: (w3, url).
    """
    load_env()
    errors = []
    for url in rpc_candidates():
        try:
            w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": RPC_TIMEOUT_S}))
            cid = w3.eth.chain_id
            if cid != CHAIN_ID:
                errors.append(f"{mask_rpc(url)}: chainId {cid} (43113 degil)")
                continue
            blk = w3.eth.block_number
            if verbose:
                print(f"[rpc] {mask_rpc(url)} secildi (chainId={cid}, blok={blk:,})")
            return w3, url
        except Exception as exc:  # 429, Cloudflare, timeout, DNS...
            detail = str(exc).split("\n")[0][:140]
            errors.append(f"{mask_rpc(url)}: {detail}")
            if verbose:
                print(f"[rpc] {mask_rpc(url)} atlandi -> {detail}")
    raise ChainError("hicbir RPC'ye baglanilamadi: " + " | ".join(errors))


def get_contract(w3, address=None):
    addr = to_checksum_address(address or os.getenv("CONTRACT_ADDRESS", ""))
    return w3.eth.contract(address=addr, abi=load_abi())


def _account(env_key):
    """Ozel anahtari .env'den alir ve SADECE hesap nesnesi dondurur.

    Anahtarin kendisi cagirana donmez, loglanmaz. Eksikse ChainError.
    """
    pk = os.getenv(env_key, "").strip()
    if not pk:
        raise ChainError(f".env icinde {env_key} yok")
    try:
        return Account.from_key(pk)
    except Exception:
        raise ChainError(f"{env_key} gecerli bir ozel anahtar degil") from None


def oracle_account():
    return _account("ORACLE_PRIVATE_KEY")


def sign_attestation_with_oracle(symbol, side, risk_score, max_safe_size_usdt,
                                 timestamp, contract_addr=None):
    """Oracle anahtariyla imzalar. Anahtar bu fonksiyonun icinden cikmaz.

    signer.sign_attestation ciktisi (digest + imza) doner; o sozlukte de
    ozel anahtar YOKTUR.
    """
    load_env()
    pk = os.getenv("ORACLE_PRIVATE_KEY", "").strip()
    if not pk:
        raise ChainError(".env icinde ORACLE_PRIVATE_KEY yok")
    addr = to_checksum_address(contract_addr or os.getenv("CONTRACT_ADDRESS", ""))
    return signer.sign_attestation(
        private_key_hex=pk,
        symbol=symbol,
        side=side,
        risk_score=risk_score,
        max_safe_size_usdt=max_safe_size_usdt,
        timestamp=timestamp,
        chain_id=CHAIN_ID,
        contract_addr=addr,
    )


def trader_account():
    return _account("TRADER_PRIVATE_KEY")


# =============================================================================
# Durum okuma
# =============================================================================

def read_state(w3=None, url=None, strict=True, verbose=True):
    """oracle/riskThreshold/owner/paused okur ve EXPECTED ile karsilastirir."""
    if w3 is None:
        w3, url = connect(verbose=verbose)
    c = get_contract(w3)

    state = {
        "rpc": mask_rpc(url or ""),
        "chain_id": w3.eth.chain_id,
        "block": w3.eth.block_number,
        "contract": c.address,
        "oracle": c.functions.oracle().call(),
        "riskThreshold": c.functions.riskThreshold().call(),
        "owner": c.functions.owner().call(),
        "paused": c.functions.paused().call(),
        "MAX_AGE": c.functions.MAX_AGE().call(),
        "MAX_FUTURE": c.functions.MAX_FUTURE().call(),
    }

    # Anahtarlardan turetilen adresler (anahtarin kendisi asla gorunmez)
    state["oracle_key_address"] = oracle_account().address
    state["trader_key_address"] = trader_account().address

    mismatches = []
    if state["contract"] != to_checksum_address(EXPECTED["contract"]):
        mismatches.append(f"kontrat adresi {state['contract']} != beklenen")
    if state["oracle"] != to_checksum_address(EXPECTED["oracle"]):
        mismatches.append(f"oracle {state['oracle']} != beklenen")
    if state["owner"] != to_checksum_address(EXPECTED["owner"]):
        mismatches.append(f"owner {state['owner']} != beklenen")
    if state["riskThreshold"] != EXPECTED["riskThreshold"]:
        mismatches.append(f"riskThreshold {state['riskThreshold']} != beklenen")
    if state["paused"] != EXPECTED["paused"]:
        mismatches.append(f"paused {state['paused']} != beklenen")
    if state["oracle_key_address"] != state["oracle"]:
        mismatches.append("ORACLE_PRIVATE_KEY zincirdeki oracle adresini vermiyor")
    if state["trader_key_address"] != to_checksum_address(EXPECTED["trader"]):
        mismatches.append("TRADER_PRIVATE_KEY beklenen trader adresini vermiyor")

    state["mismatches"] = mismatches
    if verbose:
        print(f"[zincir] kontrat   : {state['contract']}")
        print(f"[zincir] owner     : {state['owner']}")
        print(f"[zincir] oracle    : {state['oracle']}  (anahtardan: "
              f"{state['oracle_key_address']})")
        print(f"[zincir] threshold : {state['riskThreshold']}  paused={state['paused']}  "
              f"MAX_AGE={state['MAX_AGE']}  MAX_FUTURE={state['MAX_FUTURE']}")
        print(f"[zincir] trader    : {state['trader_key_address']}  "
              f"bakiye={w3.from_wei(w3.eth.get_balance(state['trader_key_address']), 'ether')} AVAX")
        print(f"[zincir] uyusmazlik: {mismatches if mismatches else 'yok'}")

    if strict and mismatches:
        raise ChainError("zincir durumu beklenenle uyusmuyor: " + "; ".join(mismatches))
    return state, w3, url


# =============================================================================
# Custom error cozumu
# =============================================================================

def _error_selectors(abi=None):
    """ABI'deki error tanimlarindan 4 bayt secici -> (ad, tipler) haritasi."""
    out = {}
    for item in abi or load_abi():
        if item.get("type") != "error":
            continue
        types = [i["type"] for i in item.get("inputs", [])]
        sig = f"{item['name']}({','.join(types)})"
        out[keccak(text=sig)[:4]] = (item["name"], types, [i.get("name") for i in item.get("inputs", [])])
    return out


def decode_custom_error(data_hex, abi=None):
    """Revert verisini okunur hale cevirir: 'ExceedsSafeSize(amount=.., ..)'."""
    if not data_hex:
        return None
    if isinstance(data_hex, dict):  # bazi RPC'ler {"data": "0x.."} doner
        data_hex = data_hex.get("data") or ""
    if isinstance(data_hex, str) and not data_hex.strip().startswith("0x"):
        # Serbest metin (hata mesaji) icinden revert verisini cek
        m = re.search(r"0x[0-9a-fA-F]{8,}", data_hex)
        data_hex = m.group(0) if m else ""
    try:
        raw = bytes.fromhex(data_hex[2:] if data_hex.startswith("0x") else data_hex)
    except ValueError:
        return {"name": None, "raw": str(data_hex)}
    if len(raw) < 4:
        return {"name": None, "raw": data_hex}

    selector, payload = raw[:4], raw[4:]

    # Standart Error(string) / Panic(uint256)
    if selector == keccak(text="Error(string)")[:4]:
        return {"name": "Error", "args": {"message": abi_decode(["string"], payload)[0]}}
    if selector == keccak(text="Panic(uint256)")[:4]:
        return {"name": "Panic", "args": {"code": abi_decode(["uint256"], payload)[0]}}

    table = _error_selectors(abi)
    if selector not in table:
        return {"name": None, "raw": data_hex}
    name, types, names = table[selector]
    try:
        vals = abi_decode(types, payload) if types else ()
    except Exception:
        return {"name": name, "raw": data_hex}
    args = {(names[i] or f"arg{i}"): v for i, v in enumerate(vals)}
    return {"name": name, "args": args, "types": types}


def _fmt_value(v):
    """bytes32/bytes alanlari hex, digerleri oldugu gibi."""
    if isinstance(v, (bytes, bytearray)):
        return "0x" + bytes(v).hex()
    return v


def format_error(err):
    if not err:
        return "(hata verisi yok)"
    if not err.get("name"):
        return f"(cozulemeyen revert: {err.get('raw')})"
    args = err.get("args") or {}
    inner = ", ".join(f"{k}={_fmt_value(v)}" for k, v in args.items())
    return f"{err['name']}({inner})"


# =============================================================================
# Niyet gonderimi
# =============================================================================

def execute_intent(symbol, side, amount_usdt, attestation, w3=None, url=None,
                   force_onchain=False, verbose=True):
    """Imzali skoru kontrata goturur.

    Once eth_call ile simule edilir. Simulasyon revert ederse:
      force_onchain=False -> tx GONDERILMEZ, decode edilmis hata dondurulur
      force_onchain=True  -> sabit gas limitiyle tx gonderilir (explorer'da
                             revert eden tx gorunsun)

    attestation: signer.sign_attestation ciktisi (ayni semboller/degerler).
    Doner: tx_hash, status, event / error, gas_used, confirm_ms, explorer.
    """
    if w3 is None:
        w3, url = connect(verbose=verbose)
    c = get_contract(w3)
    trader = trader_account()

    amount_units = signer.to_usdt_units(amount_usdt)
    sym_hash = bytes.fromhex(attestation["symbolHash"][2:])
    sig = bytes.fromhex(attestation["signature"][2:])

    if attestation["symbol"] != symbol or attestation["side"] != side:
        raise ChainError("attestation sembol/yon alanlari istekle uyusmuyor")

    fn = c.functions.executeIntent(
        sym_hash,
        attestation["sideInt"],
        amount_units,
        attestation["riskScore"],
        attestation["maxSafeSize"],
        attestation["timestamp"],
        sig,
    )

    result = {
        "symbol": symbol,
        "side": side,
        "amount_usdt": float(amount_usdt),
        "amount_units": amount_units,
        "digest": attestation["digest"],
        "tx_hash": None,
        "status": None,
        "event": None,
        "error": None,
        "error_text": None,
        "gas_used": None,
        "gas_limit": None,
        "confirm_ms": None,
        "explorer": None,
        "sent": False,
    }

    # --- 1) eth_call simulasyonu -------------------------------------------
    sim_ok = True
    try:
        fn.call({"from": trader.address})
    except ContractLogicError as exc:
        sim_ok = False
        err = decode_custom_error(getattr(exc, "data", None) or str(exc))
        result["error"] = err
        result["error_text"] = format_error(err)
    except Exception as exc:
        sim_ok = False
        result["error"] = {"name": None, "raw": str(exc)[:200]}
        result["error_text"] = f"(simulasyon hatasi: {str(exc)[:160]})"

    if verbose:
        print(f"[sim] {symbol} {side} {amount_usdt:,.0f} USDT -> "
              f"{'GECER' if sim_ok else result['error_text']}")

    if not sim_ok and not force_onchain:
        result["status"] = "SIMULATED_REVERT"
        return result

    # --- 2) tx gonderimi ----------------------------------------------------
    if sim_ok:
        gas_limit = int(fn.estimate_gas({"from": trader.address}) * 1.25)
    else:
        gas_limit = FORCE_GAS_LIMIT  # tahmin yapilmaz, revert zincire yazilir

    tx = fn.build_transaction({
        "from": trader.address,
        "nonce": w3.eth.get_transaction_count(trader.address, "pending"),
        "chainId": CHAIN_ID,
        "gas": gas_limit,
    })
    signed = trader.sign_transaction(tx)

    started = time.time()
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    result["tx_hash"] = tx_hash.hex() if not isinstance(tx_hash, str) else tx_hash
    if not result["tx_hash"].startswith("0x"):
        result["tx_hash"] = "0x" + result["tx_hash"]
    result["explorer"] = explorer_link(result["tx_hash"])
    result["sent"] = True
    result["gas_limit"] = gas_limit
    if verbose:
        print(f"[tx ] gonderildi: {result['tx_hash']}  (gas limiti {gas_limit:,})")

    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
    result["confirm_ms"] = int((time.time() - started) * 1000)
    result["gas_used"] = receipt["gasUsed"]
    result["block"] = receipt["blockNumber"]

    if receipt["status"] == 1:
        result["status"] = "CONFIRMED"
        logs = c.events.IntentApproved().process_receipt(receipt, errors=DISCARD)
        if logs:
            a = dict(logs[0]["args"])
            a["symbolHash"] = "0x" + a["symbolHash"].hex()
            result["event"] = a
    else:
        result["status"] = "REVERTED_ONCHAIN"
        # Revert sebebini ayni blokta eth_call ile yeniden uret
        try:
            fn.call({"from": trader.address}, block_identifier=receipt["blockNumber"])
        except ContractLogicError as exc:
            err = decode_custom_error(getattr(exc, "data", None) or str(exc))
            result["error"] = err
            result["error_text"] = format_error(err)
        except Exception:
            pass

    if verbose:
        print(f"[tx ] {result['status']}  blok={result.get('block')}  "
              f"gas={result['gas_used']:,}  onay={result['confirm_ms']} ms")
        print(f"[tx ] {result['explorer']}")
    return result


def simulate_only(symbol, side, amount_usdt, attestation, w3=None, url=None, verbose=True):
    """Yalnizca eth_call: zincire hicbir sey yazmaz."""
    return execute_intent(symbol, side, amount_usdt, attestation, w3=w3, url=url,
                          force_onchain=False, verbose=verbose)


def explorer_link(tx_hash):
    h = tx_hash if str(tx_hash).startswith("0x") else "0x" + str(tx_hash)
    return EXPLORER_TX.format(h)


def onchain_digest(symbol, side, risk_score, max_safe_size_usdt, timestamp,
                   w3=None, url=None):
    """Kontratin attestationDigest'i (canli byte uyumu karsilastirmasi icin)."""
    if w3 is None:
        w3, url = connect(verbose=False)
    c = get_contract(w3)
    d = c.functions.attestationDigest(
        keccak(text=symbol),
        signer.SIDES[side],
        int(risk_score),
        signer.to_usdt_units(max_safe_size_usdt),
        int(timestamp),
    ).call()
    return "0x" + d.hex()


if __name__ == "__main__":
    state, _w3, _url = read_state(strict=False)
    if state["mismatches"]:
        raise SystemExit("UYUSMAZLIK VAR, islem yapilmadi")
    print("\nzincir durumu beklenenle birebir uyusuyor.")
