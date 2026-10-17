"""
signer.py — Arf risk skorunun zincir disinda imzalanmasi (EIP-191).

Imzalanan payload, RiskCircuitBreaker.attestationDigest ile BIREBIR AYNI:
    abi.encode(bytes32 symbolHash, uint8 side, uint256 riskScore,
               uint256 maxSafeSize, uint256 timestamp, uint256 chainid,
               address contract)
`encodePacked` KULLANILMAZ (sabit genislikli alanlar, kaydirma yok).
chainid ve kontrat adresi payload'a girer: baska agdaki veya baska
kontrattaki imza gecersiz olur.

Birimler: maxSafeSize USDT x 1e6 (6 ondalik, ASAGI yuvarlanir -- yukari
yuvarlamak guvenli tutari sismesi demek olurdu), riskScore 0-10000.
side: buy=0, sell=1 (alis onayi satista kullanilamasin diye imzada).

GIZLILIK: ozel anahtar yalnizca fonksiyon PARAMETRESI olarak gelir; hicbir
dosyaya, log satirina veya cikti sozlugune yazilmaz. Asagidaki
ANVIL_TEST_KEY gercek bir anahtar DEGIL; Foundry/anvil'in herkesce bilinen
0. test hesabi ve SADECE test vektoru uretiminde kullanilir.

Kullanim:
    python signer.py --vector [--contract 0x...]
        test/vector.json dosyasini uretir (Python<->Solidity byte uyumu testi).
"""

import argparse
import json
from decimal import Decimal

import rlp
from eth_abi import encode as abi_encode
from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import keccak, to_checksum_address

SIDES = {"buy": 0, "sell": 1}
USDT_SCALE = 10**6          # maxSafeSize birimi: USDT x 1e6
RISK_SCORE_MAX = 10_000     # riskScore 0-10000 (yuksek = riskli)

PAYLOAD_TYPES = [
    "bytes32",   # symbolHash = keccak256(bytes("BTC-USDT"))
    "uint8",     # side: 0 = alis, 1 = satis
    "uint256",   # riskScore (0-10000)
    "uint256",   # maxSafeSize (USDT x 1e6)
    "uint256",   # timestamp (unix saniye)
    "uint256",   # chainid
    "address",   # kontrat adresi
]

# --- SADECE TEST VEKTORU ICIN (gercek anahtar DEGIL) --------------------------
# Kaynak: `anvil --port 18545 --accounts 3` cikti basligi, Foundry 1.7.1-Homebrew.
# Hesap 0: 0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266
ANVIL_TEST_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"

# Foundry testi kontrati bu adresten, nonce 0 ile kuruyor (vm.prank(DEPLOYER)).
# Vektor bu adrese gore uretilir; test deploy ettigi adresi vektorle karsilastirir.
TEST_DEPLOYER = "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC"  # anvil hesap 2
TEST_DEPLOYER_NONCE = 0

VECTOR_PATH = "test/vector.json"


def symbol_hash(symbol):
    """keccak256(bytes("BTC-USDT")) -- sembol duz metin olarak hash'lenir."""
    return keccak(text=symbol)


def to_usdt_units(amount_usdt):
    """USDT -> USDT x 1e6 tamsayisi. ASAGI yuvarlar (muhafazakar)."""
    units = (Decimal(str(amount_usdt)) * USDT_SCALE).to_integral_value(rounding="ROUND_FLOOR")
    if units < 0:
        raise ValueError("maxSafeSize negatif olamaz")
    return int(units)


def create_address(deployer, nonce):
    """CREATE adresi: keccak(rlp([deployer, nonce]))[12:] -- zincir disi hesap."""
    raw = rlp.encode([bytes.fromhex(deployer[2:]), nonce])
    return to_checksum_address(keccak(raw)[12:])


def build_payload(symbol, side, risk_score, max_safe_size_units, timestamp,
                  chain_id, contract_addr):
    """Imzalanacak ham payload (Solidity abi.encode ile birebir ayni)."""
    return abi_encode(
        PAYLOAD_TYPES,
        [
            symbol_hash(symbol),
            side,
            risk_score,
            max_safe_size_units,
            timestamp,
            chain_id,
            to_checksum_address(contract_addr),
        ],
    )


