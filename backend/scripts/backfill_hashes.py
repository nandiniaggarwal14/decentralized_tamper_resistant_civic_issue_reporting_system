from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List

from web3.exceptions import TimeExhausted

from backend.app.database import get_connection
from backend.app.main import (
    CHAIN_ID,
    _build_issue_hash_payload,
    _compute_hash,
    _get_onchain_hash,
    _init_blockchain_client,
    _require_blockchain,
    _uuid_to_uint256,
)


@dataclass
class BackfillResult:
    issue_id: str
    hash_value: str
    updated_db: bool
    pushed_onchain: bool
    pending_onchain: bool
    tx_hash: str | None
    error: str | None


def _fetch_issues() -> List[dict]:
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, title, description, category, area, address,
                       latitude, longitude, reporter_name, contact,
                       image_url, created_at, hash
                FROM issues
                ORDER BY created_at ASC
                """
            )
            return cursor.fetchall()


def _update_hash_in_db(issue_id: str, hash_value: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE issues
                SET hash = %s
                WHERE id = %s
                """,
                (hash_value, issue_id),
            )
        conn.commit()


def _push_hash_onchain(
    *,
    w3,
    contract,
    signer,
    issue_id: str,
    hash_value: str,
    nonce: int,
    wait_timeout: int = 45,
) -> tuple[bool, bool, str | None, int]:
    for attempt in range(2):
        try:
            tx = contract.functions.storeHash(_uuid_to_uint256(issue_id), hash_value).build_transaction(
                {
                    "from": signer.address,
                    "nonce": nonce,
                    "chainId": CHAIN_ID,
                    "gasPrice": int(w3.eth.gas_price * (1.15 + (0.1 * attempt))),
                }
            )
            tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.2)

            signed_txn = signer.sign_transaction(tx)
            tx_hash = w3.eth.send_raw_transaction(signed_txn.raw_transaction)
            tx_hash_hex = tx_hash.hex()

            try:
                receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=wait_timeout)
                return bool(receipt.status == 1), False, tx_hash_hex, nonce + 1
            except TimeExhausted:
                # Keep moving; transaction may still get mined shortly after timeout.
                return False, True, tx_hash_hex, nonce + 1
        except Exception as exc:
            if "replacement transaction underpriced" in str(exc).lower() and attempt == 0:
                nonce = w3.eth.get_transaction_count(signer.address, "pending")
                continue
            raise

    return False, False, None, nonce


def backfill_hashes() -> List[BackfillResult]:
    rows = _fetch_issues()
    results: List[BackfillResult] = []
    w3, contract, signer = _require_blockchain()
    next_nonce = w3.eth.get_transaction_count(signer.address, "pending")

    for row in rows:
        issue_id = str(row["id"])
        created_at: datetime = row["created_at"]

        payload = _build_issue_hash_payload(
            issue_id=issue_id,
            title=row["title"],
            description=row["description"],
            category=row["category"],
            area=row["area"],
            address=row["address"] or "",
            latitude=row["latitude"],
            longitude=row["longitude"],
            reporter_name=row["reporter_name"],
            contact=row["contact"] or "",
            image_url=row["image_url"] or "",
            created_at=created_at,
        )
        computed_hash = _compute_hash(payload)

        updated_db = (row.get("hash") or "").lower() != computed_hash.lower()
        if updated_db:
            _update_hash_in_db(issue_id, computed_hash)

        pushed_onchain = False
        pending_onchain = False
        tx_hash = None
        error = None

        try:
            onchain_hash = (_get_onchain_hash(issue_id) or "").lower()
            needs_onchain_push = onchain_hash != computed_hash.lower()
            if needs_onchain_push:
                pushed_onchain, pending_onchain, tx_hash, next_nonce = _push_hash_onchain(
                    w3=w3,
                    contract=contract,
                    signer=signer,
                    issue_id=issue_id,
                    hash_value=computed_hash,
                    nonce=next_nonce,
                )
        except Exception as exc:
            error = str(exc)

        results.append(
            BackfillResult(
                issue_id=issue_id,
                hash_value=computed_hash,
                updated_db=updated_db,
                pushed_onchain=pushed_onchain,
                pending_onchain=pending_onchain,
                tx_hash=tx_hash,
                error=error,
            )
        )

    return results


def main() -> None:
    _init_blockchain_client()
    results = backfill_hashes()

    total = len(results)
    db_updates = sum(1 for item in results if item.updated_db)
    chain_updates = sum(1 for item in results if item.pushed_onchain)
    chain_pending = sum(1 for item in results if item.pending_onchain)
    chain_errors = sum(1 for item in results if item.error)

    print(f"Total issues processed: {total}")
    print(f"Rows updated in Neon DB: {db_updates}")
    print(f"Hashes confirmed on Sepolia: {chain_updates}")
    print(f"Hashes pending confirmation: {chain_pending}")
    print(f"Rows with on-chain errors: {chain_errors}")

    for item in results:
        if item.tx_hash:
            print(f"Issue {item.issue_id} tx: {item.tx_hash}")
        if item.error:
            print(f"Issue {item.issue_id} error: {item.error}")


if __name__ == "__main__":
    main()
