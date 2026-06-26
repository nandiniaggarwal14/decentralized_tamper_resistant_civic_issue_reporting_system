import logging
import uuid
import hashlib
import json
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Form, UploadFile, File

from backend.app.database import get_connection
from backend.app.auth import RoleChecker, UserResponse
from backend.app.models import ProfileUpdateRequest, StatusRequest
from backend.app.helpers import anchor_authority_profile, _save_media_file, _serialize_issue, _assign_dynamic_priorities
import backend.app.ipfs_service as ipfs_service
import backend.app.blockchain_service as blockchain_service

router = APIRouter(prefix="/api/authority", tags=["authority"])

@router.get("/profile")
async def get_authority_profile(
    current_user: UserResponse = Depends(RoleChecker(["authority"]))
) -> dict:
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT gp.department_id, gp.designation, gp.ipfs_cid, gp.blockchain_hash,
                           d.name as department_name, u.full_name, u.contact, u.username
                    FROM users u
                    JOIN government_personnel gp ON u.id = gp.user_id
                    JOIN departments d ON gp.department_id = d.id
                    WHERE u.id = %s
                    """,
                    (current_user.id,)
                )
                row = cursor.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Authority profile not found")
        
        onchain_hash = blockchain_service.get_personnel_hash(current_user.id)
        db_hash = row["blockchain_hash"]
        is_verified = bool(db_hash and onchain_hash and db_hash.lower() == onchain_hash.lower())

        return {
            "success": True,
            "data": {
                "username": row["username"],
                "full_name": row["full_name"],
                "contact": row["contact"],
                "department_id": row["department_id"],
                "department_name": row["department_name"],
                "designation": row["designation"],
                "ipfs_cid": row["ipfs_cid"],
                "blockchain_hash": row["blockchain_hash"],
                "onchain_hash": onchain_hash,
                "is_verified": is_verified
            }
        }
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("Failed to fetch authority profile")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/profile")
async def update_authority_profile(
    req: ProfileUpdateRequest,
    current_user: UserResponse = Depends(RoleChecker(["authority"]))
) -> dict:
    try:
        designation = req.designation or "Department Official"
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE users SET full_name = %s, contact = %s WHERE id = %s",
                    (req.full_name, req.contact, current_user.id)
                )
                cursor.execute(
                    "UPDATE government_personnel SET designation = %s WHERE user_id = %s",
                    (designation, current_user.id)
                )
                cursor.execute("SELECT department_id FROM government_personnel WHERE user_id = %s", (current_user.id,))
                dept_row = cursor.fetchone()
                if not dept_row:
                    raise HTTPException(status_code=404, detail="Department not found for this official")
                department_id = dept_row["department_id"]
            conn.commit()

        await anchor_authority_profile(current_user.id, current_user.username, req.full_name, req.contact or "", department_id, designation)
        return {"success": True, "message": "Profile updated and anchored to blockchain successfully"}
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("Failed to update authority profile")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/stats")
async def get_authority_stats(
    current_user: UserResponse = Depends(RoleChecker(["authority"]))
) -> dict:
    try:
        dept_id = current_user.department_id
        if dept_id is None:
            raise HTTPException(status_code=400, detail="User has no department linked")

        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) as count FROM issues WHERE department_id = %s", (dept_id,))
                total_issues = cursor.fetchone()["count"]

                cursor.execute(
                    "SELECT status, COUNT(*) as count FROM issues WHERE department_id = %s GROUP BY status",
                    (dept_id,)
                )
                status_rows = cursor.fetchall()
                status_breakdown = {r["status"]: r["count"] for r in status_rows}

                resolved_count = status_breakdown.get("resolved", 0)
                resolution_rate = round((resolved_count / total_issues * 100), 1) if total_issues > 0 else 0.0

                cursor.execute(
                    """
                    SELECT AVG(EXTRACT(EPOCH FROM (h.created_at - i.created_at))) / 3600.0 as avg_time
                    FROM issues i
                    JOIN issue_status_history h ON i.id = h.issue_id
                    WHERE i.department_id = %s AND h.new_status = 'resolved'
                    """,
                    (dept_id,)
                )
                avg_time_row = cursor.fetchone()
                avg_res_time = round(avg_time_row["avg_time"], 1) if avg_time_row and avg_time_row["avg_time"] is not None else 0.0

                cursor.execute(
                    """
                    SELECT w.name as ward_name, COUNT(i.id) as count
                    FROM issues i
                    JOIN wards w ON i.ward_id = w.id
                    WHERE i.department_id = %s
                    GROUP BY w.name
                    ORDER BY count DESC
                    """,
                    (dept_id,)
                )
                ward_rows = cursor.fetchall()
                ward_distribution = {r["ward_name"]: r["count"] for r in ward_rows}

        return {
            "success": True,
            "data": {
                "total_issues": total_issues,
                "status_breakdown": status_breakdown,
                "resolution_rate": resolution_rate,
                "avg_res_time_hours": avg_res_time,
                "ward_distribution": ward_distribution
            }
        }
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("Failed to fetch authority statistics")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/issues")
async def get_authority_issues(current_user: UserResponse = Depends(RoleChecker(["authority"]))) -> dict:
    try:
        if current_user.department_id is None:
            raise HTTPException(status_code=400, detail="Authorized user has no department linked")
            
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT i.id, i.title, i.description, i.category, i.area, i.address,
                           i.latitude, i.longitude, i.reporter_name, i.contact,
                           i.image_url, i.status, i.created_at, i.hash,
                           i.priority, i.ward_id, w.name as ward_name,
                           i.department_id, d.name as department_name,
                           i.ipfs_cid, i.media_urls, i.completion_proof_ipfs_cid, i.completion_hash,
                           i.upvote_count, i.downvote_count
                    FROM issues i
                    LEFT JOIN wards w ON i.ward_id = w.id
                    JOIN departments d ON i.department_id = d.id
                    WHERE d.id = %s
                    ORDER BY i.upvote_count DESC, i.created_at DESC
                    """,
                    (current_user.department_id,)
                )
                rows = cursor.fetchall()

        items = [_serialize_issue(row) for row in rows]
        items = _assign_dynamic_priorities(items)
        return {"success": True, "count": len(items), "data": items}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch authority issues: {exc}")

