import logging
from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException

from backend.app.database import get_connection
from backend.app.auth import RoleChecker, UserResponse
from backend.app.models import (
    CreateWardRequest,
    CreateDepartmentRequest,
    AssignWardMemberRequest,
    AssignAuthorityRequest,
)
from backend.app.helpers import anchor_ward_profile, anchor_authority_profile
import backend.app.blockchain_service as blockchain_service

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ---- Blockchain status (NEW endpoint) ----
@router.get("/blockchain/status")
async def blockchain_status(
    current_user: UserResponse = Depends(RoleChecker(["admin"]))
) -> dict:
    """Returns blockchain health info: active/mock, failed tx count, last error, wallet address."""
    try:
        is_active = blockchain_service.is_blockchain_active()

        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) as count FROM failed_blockchain_txns WHERE resolved_at IS NULL"
                )
                unresolved_count = cursor.fetchone()["count"]

                cursor.execute(
                    """
                    SELECT error_message, created_at
                    FROM failed_blockchain_txns
                    WHERE resolved_at IS NULL
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                )
                last_error_row = cursor.fetchone()

        last_error = None
        last_error_at = None
        if last_error_row:
            last_error = last_error_row["error_message"]
            last_error_at = last_error_row["created_at"].isoformat() if last_error_row["created_at"] else None

        # Get wallet address if blockchain is active
        wallet_address = None
        eth_balance = None
        if is_active:
            try:
                wallet_address = blockchain_service.get_wallet_address()
                eth_balance = blockchain_service.get_wallet_balance()
            except Exception:
                pass

        return {
            "success": True,
            "data": {
                "blockchain_active": is_active,
                "mode": "active" if is_active else "mock_mode",
                "unresolved_failed_txns": unresolved_count,
                "last_error": last_error,
                "last_error_at": last_error_at,
                "wallet_address": wallet_address,
                "eth_balance_wei": eth_balance,
            }
        }
    except Exception as exc:
        logging.exception("Failed to fetch blockchain status")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---- Dashboard stats ----
@router.get("/stats")
async def get_admin_stats(
    current_user: UserResponse = Depends(RoleChecker(["admin"]))
) -> dict:
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) as total_users FROM users")
                total_users = cursor.fetchone()["total_users"]

                cursor.execute("SELECT COUNT(*) as total_issues FROM issues")
                total_issues = cursor.fetchone()["total_issues"]

                cursor.execute("SELECT COUNT(*) as pending_approvals FROM users WHERE is_approved = FALSE")
                pending_approvals = cursor.fetchone()["pending_approvals"]

                cursor.execute("SELECT COUNT(*) as resolved_issues FROM issues WHERE status = 'resolved'")
                resolved_issues = cursor.fetchone()["resolved_issues"]

                cursor.execute("SELECT COUNT(*) as failed_txns FROM failed_blockchain_txns WHERE resolved_at IS NULL")
                failed_txns = cursor.fetchone()["failed_txns"]

        return {
            "success": True,
            "data": {
                "total_users": total_users,
                "total_issues": total_issues,
                "pending_approvals": pending_approvals,
                "resolved_issues": resolved_issues,
                "failed_txns": failed_txns
            }
        }
    except Exception as exc:
        logging.exception("Failed to fetch admin dashboard statistics")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---- Pending users ----
@router.get("/pending-users")
async def get_pending_users(
    current_user: UserResponse = Depends(RoleChecker(["admin"]))
) -> dict:
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, username, role, full_name, contact, created_at
                    FROM users
                    WHERE is_approved = FALSE
                    ORDER BY created_at DESC
                    """
                )
                rows = cursor.fetchall()
        users = []
        for r in rows:
            users.append({
                "id": str(r["id"]),
                "username": r["username"],
                "role": r["role"],
                "full_name": r["full_name"],
                "contact": r["contact"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None
            })
        return {"success": True, "count": len(users), "data": users}
    except Exception as exc:
        logging.exception("Failed to fetch pending users")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---- Approve / Reject users ----
@router.post("/approve-user/{user_id}")
async def approve_user(
    user_id: str,
    current_user: UserResponse = Depends(RoleChecker(["admin"]))
) -> dict:
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE users SET is_approved = TRUE WHERE id = %s RETURNING id",
                    (user_id,)
                )
                if not cursor.fetchone():
                    raise HTTPException(status_code=404, detail="User not found")
            conn.commit()
        return {"success": True, "message": "User approved successfully"}
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception(f"Failed to approve user {user_id}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/reject-user/{user_id}")
async def reject_user(
    user_id: str,
    current_user: UserResponse = Depends(RoleChecker(["admin"]))
) -> dict:
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                # government_personnel has user_id ON DELETE CASCADE.
                cursor.execute(
                    "DELETE FROM users WHERE id = %s AND is_approved = FALSE RETURNING id",
                    (user_id,)
                )
                if not cursor.fetchone():
                    raise HTTPException(status_code=400, detail="User not found or already approved")
            conn.commit()
        return {"success": True, "message": "User registration rejected and account deleted"}
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception(f"Failed to reject user {user_id}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---- Failed blockchain transactions ----
@router.get("/failed-transactions")
async def get_failed_transactions(
    current_user: UserResponse = Depends(RoleChecker(["admin"]))
) -> dict:
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, function_name, args_json, error_message, retry_count, created_at, resolved_at
                    FROM failed_blockchain_txns
                    ORDER BY created_at DESC
                    """
                )
                rows = cursor.fetchall()
        txns = []
        for r in rows:
            txns.append({
                "id": r["id"],
                "function_name": r["function_name"],
                "args_json": r["args_json"],
                "error_message": r["error_message"],
                "retry_count": r["retry_count"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "resolved_at": r["resolved_at"].isoformat() if r["resolved_at"] else None
            })
        return {"success": True, "count": len(txns), "data": txns}
    except Exception as exc:
        logging.exception("Failed to fetch failed transactions")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/retry-blockchain")
async def retry_blockchain(
    current_user: UserResponse = Depends(RoleChecker(["admin"]))
) -> dict:
    try:
        success_count, fail_count = blockchain_service.retry_failed_transactions()
        return {
            "success": True,
            "message": f"Retry completed. Successes: {success_count}, Failures: {fail_count}"
        }
    except Exception as exc:
        logging.exception("Failed to retry blockchain transactions")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---- List all users ----
@router.get("/users")
async def admin_list_users(
    current_user: UserResponse = Depends(RoleChecker(["admin"]))
) -> dict:
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT u.id, u.username, u.role, u.full_name, u.contact, u.is_approved, u.created_at,
                           w.id as ward_id, w.name as ward_name,
                           gp.department_id, d.name as department_name
                    FROM users u
                    LEFT JOIN wards w ON w.ward_member_id = u.id
                    LEFT JOIN government_personnel gp ON gp.user_id = u.id
                    LEFT JOIN departments d ON d.id = gp.department_id
                    ORDER BY u.created_at DESC
                    """
                )
                rows = cursor.fetchall()
        users = []
        for r in rows:
            users.append({
                "id": str(r["id"]),
                "username": r["username"],
                "role": r["role"],
                "full_name": r["full_name"],
                "contact": r["contact"],
                "is_approved": r["is_approved"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "ward_id": r["ward_id"],
                "ward_name": r["ward_name"],
                "department_id": r["department_id"],
                "department_name": r["department_name"],
            })
        return {"success": True, "count": len(users), "data": users}
    except Exception as exc:
        logging.exception("Failed to list users")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---- Ward management ----
@router.post("/wards")
async def admin_create_ward(
    req: CreateWardRequest,
    current_user: UserResponse = Depends(RoleChecker(["admin"]))
) -> dict:
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO wards (name, center_latitude, center_longitude, radius_meters)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                    """,
                    (req.name.strip(), req.center_latitude, req.center_longitude, req.radius_meters)
                )
                row = cursor.fetchone()
            conn.commit()
        return {"success": True, "message": "Ward created successfully", "ward_id": row["id"]}
    except Exception as exc:
        logging.exception("Failed to create ward")
        raise HTTPException(status_code=500, detail=f"Failed to create ward: {exc}")


@router.delete("/wards/{ward_id}")
async def admin_delete_ward(
    ward_id: int,
    current_user: UserResponse = Depends(RoleChecker(["admin"]))
) -> dict:
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM wards WHERE id = %s RETURNING id", (ward_id,))
                if not cursor.fetchone():
                    raise HTTPException(status_code=404, detail="Ward not found")
            conn.commit()
        return {"success": True, "message": "Ward deleted successfully"}
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("Failed to delete ward")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/wards")
async def admin_list_wards(
    current_user: UserResponse = Depends(RoleChecker(["admin"]))
) -> dict:
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT w.id, w.name, w.center_latitude, w.center_longitude, w.radius_meters,
                           u.id as member_id, u.username as member_username, u.full_name as member_name
                    FROM wards w
                    LEFT JOIN users u ON w.ward_member_id = u.id
                    ORDER BY w.name
                    """
                )
                rows = cursor.fetchall()
        wards = [
            {
                "id": r["id"],
                "name": r["name"],
                "center_latitude": r["center_latitude"],
                "center_longitude": r["center_longitude"],
                "radius_meters": r["radius_meters"],
                "member_id": str(r["member_id"]) if r["member_id"] else None,
                "member_username": r["member_username"],
                "member_name": r["member_name"],
            }
            for r in rows
        ]
        return {"success": True, "count": len(wards), "data": wards}
    except Exception as exc:
        logging.exception("Failed to list admin wards")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/wards/{ward_id}/assign-member")