def sign_attestation(private_key_hex, symbol, side, risk_score,
                     max_safe_size_usdt, timestamp, chain_id, contract_addr):
    """Imzali risk skoru uretir. Ozel anahtar ciktiya ASLA girmez."""
    if side not in SIDES:
        raise ValueError(f"side 'buy' veya 'sell' olmali, gelen: {side!r}")
    if not 0 <= risk_score <= RISK_SCORE_MAX:
        raise ValueError(f"riskScore 0-{RISK_SCORE_MAX} araliginda olmali: {risk_score}")
    if int(timestamp) <= 0:
        raise ValueError("timestamp pozitif unix saniye olmali")

    side_int = SIDES[side]
    units = to_usdt_units(max_safe_size_usdt)
    contract = to_checksum_address(contract_addr)

    payload = build_payload(symbol, side_int, int(risk_score), units,
                            int(timestamp), int(chain_id), contract)
    digest = keccak(payload)

    # EIP-191 "version E": encode_defunct 32 baytlik hash'i
    # b"\x19Ethereum Signed Message:\n32" onekiyle sarar; Solidity tarafinda
    # MessageHashUtils.toEthSignedMessageHash(bytes32) ayni seyi yapar.
    signable = encode_defunct(primitive=digest)
    signed = Account.sign_message(signable, private_key=private_key_hex)

    signer_addr = Account.from_key(private_key_hex).address
    recovered = Account.recover_message(signable, signature=signed.signature)
    if recovered != signer_addr:
        raise RuntimeError("imza kendi kendini dogrulayamadi (kutuphane uyumsuz)")

    return {
        "symbol": symbol,
        "symbolHash": "0x" + symbol_hash(symbol).hex(),
        "side": side,
        "sideInt": side_int,
        "riskScore": int(risk_score),
        "maxSafeSizeUsdt": float(max_safe_size_usdt),
        "maxSafeSize": units,
        "timestamp": int(timestamp),
        "chainId": int(chain_id),
        "contract": contract,
        "signer": signer_addr,
        "payloadHex": "0x" + payload.hex(),
        "digest": "0x" + digest.hex(),
        "ethSignedMessageHash": "0x" + signed.message_hash.hex(),
        "signature": "0x" + signed.signature.hex(),
    }


def write_vector(contract_addr=None, out_path=VECTOR_PATH):
    """Sabit girdilerle test vektoru uretir ve `out_path`e yazar."""
    contract = contract_addr or create_address(TEST_DEPLOYER, TEST_DEPLOYER_NONCE)
    vec = sign_attestation(
        private_key_hex=ANVIL_TEST_KEY,
        symbol="YGG-USDT",
        side="buy",
        risk_score=4200,
        max_safe_size_usdt=1000.0,
        timestamp=1760000000,
        chain_id=43113,
        contract_addr=contract,
    )
    vec["note"] = (
        "Python<->Solidity byte uyumu test vektoru. Anahtar: anvil hesap 0 "
        "(herkesce bilinen TEST anahtari, ozel anahtar bu dosyada YOK). "
        f"Kontrat adresi = CREATE({TEST_DEPLOYER}, nonce {TEST_DEPLOYER_NONCE})."
    )
    with open(out_path, "w") as f:
        json.dump(vec, f, indent=2, sort_keys=True)
        f.write("\n")
    print(json.dumps(vec, indent=2, sort_keys=True))
    print(f"\n-> {out_path}")
    return vec


def main():
    ap = argparse.ArgumentParser(description="Arf imzalayici")
    ap.add_argument("--vector", action="store_true",
                    help="sabit girdilerle test/vector.json uret")
    ap.add_argument("--contract", default=None,
                    help="vektorun uretilecegi kontrat adresi "
                         "(varsayilan: Foundry testinin deploy adresi)")
    ap.add_argument("--out", default=VECTOR_PATH,
                    help=f"cikti dosyasi (varsayilan: {VECTOR_PATH})")
    args = ap.parse_args()

    if args.vector:
        write_vector(args.contract, args.out)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
