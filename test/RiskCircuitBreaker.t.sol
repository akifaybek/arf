// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";

import {RiskCircuitBreaker} from "../contracts/RiskCircuitBreaker.sol";
import {Vm} from "./Cheats.sol";

/// @notice RiskCircuitBreaker testleri. En onemlisi test_DigestMatchesPython:
///         Python imzalayicinin urettigi digest ve imza, kontratin kendi
///         hesabiyla birebir ayni mi (byte uyumu kaniti).
contract RiskCircuitBreakerTest {
    Vm constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));

    // Herkesce bilinen anvil TEST anahtarlari (gercek anahtar DEGIL).
    // Kaynak: `anvil --accounts 3` cikti basligi, Foundry 1.7.1-Homebrew.
    uint256 constant ORACLE_PK = 0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80;
    uint256 constant OTHER_PK = 0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d;

    // Vektor bu adresten, nonce 0 ile kurulan kontrat icin uretildi.
    address constant DEPLOYER = 0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC;
    address constant STRANGER = address(0xBEEF);

    uint256 constant FUJI_CHAIN_ID = 43113;
    uint256 constant THRESHOLD = 5000;
    uint256 constant USDT = 1e6;

    RiskCircuitBreaker breaker;
    address oracle;

    // vector.json alanlari
    string vectorJson;
    bytes32 vSymbolHash;
    uint8 vSide;
    uint256 vRiskScore;
    uint256 vMaxSafeSize;
    uint256 vTimestamp;
    bytes32 vDigest;
    bytes vSignature;

    /// @dev Kontrattaki olayin aynisi; expectEmit icin yerel bildirim sart.
    event IntentApproved(
        bytes32 indexed symbolHash,
        uint8 side,
        uint256 amount,
        uint256 riskScore,
        uint256 maxSafeSize,
        uint256 timestamp,
        address indexed caller
    );
    event OracleChanged(address indexed previousOracle, address indexed newOracle);

    function setUp() public {
        // Vektor chainId 43113 icin uretildi; digest chainid'i icerir.
        vm.chainId(FUJI_CHAIN_ID);
        oracle = vm.addr(ORACLE_PK);

        vm.prank(DEPLOYER);
        breaker = new RiskCircuitBreaker(oracle, THRESHOLD);

        vectorJson = vm.readFile("test/vector.json");
        vSymbolHash = vm.parseJsonBytes32(vectorJson, ".symbolHash");
        vSide = uint8(vm.parseJsonUint(vectorJson, ".sideInt"));
        vRiskScore = vm.parseJsonUint(vectorJson, ".riskScore");
        vMaxSafeSize = vm.parseJsonUint(vectorJson, ".maxSafeSize");
        vTimestamp = vm.parseJsonUint(vectorJson, ".timestamp");
        vDigest = vm.parseJsonBytes32(vectorJson, ".digest");
        vSignature = vm.parseJsonBytes(vectorJson, ".signature");

        // Vektor, testin deploy ettigi adres icin uretilmis olmali:
        // digest kontrat adresini de kapsiyor.
        vm.assertEq(
            address(breaker),
            vm.parseJsonAddress(vectorJson, ".contract"),
            "vector.json baska bir kontrat adresi icin uretilmis: signer.py --vector ile yenile"
        );
        vm.assertEq(
            vm.parseJsonUint(vectorJson, ".chainId"), FUJI_CHAIN_ID, "vektor chainId uyusmuyor"
        );
        vm.assertEq(vm.parseJsonAddress(vectorJson, ".signer"), oracle, "vektor imzalayicisi oracle degil");

        // Skoru taze yap: uretiminden 10 sn sonrasi
        vm.warp(vTimestamp + 10);
    }

    // --- yardimcilar ---------------------------------------------------------

    /// @dev EIP-191: keccak256("\x19Ethereum Signed Message:\n32" || digest)
    function _ethHash(bytes32 digest) internal pure returns (bytes32) {
        return keccak256(abi.encodePacked("\x19Ethereum Signed Message:\n32", digest));
    }

    function _sign(uint256 pk, bytes32 digest) internal pure returns (bytes memory) {
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(pk, _ethHash(digest));
        return abi.encodePacked(r, s, v);
    }

    /// @dev Verilen alanlar icin digest uretip imzalar.
    function _attest(uint256 pk, uint8 side, uint256 riskScore, uint256 maxSafeSize, uint256 ts)
        internal
        view
        returns (bytes32 digest, bytes memory sig)
    {
        digest = breaker.attestationDigest(vSymbolHash, side, riskScore, maxSafeSize, ts);
        sig = _sign(pk, digest);
    }

    // --- 1) Python <-> Solidity byte uyumu -----------------------------------

    function test_DigestMatchesPython() public {
        bytes32 onchain = breaker.attestationDigest(vSymbolHash, vSide, vRiskScore, vMaxSafeSize, vTimestamp);
        vm.assertEq(onchain, vDigest, "Solidity digest Python digest'inden farkli");

        // Python'un imzasi zincirde kabul ediliyor mu (amount = guvenli tutar)
        breaker.executeIntent(
            vSymbolHash, vSide, vMaxSafeSize, vRiskScore, vMaxSafeSize, vTimestamp, vSignature
        );
        vm.assertTrue(breaker.used(vDigest), "imza harcanmis olarak isaretlenmedi");
    }

    // --- 2) mutlu yol --------------------------------------------------------

    function test_HappyPath() public {
        uint256 amount = 800 * USDT;
        (, bytes memory sig) = _attest(ORACLE_PK, 0, 4200, 1000 * USDT, vTimestamp);

        vm.expectEmit(address(breaker));
        emit IntentApproved(vSymbolHash, 0, amount, 4200, 1000 * USDT, vTimestamp, address(this));

        breaker.executeIntent(vSymbolHash, 0, amount, 4200, 1000 * USDT, vTimestamp, sig);
    }

    // --- 3) guvenli tutar asimi ---------------------------------------------

    function test_RevertExceedsSafeSize() public {
        uint256 amount = 10000 * USDT;
        uint256 maxSafe = 1000 * USDT;
        (, bytes memory sig) = _attest(ORACLE_PK, 0, 4200, maxSafe, vTimestamp);

        vm.expectRevert(
            abi.encodeWithSelector(RiskCircuitBreaker.ExceedsSafeSize.selector, amount, maxSafe, 10)
        );
        breaker.executeIntent(vSymbolHash, 0, amount, 4200, maxSafe, vTimestamp, sig);
    }

    // --- 4) bayatlik ---------------------------------------------------------

    function test_RevertStale() public {
        (, bytes memory sig) = _attest(ORACLE_PK, 0, 4200, 1000 * USDT, vTimestamp);

        vm.warp(vTimestamp + 301);
        vm.expectRevert(
            abi.encodeWithSelector(RiskCircuitBreaker.StaleScore.selector, vTimestamp, vTimestamp + 301)
        );
        breaker.executeIntent(vSymbolHash, 0, 800 * USDT, 4200, 1000 * USDT, vTimestamp, sig);
    }

    function test_RevertFutureTimestamp() public {
        uint256 future = vTimestamp + 10 + 61; // simdi + 61 sn
        (, bytes memory sig) = _attest(ORACLE_PK, 0, 4200, 1000 * USDT, future);

        vm.expectRevert(
            abi.encodeWithSelector(RiskCircuitBreaker.StaleScore.selector, future, vTimestamp + 10)
        );
        breaker.executeIntent(vSymbolHash, 0, 800 * USDT, 4200, 1000 * USDT, future, sig);
    }

    // --- 5) yabanci imza -----------------------------------------------------

    function test_RevertBadSigner() public {
        (, bytes memory sig) = _attest(OTHER_PK, 0, 4200, 1000 * USDT, vTimestamp);

        vm.expectRevert(
            abi.encodeWithSelector(RiskCircuitBreaker.BadSigner.selector, vm.addr(OTHER_PK))
        );
        breaker.executeIntent(vSymbolHash, 0, 800 * USDT, 4200, 1000 * USDT, vTimestamp, sig);
    }

    // --- 6) tekrar kullanim --------------------------------------------------

    function test_RevertReplay() public {
        (bytes32 digest, bytes memory sig) = _attest(ORACLE_PK, 0, 4200, 1000 * USDT, vTimestamp);

        breaker.executeIntent(vSymbolHash, 0, 800 * USDT, 4200, 1000 * USDT, vTimestamp, sig);

        vm.expectRevert(abi.encodeWithSelector(RiskCircuitBreaker.AlreadyUsed.selector, digest));
        breaker.executeIntent(vSymbolHash, 0, 800 * USDT, 4200, 1000 * USDT, vTimestamp, sig);
    }

    // --- 7) risk esigi -------------------------------------------------------

    function test_RevertRiskTooHigh() public {
        (, bytes memory sig) = _attest(ORACLE_PK, 0, 9000, 1000 * USDT, vTimestamp);

        vm.expectRevert(
            abi.encodeWithSelector(RiskCircuitBreaker.RiskTooHigh.selector, 9000, THRESHOLD)
        );
        breaker.executeIntent(vSymbolHash, 0, 800 * USDT, 9000, 1000 * USDT, vTimestamp, sig);
    }

    // --- 8) guvenli tutar yok ------------------------------------------------

    function test_RevertNoSafeSize() public {
        (, bytes memory sig) = _attest(ORACLE_PK, 0, 4200, 0, vTimestamp);

        vm.expectRevert(abi.encodeWithSelector(RiskCircuitBreaker.NoSafeSize.selector));
        breaker.executeIntent(vSymbolHash, 0, 800 * USDT, 4200, 0, vTimestamp, sig);
    }

    // --- 9) gecersiz yon -----------------------------------------------------

    function test_RevertBadSide() public {
        (, bytes memory sig) = _attest(ORACLE_PK, 2, 4200, 1000 * USDT, vTimestamp);

        vm.expectRevert(abi.encodeWithSelector(RiskCircuitBreaker.BadSide.selector, uint8(2)));
        breaker.executeIntent(vSymbolHash, 2, 800 * USDT, 4200, 1000 * USDT, vTimestamp, sig);
    }

    // --- 10) durdurma --------------------------------------------------------

    function test_PauseBlocks() public {
        (, bytes memory sig) = _attest(ORACLE_PK, 0, 4200, 1000 * USDT, vTimestamp);

        vm.prank(DEPLOYER); // owner
        breaker.pause();

        vm.expectRevert(abi.encodeWithSelector(Pausable.EnforcedPause.selector));
        breaker.executeIntent(vSymbolHash, 0, 800 * USDT, 4200, 1000 * USDT, vTimestamp, sig);
    }

    // --- 11) yetki -----------------------------------------------------------

    function test_SetOracleOnlyOwner() public {
        vm.expectRevert(
            abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, STRANGER)
        );
        vm.prank(STRANGER);
        breaker.setOracle(STRANGER);
    }

    // --- 12) oracle rotasyonu ------------------------------------------------

    function test_SetOracleRotates() public {
        (, bytes memory oldSig) = _attest(ORACLE_PK, 0, 4200, 1000 * USDT, vTimestamp);
        address newOracle = vm.addr(OTHER_PK);

        vm.expectEmit(address(breaker));
        emit OracleChanged(oracle, newOracle);
        vm.prank(DEPLOYER);
        breaker.setOracle(newOracle);

        vm.assertEq(breaker.oracle(), newOracle, "oracle degismedi");

        // Eski oracle'in imzasi artik kabul edilmiyor
        vm.expectRevert(abi.encodeWithSelector(RiskCircuitBreaker.BadSigner.selector, oracle));
        breaker.executeIntent(vSymbolHash, 0, 800 * USDT, 4200, 1000 * USDT, vTimestamp, oldSig);

        // Yeni oracle'in imzasi geciyor
        (, bytes memory newSig) = _attest(OTHER_PK, 0, 4200, 1000 * USDT, vTimestamp);
        breaker.executeIntent(vSymbolHash, 0, 800 * USDT, 4200, 1000 * USDT, vTimestamp, newSig);
    }

    // --- 13) esik degisimi ---------------------------------------------------

    function test_SetRiskThresholdOnlyOwner() public {
        vm.expectRevert(
            abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, STRANGER)
        );
        vm.prank(STRANGER);
        breaker.setRiskThreshold(9999);

        vm.prank(DEPLOYER);
        breaker.setRiskThreshold(9999);
        vm.assertEq(breaker.riskThreshold(), 9999, "esik degismedi");
    }
}