async def admin_assign_ward_member(
    ward_id: int,
    req: AssignWardMemberRequest,
    current_user: UserResponse = Depends(RoleChecker(["admin"]))
) -> dict:
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                # Check user exists and is ward_member
                cursor.execute("SELECT id, username, full_name, contact, role FROM users WHERE id = %s", (req.user_id,))
                user_row = cursor.fetchone()
                if not user_row:
                    raise HTTPException(status_code=404, detail="User not found")
                if user_row["role"] != "ward_member":
                    raise HTTPException(status_code=400, detail="User must have the 'ward_member' role")

                # Clear any previous assignment for this user
                cursor.execute("UPDATE wards SET ward_member_id = NULL WHERE ward_member_id = %s", (req.user_id,))
                # Assign
                cursor.execute(
                    "UPDATE wards SET ward_member_id = %s WHERE id = %s RETURNING id",
                    (req.user_id, ward_id)
                )
                if not cursor.fetchone():
                    raise HTTPException(status_code=404, detail="Ward not found")
            conn.commit()

        # Anchor profile to IPFS + blockchain
        await anchor_ward_profile(
            req.user_id,
            user_row["username"],
            user_row["full_name"],
            user_row["contact"] or "",
            ward_id
        )
        return {"success": True, "message": "Ward member assigned successfully"}
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("Failed to assign ward member")
        raise HTTPException(status_code=500, detail=f"Failed to assign ward member: {exc}")


