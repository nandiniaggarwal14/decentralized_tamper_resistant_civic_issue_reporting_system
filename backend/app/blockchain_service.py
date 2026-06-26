import os
import json
import hashlib
import uuid
import time
from pathlib import Path
from typing import Any, Optional
from fastapi import HTTPException

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

INFURA_URL = os.getenv("INFURA_URL", "").strip()
CONTRACT_ADDRESS = os.getenv("CONTRACT_ADDRESS", "").strip()
WALLET_PRIVATE_KEY = os.getenv("WALLET_PRIVATE_KEY", "").strip()
CHAIN_ID = int(os.getenv("CHAIN_ID", "11155111"))

# Determine which ABI to use (prefer CivicRegistry if compiled)
CIVIC_REGISTRY_ABI = PROJECT_ROOT / "backend" / "app" / "abis" / "CivicRegistry.json"
FAILED_TX_LOG = PROJECT_ROOT / "failed_transactions.json"

web3_client = None
contract_instance = None
signer_account = None

def _log_failed_transaction(tx_details: dict) -> None:
    try:
        records = []
        if FAILED_TX_LOG.exists():
            try:
                records = json.loads(FAILED_TX_LOG.read_text(encoding="utf-8"))
            except Exception:
                records = []
        records.append(tx_details)
        FAILED_TX_LOG.write_text(json.dumps(records, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"Failed to log transaction to file: {e}")

def _uuid_to_uint256(value: str) -> int:
    return uuid.UUID(value).int

def init_blockchain() -> None:
    global web3_client, contract_instance, signer_account
    from web3 import Web3

    if not INFURA_URL or not CONTRACT_ADDRESS or not WALLET_PRIVATE_KEY:
        # Mock mode enabled silently
        return

    abi_path = CIVIC_REGISTRY_ABI
    if not abi_path.exists():
        # Fallback to smart_contract build if it exists
        candidate = PROJECT_ROOT / "smart_contract" / "artifacts" / "contracts" / "CivicRegistry.sol" / "CivicRegistry.json"
        if candidate.exists():
            try:
                build_info = json.loads(candidate.read_text(encoding="utf-8"))
                abi = build_info.get("abi")
                # Write it locally for fast caching
                CIVIC_REGISTRY_ABI.write_text(json.dumps(abi), encoding="utf-8")
                abi_path = CIVIC_REGISTRY_ABI
            except Exception:
                pass

    if not abi_path.exists():
        return

    try:
        abi = json.loads(abi_path.read_text(encoding="utf-8"))
        # If compiled artifacts from hardhat are loaded, extract ABI field
        if isinstance(abi, dict) and "abi" in abi:
            abi = abi["abi"]

        web3_client = Web3(Web3.HTTPProvider(INFURA_URL))
        if web3_client.is_connected():
            checksummed_address = web3_client.to_checksum_address(CONTRACT_ADDRESS)
            contract_instance = web3_client.eth.contract(address=checksummed_address, abi=abi)
            signer_account = web3_client.eth.account.from_key(WALLET_PRIVATE_KEY)
    except Exception as e:
        print(f"Error initializing blockchain: {e}. Falling back to mock mode.")
        web3_client = None
        contract_instance = None
        signer_account = None

def is_blockchain_active() -> bool:
    return web3_client is not None and contract_instance is not None and signer_account is not None

def get_wallet_address() -> Optional[str]:
    """Return the wallet address used for signing transactions, or None if not active."""
    if signer_account is not None:
        return signer_account.address
    return None

def get_wallet_balance() -> Optional[int]:
    """Return the wallet balance in Wei, or None if blockchain is not active."""
    if web3_client is not None and signer_account is not None:
        try:
            return web3_client.eth.get_balance(signer_account.address)
        except Exception:
            return None
    return None

def _queue_failed_transaction(function_name: str, args: dict, error_message: str) -> None:
    from backend.app.database import get_connection
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO failed_blockchain_txns (function_name, args_json, error_message)
                    VALUES (%s, %s, %s)
                    """,
                    (function_name, json.dumps(args), error_message)
                )
            conn.commit()
        print(f"Logged failed txn {function_name} to database queue.")
    except Exception as db_err:
        print(f"Failed to log transaction to database: {db_err}")
        _log_failed_transaction({
            "function_name": function_name,
            "args": args,
            "error_message": error_message,
            "timestamp": time.time()
        })

def _store_issue_hash_onchain(issue_id: str, data_hash: str) -> str:
    w3: Any = web3_client
    contract: Any = contract_instance
    signer: Any = signer_account

    nonce = w3.eth.get_transaction_count(signer.address)
    contract_issue_id = _uuid_to_uint256(issue_id)
    
    if hasattr(contract.functions, "storeIssueHash"):
        func = contract.functions.storeIssueHash(contract_issue_id, data_hash)
    else:
        func = contract.functions.storeHash(contract_issue_id, data_hash)

    tx = func.build_transaction({
        "from": signer.address,
        "nonce": nonce,
        "chainId": CHAIN_ID,
        "gasPrice": w3.eth.gas_price,
    })
    tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.2)

    signed_txn = signer.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed_txn.raw_transaction)
    
    try:
        from web3.exceptions import TimeExhausted, TransactionNotFound, Web3Exception
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
    except TimeExhausted:
        raise RuntimeError("Transaction receipt wait timed out (TimeExhausted)")
    except TransactionNotFound:
        raise RuntimeError("Transaction not found on chain (TransactionNotFound)")
    except Web3Exception as wexc:
        raise RuntimeError(f"Web3 protocol exception: {wexc}")
        
    if receipt.status != 1:
        raise RuntimeError("On-chain hash transaction failed (receipt status 0)")
    return receipt.transactionHash.hex()

def store_issue_hash(issue_id: str, data_hash: str) -> str:
    """Store the hash of an issue on chain. Falls back to mock hash if blockchain is inactive."""
    if not is_blockchain_active():
        return "mock_tx_" + hashlib.sha256((issue_id + data_hash).encode()).hexdigest()

    try:
        return _store_issue_hash_onchain(issue_id, data_hash)
    except Exception as e:
        _queue_failed_transaction(
            function_name="store_issue_hash",
            args={"issue_id": issue_id, "data_hash": data_hash},
            error_message=str(e)
        )
        return "queued_tx_" + hashlib.sha256((issue_id + data_hash).encode()).hexdigest()

def get_issue_hash(issue_id: str) -> Optional[str]:
    """Retrieve the issue hash from the blockchain. Returns None if inactive or not found."""
    if not is_blockchain_active():
        return None

    contract: Any = contract_instance
    contract_issue_id = _uuid_to_uint256(issue_id)
    
    try:
        if hasattr(contract.functions, "getIssueHash"):
            return contract.functions.getIssueHash(contract_issue_id).call()
        else:
            return contract.functions.getHash(contract_issue_id).call()
    except Exception:
        return None

def _store_completion_hash_onchain(issue_id: str, completion_hash: str) -> str:
    w3: Any = web3_client
    contract: Any = contract_instance
    signer: Any = signer_account

    nonce = w3.eth.get_transaction_count(signer.address)
    contract_issue_id = _uuid_to_uint256(issue_id)
    
    if not hasattr(contract.functions, "storeCompletionHash"):
        return "mock_completion_tx_no_contract_support"

    tx = contract.functions.storeCompletionHash(contract_issue_id, completion_hash).build_transaction({
        "from": signer.address,
        "nonce": nonce,
        "chainId": CHAIN_ID,
        "gasPrice": w3.eth.gas_price,
    })
    tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.2)

    signed_txn = signer.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed_txn.raw_transaction)
    
    try:
        from web3.exceptions import TimeExhausted, TransactionNotFound, Web3Exception
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
    except TimeExhausted:
        raise RuntimeError("Transaction receipt wait timed out (TimeExhausted)")
    except TransactionNotFound:
        raise RuntimeError("Transaction not found on chain (TransactionNotFound)")
    except Web3Exception as wexc:
        raise RuntimeError(f"Web3 protocol exception: {wexc}")
        
    if receipt.status != 1:
        raise RuntimeError("On-chain completion hash transaction failed (receipt status 0)")
    return receipt.transactionHash.hex()

def store_completion_hash(issue_id: str, completion_hash: str) -> str:
    """Store the resolution hash on chain."""
    if not is_blockchain_active():
        return "mock_completion_tx_" + hashlib.sha256((issue_id + completion_hash).encode()).hexdigest()

    try:
        return _store_completion_hash_onchain(issue_id, completion_hash)
    except Exception as e:
        _queue_failed_transaction(
            function_name="store_completion_hash",
            args={"issue_id": issue_id, "completion_hash": completion_hash},
            error_message=str(e)
        )
        return "queued_completion_tx_" + hashlib.sha256((issue_id + completion_hash).encode()).hexdigest()

def get_completion_hash(issue_id: str) -> Optional[str]:
    """Retrieve the resolution hash from the blockchain."""
    if not is_blockchain_active():
        return None

    contract: Any = contract_instance
    contract_issue_id = _uuid_to_uint256(issue_id)
    
    try:
        if hasattr(contract.functions, "getCompletionHash"):
            return contract.functions.getCompletionHash(contract_issue_id).call()
    except Exception:
        pass
    return None

def _store_personnel_hash_onchain(user_id: str, data_hash: str) -> str:
    w3: Any = web3_client
    contract: Any = contract_instance
    signer: Any = signer_account

    nonce = w3.eth.get_transaction_count(signer.address)
    contract_user_id = _uuid_to_uint256(user_id)
    
    if not hasattr(contract.functions, "storePersonnelHash"):
        return "mock_personnel_tx_no_contract_support"

    tx = contract.functions.storePersonnelHash(contract_user_id, data_hash).build_transaction({
        "from": signer.address,
        "nonce": nonce,
        "chainId": CHAIN_ID,
        "gasPrice": w3.eth.gas_price,
    })
    tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.2)

    signed_txn = signer.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed_txn.raw_transaction)

    try:
        from web3.exceptions import TimeExhausted, TransactionNotFound, Web3Exception
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
    except TimeExhausted:
        raise RuntimeError("Transaction receipt wait timed out (TimeExhausted)")
    except TransactionNotFound:
        raise RuntimeError("Transaction not found on chain (TransactionNotFound)")
    except Web3Exception as wexc:
        raise RuntimeError(f"Web3 protocol exception: {wexc}")
        
    if receipt.status != 1:
        raise RuntimeError("On-chain hash transaction failed (receipt status 0)")
    return receipt.transactionHash.hex()

def store_personnel_hash(user_id: str, data_hash: str) -> str:
    """Store the hash of personnel data on chain. Falls back to mock hash if blockchain is inactive."""
    if not is_blockchain_active():
        return "mock_tx_" + hashlib.sha256((user_id + data_hash).encode()).hexdigest()

    try:
        return _store_personnel_hash_onchain(user_id, data_hash)
    except Exception as e:
        _queue_failed_transaction(
            function_name="store_personnel_hash",
            args={"user_id": user_id, "data_hash": data_hash},
            error_message=str(e)
        )
        return "queued_tx_" + hashlib.sha256((user_id + data_hash).encode()).hexdigest()

def get_personnel_hash(user_id: str) -> Optional[str]:
    """Retrieve the personnel hash from the blockchain. Returns None if inactive or not found."""
    if not is_blockchain_active():
        return None

    contract: Any = contract_instance
    contract_user_id = _uuid_to_uint256(user_id)
    
    try:
        if hasattr(contract.functions, "getPersonnelHash"):
            return contract.functions.getPersonnelHash(contract_user_id).call()
    except Exception:
        pass
    return None

def retry_failed_transactions() -> tuple[int, int]:
    """Fetch all pending failed transactions and attempt to re-submit them to the blockchain."""
    from backend.app.database import get_connection
    if not is_blockchain_active():
        print("Blockchain is not active. Cannot retry transactions.")
        return 0, 0

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, function_name, args_json, retry_count
                FROM failed_blockchain_txns
                WHERE resolved_at IS NULL
                ORDER BY created_at ASC
                """
            )
            rows = cursor.fetchall()
            
    successes = 0
    failures = 0

    for row in rows:
        txn_id = row["id"]
        func_name = row["function_name"]
        try:
            args = json.loads(row["args_json"])
        except Exception:
            args = {}
            
        retry_count = row["retry_count"] + 1

        print(f"Retrying transaction {txn_id}: {func_name} (attempt {retry_count})...")
        try:
            if func_name == "store_issue_hash":
                issue_id = args.get("issue_id")
                data_hash = args.get("data_hash")
                if issue_id and data_hash:
                    _store_issue_hash_onchain(issue_id, data_hash)
            elif func_name == "store_completion_hash":
                issue_id = args.get("issue_id")
                completion_hash = args.get("completion_hash")
                if issue_id and completion_hash:
                    _store_completion_hash_onchain(issue_id, completion_hash)
            elif func_name == "store_personnel_hash":
                user_id = args.get("user_id")
                data_hash = args.get("data_hash")
                if user_id and data_hash:
                    _store_personnel_hash_onchain(user_id, data_hash)
            else:
                raise ValueError(f"Unknown function name in retry: {func_name}")
                
            # Success! Mark resolved
            with get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE failed_blockchain_txns
                        SET resolved_at = NOW(), retry_count = %s
                        WHERE id = %s
                        """,
                        (retry_count, txn_id)
                    )
                conn.commit()
            successes += 1
            print(f"Transaction {txn_id} successfully processed and resolved.")
        except Exception as e:
            # Failure: update error message and retry count
            with get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE failed_blockchain_txns
                        SET error_message = %s, retry_count = %s
                        WHERE id = %s
                        """,
                        (str(e), retry_count, txn_id)
                    )
                conn.commit()
            failures += 1
            print(f"Transaction {txn_id} retry failed: {e}")

    return successes, failures

# Initialize upon import
init_blockchain()