@router.patch("/issues/{issue_id}/status")
async def update_issue_status(
    issue_id: str,
    req: StatusRequest,
    current_user: UserResponse = Depends(RoleChecker(["authority", "ward_member"]))
) -> dict:
    if req.status not in {"pending", "in_progress", "resolved"}:
        raise HTTPException(status_code=400, detail="Invalid status type")

    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT status FROM issues WHERE id = %s", (issue_id,))
                issue = cursor.fetchone()
                if not issue:
                    raise HTTPException(status_code=404, detail="Issue not found")
                
                old_status = issue["status"]

        # Anchor status history change to IPFS + Blockchain
        history_id = str(uuid.uuid4())
        status_payload = {
            "history_id": history_id,
            "issue_id": issue_id,
            "old_status": old_status,
            "new_status": req.status,
            "changed_by": current_user.id,
            "changed_by_name": current_user.full_name,
            "comments": req.comments or "",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        ipfs_cid = ipfs_service.store_json(status_payload, type_label="status_history")
        payload_str = json.dumps(status_payload, sort_keys=True)
        blockchain_hash = hashlib.sha256(payload_str.encode()).hexdigest()

        # Write to blockchain under history_id key
        onchain_tx_hash = blockchain_service.store_issue_hash(history_id, blockchain_hash)

        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE issues SET status = %s WHERE id = %s",
                    (req.status, issue_id)
                )

                cursor.execute(
                    """
                    INSERT INTO issue_status_history (id, issue_id, old_status, new_status, changed_by, comments, ipfs_cid, blockchain_hash)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (history_id, issue_id, old_status, req.status, current_user.id, req.comments, ipfs_cid, blockchain_hash)
                )
            conn.commit()

        return {
            "success": True,
            "message": f"Status updated to {req.status} and anchored to blockchain.",
            "tx_hash": onchain_tx_hash,
            "ipfs_cid": ipfs_cid,
            "blockchain_hash": blockchain_hash
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to update status: {exc}")

@router.post("/issues/{issue_id}/resolve")
async def resolve_issue(
    issue_id: str,
    comments: str = Form(...),
    proof_file: UploadFile = File(...),
    current_user: UserResponse = Depends(RoleChecker(["authority"]))
) -> dict:
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT status, department_id FROM issues WHERE id = %s", (issue_id,))
                issue = cursor.fetchone()
                if not issue:
                    raise HTTPException(status_code=404, detail="Issue not found")
                
                if current_user.department_id != issue["department_id"]:
                    raise HTTPException(status_code=403, detail="This issue is assigned to a different department")
                
                old_status = issue["status"]

        proof_info = await _save_media_file(proof_file, expected_type="proof")
        if not proof_info:
            raise HTTPException(status_code=400, detail="Failed to save resolution proof file")
            
        proof_cid = proof_info["cid"]
        proof_url = proof_info["url"]

        completion_data = {
            "issue_id": issue_id,
            "resolved_by": current_user.id,
            "resolved_by_name": current_user.full_name,
            "comments": comments,
            "proof_file": proof_info,
            "resolved_at": datetime.now(timezone.utc).isoformat()
        }
        completion_proof_ipfs_cid = ipfs_service.store_json(completion_data, type_label="completion_proof")

        completion_hash = hashlib.sha256(
            json.dumps(completion_data, sort_keys=True).encode()
        ).hexdigest()

        onchain_tx_hash = blockchain_service.store_completion_hash(issue_id, completion_hash)

        # Anchor status history change to IPFS + Blockchain
        history_id = str(uuid.uuid4())
        status_payload = {
            "history_id": history_id,
            "issue_id": issue_id,
            "old_status": old_status,
            "new_status": "resolved",
            "changed_by": current_user.id,
            "changed_by_name": current_user.full_name,
            "comments": comments,
            "proof_url": proof_url,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        status_ipfs_cid = ipfs_service.store_json(status_payload, type_label="status_history")
        status_payload_str = json.dumps(status_payload, sort_keys=True)
        status_blockchain_hash = hashlib.sha256(status_payload_str.encode()).hexdigest()

        # Write status history hash to blockchain under history_id key
        status_tx_hash = blockchain_service.store_issue_hash(history_id, status_blockchain_hash)

        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE issues
                    SET status = 'resolved',
                        completion_proof_ipfs_cid = %s,
                        completion_hash = %s
                    WHERE id = %s
                    """,
                    (completion_proof_ipfs_cid, completion_hash, issue_id)
                )

                cursor.execute(
                    """
                    INSERT INTO issue_status_history (id, issue_id, old_status, new_status, changed_by, comments, proof_url, ipfs_cid, blockchain_hash)
                    VALUES (%s, %s, %s, 'resolved', %s, %s, %s, %s, %s)
                    """,
                    (history_id, issue_id, old_status, current_user.id, comments, proof_url, status_ipfs_cid, status_blockchain_hash)
                )
            conn.commit()

        return {
            "success": True, 
            "message": "Issue marked as resolved on blockchain & database.",
            "tx_hash": onchain_tx_hash,
            "completion_hash": completion_hash,
            "status_tx_hash": status_tx_hash,
            "status_ipfs_cid": status_ipfs_cid,
            "status_blockchain_hash": status_blockchain_hash
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to resolve issue: {exc}")
