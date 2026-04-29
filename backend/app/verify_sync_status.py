from __future__ import annotations

from datetime import datetime

from backend.app.database import get_connection
from backend.app.main import _build_issue_hash_payload, _compute_hash, _get_onchain_hash, _init_blockchain_client


def main() -> None:
    _init_blockchain_client()

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
            rows = cursor.fetchall()

    print(f"Total issues: {len(rows)}")

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
        recomputed_hash = _compute_hash(payload)
        db_hash = (row.get("hash") or "").lower()
        onchain_hash = (_get_onchain_hash(issue_id) or "").lower()

        db_match = db_hash == recomputed_hash.lower()
        onchain_match = onchain_hash == recomputed_hash.lower()

        print(f"Issue: {issue_id}")
        print(f"  DB match: {db_match}")
        print(f"  On-chain match: {onchain_match}")
        print(f"  DB hash: {db_hash}")
        print(f"  Recomputed: {recomputed_hash.lower()}")
        print(f"  On-chain: {onchain_hash}")


if __name__ == "__main__":
    main()
