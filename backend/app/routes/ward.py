import logging
from fastapi import APIRouter, Depends, HTTPException

from backend.app.database import get_connection
from backend.app.auth import RoleChecker, UserResponse
from backend.app.models import ProfileUpdateRequest, PriorityRequest, RedirectRequest
from backend.app.helpers import anchor_ward_profile, _serialize_issue, _assign_dynamic_priorities
import backend.app.blockchain_service as blockchain_service

router = APIRouter(prefix="/api/ward", tags=["ward"])

@router.get("/profile")
async def get_ward_profile(
    current_user: UserResponse = Depends(RoleChecker(["ward_member"]))
) -> dict:
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT w.name as ward_name, w.ipfs_cid, w.blockchain_hash, w.id as ward_id,
                           u.full_name, u.contact, u.username
                    FROM users u
                    JOIN wards w ON u.id = w.ward_member_id
                    WHERE u.id = %s
                    """,
                    (current_user.id,)
                )
                row = cursor.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Ward profile not found")
        
        onchain_hash = blockchain_service.get_personnel_hash(current_user.id)
        db_hash = row["blockchain_hash"]
        is_verified = bool(db_hash and onchain_hash and db_hash.lower() == onchain_hash.lower())

        return {
            "success": True,
            "data": {
                "username": row["username"],
                "full_name": row["full_name"],
                "contact": row["contact"],
                "ward_id": row["ward_id"],
                "ward_name": row["ward_name"],
                "ipfs_cid": row["ipfs_cid"],
                "blockchain_hash": row["blockchain_hash"],
                "onchain_hash": onchain_hash,
                "is_verified": is_verified
            }
        }
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("Failed to fetch ward profile")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/profile")
async def update_ward_profile(
    req: ProfileUpdateRequest,
    current_user: UserResponse = Depends(RoleChecker(["ward_member"]))
) -> dict:
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE users SET full_name = %s, contact = %s WHERE id = %s",
                    (req.full_name, req.contact, current_user.id)
                )
                cursor.execute("SELECT id FROM wards WHERE ward_member_id = %s", (current_user.id,))
                ward_row = cursor.fetchone()
                if not ward_row:
                    raise HTTPException(status_code=404, detail="Ward not found for this user")
                ward_id = ward_row["id"]
            conn.commit()

        await anchor_ward_profile(current_user.id, current_user.username, req.full_name, req.contact or "", ward_id)
        return {"success": True, "message": "Profile updated and anchored to blockchain successfully"}
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("Failed to update ward profile")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/stats")
async def get_ward_stats(
    current_user: UserResponse = Depends(RoleChecker(["ward_member"]))
) -> dict:
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT id FROM wards WHERE ward_member_id = %s", (current_user.id,))
                ward_row = cursor.fetchone()
                if not ward_row:
                    raise HTTPException(status_code=404, detail="Ward not found for this member")
                ward_id = ward_row["id"]

                cursor.execute("SELECT COUNT(*) as count FROM issues WHERE ward_id = %s", (ward_id,))
                total_issues = cursor.fetchone()["count"]

                cursor.execute(
                    "SELECT status, COUNT(*) as count FROM issues WHERE ward_id = %s GROUP BY status",
                    (ward_id,)
                )
                status_rows = cursor.fetchall()
                status_breakdown = {r["status"]: r["count"] for r in status_rows}

                cursor.execute(
                    "SELECT priority, COUNT(*) as count FROM issues WHERE ward_id = %s GROUP BY priority",
                    (ward_id,)
                )
                priority_rows = cursor.fetchall()
                priority_breakdown = {r["priority"]: r["count"] for r in priority_rows}

                cursor.execute(
                    """
                    SELECT AVG(EXTRACT(EPOCH FROM (h.created_at - i.created_at))) / 3600.0 as avg_time
                    FROM issues i
                    JOIN issue_status_history h ON i.id = h.issue_id
                    WHERE i.ward_id = %s AND h.new_status = 'resolved'
                    """,
                    (ward_id,)
                )
                avg_time_row = cursor.fetchone()
                avg_res_time = round(avg_time_row["avg_time"], 1) if avg_time_row and avg_time_row["avg_time"] is not None else 0.0

                cursor.execute(
                    """
                    SELECT category, COUNT(*) as count 
                    FROM issues 
                    WHERE ward_id = %s 
                    GROUP BY category 
                    ORDER BY count DESC 
                    LIMIT 5
                    """,
                    (ward_id,)
                )
                cat_rows = cursor.fetchall()
                top_categories = {r["category"]: r["count"] for r in cat_rows}

        return {
            "success": True,
            "data": {
                "total_issues": total_issues,
                "status_breakdown": status_breakdown,
                "priority_breakdown": priority_breakdown,
                "avg_res_time_hours": avg_res_time,
                "top_categories": top_categories
            }
        }
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("Failed to fetch ward statistics")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/issues")
async def get_ward_issues(current_user: UserResponse = Depends(RoleChecker(["ward_member"]))) -> dict:
    try:
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
                    JOIN wards w ON i.ward_id = w.id
                    LEFT JOIN departments d ON i.department_id = d.id
                    WHERE w.ward_member_id = %s
                    ORDER BY i.upvote_count DESC, i.created_at DESC
                    """,
                    (current_user.id,)
                )
                rows = cursor.fetchall()

        items = [_serialize_issue(row) for row in rows]
        items = _assign_dynamic_priorities(items)
        return {"success": True, "count": len(items), "data": items}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch ward issues: {exc}")

@router.patch("/issues/{issue_id}/priority")
async def update_issue_priority(
    issue_id: str,
    req: PriorityRequest,
    current_user: UserResponse = Depends(RoleChecker(["ward_member"]))
) -> dict:
    raise HTTPException(status_code=403, detail="Priority updates are handled automatically by user votes.")

@router.post("/issues/{issue_id}/redirect")
async def redirect_issue(
    issue_id: str,
    req: RedirectRequest,
    current_user: UserResponse = Depends(RoleChecker(["ward_member"]))
) -> dict:
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT i.id FROM issues i
                    JOIN wards w ON i.ward_id = w.id
                    WHERE i.id = %s AND w.ward_member_id = %s
                    """,
                    (issue_id, current_user.id)
                )
                if not cursor.fetchone():
                    raise HTTPException(status_code=403, detail="Not authorized to route issues in another ward")

                cursor.execute("SELECT id FROM departments WHERE id = %s", (req.department_id,))
                if not cursor.fetchone():
                    raise HTTPException(status_code=404, detail="Department not found")

                cursor.execute(
                    "UPDATE issues SET department_id = %s WHERE id = %s",
                    (req.department_id, issue_id)
                )
            conn.commit()
        return {"success": True, "message": "Issue redirected to new department"}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to redirect issue: {exc}")
