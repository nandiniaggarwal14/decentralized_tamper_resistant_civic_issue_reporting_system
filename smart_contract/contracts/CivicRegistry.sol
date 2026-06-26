// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title CivicRegistry
 * @notice Unified on-chain registry for the Decentralized Tamper-Resistant
 *         Civic Issue Reporting System.  Stores two kinds of integrity hashes:
 *
 *         1. Issue Hashes   – SHA-256 digest of every citizen-submitted issue.
 *         2. Completion Hashes – SHA-256 digest of every government-uploaded
 *            resolution proof, binding the completion evidence to the issue.
 *
 *         Both mappings are keyed by the uint256 representation of the issue's
 *         UUID so that a single contract address covers the full lifecycle of
 *         an issue (submission → verification → resolution → proof).
 *
 * @dev    Only the deployer (owner) may write hashes.  Read access is public.
 *         The original Verification.sol is kept for backward compatibility;
 *         new issues should target this contract.
 */
contract CivicRegistry {
    // -----------------------------------------------------------------------
    // State
    // -----------------------------------------------------------------------
    address public owner;
    
    /// @notice Whitelist of addresses allowed to write hashes.
    mapping(address => bool) public authorizedCallers;

    /// @notice SHA-256 hash of the original issue data, keyed by issue UUID.
    mapping(uint256 => string) private issueHashes;

    /// @notice SHA-256 hash of the government completion-proof data.
    mapping(uint256 => string) private completionHashes;

    /// @notice SHA-256 hash of ward member or authority profile data, keyed by user UUID.
    mapping(uint256 => string) private personnelHashes;

    // -----------------------------------------------------------------------
    // Events
    // -----------------------------------------------------------------------

    /// @notice Emitted when a new issue hash is stored.
    event IssueHashStored(uint256 indexed issueId, string dataHash);

    /// @notice Emitted when a completion / resolution hash is stored.
    event CompletionHashStored(uint256 indexed issueId, string dataHash);

    /// @notice Emitted when a ward member or authority profile hash is stored.
    event PersonnelHashStored(uint256 indexed userId, string dataHash);

    /// @notice Emitted when an address authorization status changes.
    event CallerAuthorized(address indexed caller, bool status);


    // -----------------------------------------------------------------------
    // Modifiers
    // -----------------------------------------------------------------------

    modifier onlyOwner() {
        require(msg.sender == owner, "CivicRegistry: caller is not the owner");
        _;
    }

    modifier onlyAuthorized() {
        require(msg.sender == owner || authorizedCallers[msg.sender], "CivicRegistry: caller is not authorized");
        _;
    }

    // -----------------------------------------------------------------------
    // Constructor
    // -----------------------------------------------------------------------

    constructor() {
        owner = msg.sender;
        authorizedCallers[msg.sender] = true;
    }

    // -----------------------------------------------------------------------
    // Authorization management
    // -----------------------------------------------------------------------

    /**
     * @notice Authorize or deauthorize a wallet address to write hashes.
     * @param account The wallet address to change authorization for.
     * @param status True to authorize, False to revoke access.
     */
    function authorizeAddress(address account, bool status) external onlyOwner {
        authorizedCallers[account] = status;
        emit CallerAuthorized(account, status);
    }

    // -----------------------------------------------------------------------
    // Issue Hash — Write & Read
    // -----------------------------------------------------------------------

    /**
     * @notice Store the integrity hash for a citizen-submitted issue.
     * @param issueId  uint256 representation of the issue UUID.
     * @param dataHash SHA-256 hex digest of the canonical issue payload.
     */
    function storeIssueHash(uint256 issueId, string memory dataHash) external onlyAuthorized {
        issueHashes[issueId] = dataHash;
        emit IssueHashStored(issueId, dataHash);
    }

    /**
     * @notice Retrieve the stored issue hash for verification.
     * @param issueId uint256 representation of the issue UUID.
     * @return The stored SHA-256 hex digest (empty string if not set).
     */
    function getIssueHash(uint256 issueId) external view returns (string memory) {
        return issueHashes[issueId];
    }

    // -----------------------------------------------------------------------
    // Completion Hash — Write & Read
    // -----------------------------------------------------------------------

    /**
     * @notice Store the integrity hash for a government completion proof.
     * @param issueId  uint256 representation of the issue UUID.
     * @param dataHash SHA-256 hex digest of the completion proof payload.
     */
    function storeCompletionHash(uint256 issueId, string memory dataHash) external onlyAuthorized {
        completionHashes[issueId] = dataHash;
        emit CompletionHashStored(issueId, dataHash);
    }

    /**
     * @notice Retrieve the stored completion hash for verification.
     * @param issueId uint256 representation of the issue UUID.
     * @return The stored SHA-256 hex digest (empty string if not set).
     */
    function getCompletionHash(uint256 issueId) external view returns (string memory) {
        return completionHashes[issueId];
    }

    // -----------------------------------------------------------------------
    // Personnel Hash — Write & Read
    // -----------------------------------------------------------------------

    /**
     * @notice Store the integrity hash for a ward member or government official profile.
     * @param userId   uint256 representation of the user UUID.
     * @param dataHash SHA-256 hex digest of the canonical profile payload.
     */
    function storePersonnelHash(uint256 userId, string memory dataHash) external onlyAuthorized {
        personnelHashes[userId] = dataHash;
        emit PersonnelHashStored(userId, dataHash);
    }

    /**
     * @notice Retrieve the stored profile hash for verification.
     * @param userId uint256 representation of the user UUID.
     * @return The stored SHA-256 hex digest (empty string if not set).
     */
    function getPersonnelHash(uint256 userId) external view returns (string memory) {
        return personnelHashes[userId];
    }
}
