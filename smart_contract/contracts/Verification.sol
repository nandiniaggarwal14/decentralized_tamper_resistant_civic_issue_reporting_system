// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract Verification {
    address public owner;
    mapping(uint256 => string) private issueHashes;

    event HashStored(uint256 indexed issueId, string dataHash);

    modifier onlyOwner() {
        require(msg.sender == owner, "Only owner can call this function");
        _;
    }

    constructor() {
        owner = msg.sender;
    }

    function storeHash(uint256 issueId, string memory dataHash) external onlyOwner {
        issueHashes[issueId] = dataHash;
        emit HashStored(issueId, dataHash);
    }

    function getHash(uint256 issueId) external view returns (string memory) {
        return issueHashes[issueId];
    }
}