@router.post("/wards/{ward_id}/unassign-member")
async def admin_unassign_ward_member(
    ward_id: int,
    current_user: UserResponse = Depends(RoleChecker(["admin"]))
) -> dict:
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE wards SET ward_member_id = NULL WHERE id = %s RETURNING id",
                    (ward_id,)
                )
                if not cursor.fetchone():
                    raise HTTPException(status_code=404, detail="Ward not found")
            conn.commit()
        return {"success": True, "message": "Ward member unassigned"}
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("Failed to unassign ward member")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---- Department management ----
@router.post("/departments")
async def admin_create_department(
    req: CreateDepartmentRequest,
    current_user: UserResponse = Depends(RoleChecker(["admin"]))
) -> dict:
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO departments (name, description)
                    VALUES (%s, %s)
                    ON CONFLICT (name) DO NOTHING
                    RETURNING id
                    """,
                    (req.name.strip(), req.description)
                )
                row = cursor.fetchone()
                if not row:
                    raise HTTPException(status_code=400, detail="A department with this name already exists")
            conn.commit()
        return {"success": True, "message": "Department created successfully", "department_id": row["id"]}
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("Failed to create department")
        raise HTTPException(status_code=500, detail=f"Failed to create department: {exc}")


@router.delete("/departments/{dept_id}")
async def admin_delete_department(
    dept_id: int,
    current_user: UserResponse = Depends(RoleChecker(["admin"]))
) -> dict:
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM departments WHERE id = %s RETURNING id", (dept_id,))
                if not cursor.fetchone():
                    raise HTTPException(status_code=404, detail="Department not found")
            conn.commit()
        return {"success": True, "message": "Department deleted successfully"}
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("Failed to delete department")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/departments")
async def admin_list_departments(
    current_user: UserResponse = Depends(RoleChecker(["admin"]))
) -> dict:
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT d.id, d.name, d.description,
                           u.id as authority_id, u.username as authority_username,
                           u.full_name as authority_name, gp.designation
                    FROM departments d
                    LEFT JOIN government_personnel gp ON gp.department_id = d.id
                    LEFT JOIN users u ON u.id = gp.user_id
                    ORDER BY d.name, u.full_name
                    """
                )
                rows = cursor.fetchall()

        # Group authorities per department
        dept_map = {}
        for r in rows:
            did = r["id"]
            if did not in dept_map:
                dept_map[did] = {
                    "id": did,
                    "name": r["name"],
                    "description": r["description"],
                    "authorities": []
                }
            if r["authority_id"]:
                dept_map[did]["authorities"].append({
                    "user_id": str(r["authority_id"]),
                    "username": r["authority_username"],
                    "full_name": r["authority_name"],
                    "designation": r["designation"],
                })
        departments = list(dept_map.values())
        return {"success": True, "count": len(departments), "data": departments}
    except Exception as exc:
        logging.exception("Failed to list admin departments")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/departments/{dept_id}/assign-authority")
