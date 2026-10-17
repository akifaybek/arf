// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";
import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import {MessageHashUtils} from "@openzeppelin/contracts/utils/cryptography/MessageHashUtils.sol";

/// @title RiskCircuitBreaker — Arf icra kalkaninin zincir tarafi
/// @notice Tek bir degismezi korur: hicbir emir, tahtanin o an tasiyabilecegi
///         tutardan (maxSafeSize) buyuk olamaz. Niyet imzasiz, bayat veya
///         guvenli tutarin uzerindeyse islem geri doner (fail-closed).
/// @dev Skor ve maxSafeSize zincir disinda deterministik olarak hesaplanir ve
///      oracle anahtariyla EIP-191 formatinda imzalanir. Kontrat sadece
///      dogrular; hesap yapmaz.
contract RiskCircuitBreaker is Ownable, Pausable {
    using MessageHashUtils for bytes32;

    /// @notice Skoru imzalamaya yetkili adres
    address public oracle;

    /// @notice Kabul edilen en yuksek risk skoru (0-10000; yuksek = riskli)
    uint256 public riskThreshold;

    /// @notice Skorun en fazla ne kadar eski olabilecegi (saniye)
    uint256 public constant MAX_AGE = 300;

    /// @notice Saat sapmasi icin izin verilen ileri zaman payi (saniye)
    uint256 public constant MAX_FUTURE = 60;

    /// @notice Harcanmis imzalar (tekrar kullanim engeli)
    mapping(bytes32 => bool) public used;

    /// @notice Niyet onaylandi; amount guvenli tutarin icinde
    event IntentApproved(
        bytes32 indexed symbolHash,
        uint8 side,
        uint256 amount,
        uint256 riskScore,
        uint256 maxSafeSize,
        uint256 timestamp,
        address indexed caller
    );

    /// @notice Oracle adresi degisti (anahtar sizmasinda kullanilir)
    event OracleChanged(address indexed previousOracle, address indexed newOracle);

    /// @notice Risk esigi degisti
    event RiskThresholdChanged(uint256 previousThreshold, uint256 newThreshold);

    /// @dev side yalnizca 0 (alis) veya 1 (satis) olabilir
    error BadSide(uint8 side);
    /// @dev Skor bayat ya da gelecekte
    error StaleScore(uint256 scoreTimestamp, uint256 blockTimestamp);
    /// @dev Imzayi atan adres oracle degil
    error BadSigner(address recovered);
    /// @dev Ayni imza daha once harcanmis
    error AlreadyUsed(bytes32 digest);
    /// @dev Risk skoru esigin uzerinde
    error RiskTooHigh(uint256 riskScore, uint256 threshold);
    /// @dev Bu tahtada guvenli tutar yok
    error NoSafeSize();
    /// @dev Emir guvenli tutari asiyor; suggestedParts kadar parcaya bolunmeli
    error ExceedsSafeSize(uint256 amount, uint256 maxSafeSize, uint256 suggestedParts);
    /// @dev Sifir adres kabul edilmez
    error ZeroAddress();

    /// @param initialOracle Skoru imzalayacak adres
    /// @param initialThreshold Baslangic risk esigi (0-10000)
    constructor(address initialOracle, uint256 initialThreshold) Ownable(msg.sender) {
        if (initialOracle == address(0)) revert ZeroAddress();
        oracle = initialOracle;
        riskThreshold = initialThreshold;
    }

    /// @notice Imzalanan ham payload'in keccak ozeti (Python imzalayici ile
    ///         byte uyumunu kanitlamak icin disa acildi).
    /// @dev encodePacked DEGIL; sabit genislikli abi.encode kullanilir.
    ///      chainid ve kontrat adresi payload'a girer: baska agdaki ya da
    ///      baska kontrattaki imza burada gecersizdir.
    function attestationDigest(
        bytes32 symbolHash,
        uint8 side,
        uint256 riskScore,
        uint256 maxSafeSize,
        uint256 timestamp
    ) public view returns (bytes32) {
        return keccak256(
            abi.encode(symbolHash, side, riskScore, maxSafeSize, timestamp, block.chainid, address(this))
        );
    }

    /// @notice Imzali skoru dogrular ve emir tutarini guvenli tutarla karsilastirir.
    /// @param symbolHash keccak256(bytes("BTC-USDT"))
    /// @param side 0 = alis, 1 = satis
    /// @param amount Emir tutari, USDT x 1e6
    /// @param riskScore 0-10000, yuksek = riskli
    /// @param maxSafeSize Guvenli tutar, USDT x 1e6
    /// @param timestamp Skorun uretildigi an (unix saniye)
    /// @param sig Oracle'in EIP-191 imzasi (65 byte)
    function executeIntent(
        bytes32 symbolHash,
        uint8 side,
        uint256 amount,
        uint256 riskScore,
        uint256 maxSafeSize,
        uint256 timestamp,
        bytes calldata sig
    ) external whenNotPaused {
        // 1) Yon gecerli mi (alis onayi satista kullanilamaz; side imzaya girer)
        if (side > 1) revert BadSide(side);

        // 2) Tazelik: ne bayat ne de gelecekten
        if (block.timestamp > timestamp + MAX_AGE || timestamp > block.timestamp + MAX_FUTURE) {
            revert StaleScore(timestamp, block.timestamp);
        }

        bytes32 digest = attestationDigest(symbolHash, side, riskScore, maxSafeSize, timestamp);

        // 3) Imza oracle'a mi ait
        address recovered = ECDSA.recover(digest.toEthSignedMessageHash(), sig);
        if (recovered != oracle) revert BadSigner(recovered);

        // 4) Ayni imza ikinci kez kullanilamaz
        if (used[digest]) revert AlreadyUsed(digest);

        // 5) Risk esigi
        if (riskScore > riskThreshold) revert RiskTooHigh(riskScore, riskThreshold);

        // 6) Tahtada guvenli tutar yok
        if (maxSafeSize == 0) revert NoSafeSize();

        // 7) Emir guvenli tutari asiyor: kac parcaya bolunecegini de soyle
        if (amount > maxSafeSize) {
            // maxSafeSize > 0 oldugu 6. adimda garanti; sifira bolme yok
            uint256 suggestedParts = (amount + maxSafeSize - 1) / maxSafeSize;
            revert ExceedsSafeSize(amount, maxSafeSize, suggestedParts);
        }

        used[digest] = true;
        emit IntentApproved(symbolHash, side, amount, riskScore, maxSafeSize, timestamp, msg.sender);
    }

    /// @notice Oracle adresini degistirir (anahtar sizmasinda: pause + setOracle)
    function setOracle(address newOracle) external onlyOwner {
        if (newOracle == address(0)) revert ZeroAddress();
        address previous = oracle;
        oracle = newOracle;
        emit OracleChanged(previous, newOracle);
    }

    /// @notice Risk esigini degistirir; esik zincirde gorunur kalir
    function setRiskThreshold(uint256 newThreshold) external onlyOwner {
        uint256 previous = riskThreshold;
        riskThreshold = newThreshold;
        emit RiskThresholdChanged(previous, newThreshold);
    }

    /// @notice Tum niyetleri durdurur (acil durum)
    function pause() external onlyOwner {
        _pause();
    }

    /// @notice Durdurmayi kaldirir
    function unpause() external onlyOwner {
        _unpause();
    }
}
