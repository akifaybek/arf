// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice Foundry cheatcode arayuzunun bu projede kullanilan ASGARI alt kumesi.
/// @dev forge-std KULLANILMIYOR: npm'deki `forge-std` paketi ucuncu taraf
///      ("Unofficial NPM distribution"), `forge install` ise git'e yazar.
///      Asagidaki bildirimler EZBERDEN YAZILMADI; forge 1.7.1 ikilisinin
///      gomulu cheatcode tablosundan aynen cikarildi:
///        strings -a $(which forge) | grep -oE "function (sign|warp|...)\([^;]*;"
///      Cheatcode adresi de ayni ikiliden dogrulandi:
///        address(uint160(uint256(keccak256("hevm cheat code"))))
///        = 0x7109709ECfa91a80626fF3989D68f67F5b1DD12D
interface Vm {
    // --- imza / adres ---
    function sign(uint256 privateKey, bytes32 digest)
        external
        pure
        returns (uint8 v, bytes32 r, bytes32 s);
    function addr(uint256 privateKey) external pure returns (address keyAddr);
    function computeCreateAddress(address deployer, uint256 nonce) external pure returns (address);

    // --- ortam ---
    function warp(uint256 newTimestamp) external;
    function chainId(uint256 newChainId) external;
    function prank(address msgSender) external;

    // --- beklentiler ---
    function expectRevert(bytes calldata revertData) external;
    function expectEmit(address emitter) external;

    // --- dosya / JSON ---
    function readFile(string calldata path) external view returns (string memory data);
    function parseJsonBytes32(string calldata json, string calldata key) external pure returns (bytes32);
    function parseJsonBytes(string calldata json, string calldata key) external pure returns (bytes memory);
    function parseJsonUint(string calldata json, string calldata key) external pure returns (uint256);
    function parseJsonAddress(string calldata json, string calldata key) external pure returns (address);

    // --- iddialar (assertions_revert = true oldugu icin basarisizlikta revert) ---
    function assertEq(bytes32 left, bytes32 right, string calldata err) external pure;
    function assertEq(uint256 left, uint256 right, string calldata err) external pure;
    function assertEq(address left, address right, string calldata err) external pure;
    function assertTrue(bool condition, string calldata err) external pure;
    function assertFalse(bool condition, string calldata err) external pure;
}