async def admin_assign_authority(
    dept_id: int,
    req: AssignAuthorityRequest,
    current_user: UserResponse = Depends(RoleChecker(["admin"]))
) -> dict:
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                # Verify user exists and has authority role
                cursor.execute("SELECT id, username, full_name, contact, role FROM users WHERE id = %s", (req.user_id,))
                user_row = cursor.fetchone()
                if not user_row:
                    raise HTTPException(status_code=404, detail="User not found")
                if user_row["role"] != "authority":
                    raise HTTPException(status_code=400, detail="User must have the 'authority' role")

                # Verify department exists
                cursor.execute("SELECT id FROM departments WHERE id = %s", (dept_id,))
                if not cursor.fetchone():
                    raise HTTPException(status_code=404, detail="Department not found")

                # Upsert personnel row
                cursor.execute(
                    """
                    INSERT INTO government_personnel (user_id, department_id, designation)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (user_id) DO UPDATE
                        SET department_id = EXCLUDED.department_id,
                            designation = EXCLUDED.designation
                    """,
                    (req.user_id, dept_id, req.designation or "Department Official")
                )
            conn.commit()

        # Anchor profile to IPFS + blockchain
        await anchor_authority_profile(
            req.user_id,
            user_row["username"],
            user_row["full_name"],
            user_row["contact"] or "",
            dept_id,
            req.designation or "Department Official"
        )
        return {"success": True, "message": "Authority assigned to department successfully"}
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("Failed to assign authority")
        raise HTTPException(status_code=500, detail=f"Failed to assign authority: {exc}")


@router.delete("/departments/{dept_id}/remove-authority/{user_id}")
async def admin_remove_authority(
    dept_id: int,
    user_id: str,
    current_user: UserResponse = Depends(RoleChecker(["admin"]))
) -> dict:
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM government_personnel WHERE user_id = %s AND department_id = %s RETURNING user_id",
                    (user_id, dept_id)
                )
                if not cursor.fetchone():
                    raise HTTPException(status_code=404, detail="Assignment not found")
            conn.commit()
        return {"success": True, "message": "Authority removed from department"}
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("Failed to remove authority from department")
        raise HTTPException(status_code=500, detail="Internal server error")
