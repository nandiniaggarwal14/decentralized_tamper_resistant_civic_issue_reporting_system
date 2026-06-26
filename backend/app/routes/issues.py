import logging
import json
import uuid
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Form, UploadFile, File

from backend.app.database import get_connection
from backend.app.auth import get_current_user, get_optional_current_user, UserResponse
from backend.app.models import VoteRequest
from backend.app.config import SUBMISSION_COOLDOWN, VOTE_COOLDOWN
from backend.app.helpers import (
    _validate_coordinates,
    _save_media_file,
    _build_issue_hash_payload,
    _compute_hash,
    _serialize_issue,
    _assign_dynamic_priorities
)
import backend.app.ipfs_service as ipfs_service
import backend.app.routing as routing_service
import backend.app.blockchain_service as blockchain_service

router = APIRouter(prefix="/api", tags=["issues"])

@router.get("/issues")
async def get_issues(
    voter_id: Optional[str] = None,
    current_user: Optional[UserResponse] = Depends(get_optional_current_user)
) -> dict:
    if current_user:
        voter_id = str(current_user.id)
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
                           i.upvote_count, i.downvote_count,
                           uv.vote_type AS user_vote
                     FROM issues i
                     LEFT JOIN wards w ON i.ward_id = w.id
                     LEFT JOIN departments d ON i.department_id = d.id
                     LEFT JOIN issue_votes uv
                         ON uv.issue_id = i.id AND uv.voter_id = %s
                     ORDER BY i.upvote_count DESC, i.created_at DESC
                     """,
                     (voter_id or "",),
                )
                rows = cursor.fetchall()

        items = [_serialize_issue(row) for row in rows]
        items = _assign_dynamic_priorities(items)
        return {"success": True, "count": len(items), "data": items}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch issues: {exc}") from exc

@router.post("/issues")
async def create_issue(
    title: str = Form(...),
    description: str = Form(...),
    latitude: float = Form(...),
    longitude: float = Form(...),
    category: str = Form(...),
    area: str = Form(...),
    address: str = Form(""),
    reporter_name: str = Form(...),
    contact: str = Form(""),
    image: Optional[UploadFile] = File(default=None),
    audio: Optional[UploadFile] = File(default=None),
    video: Optional[UploadFile] = File(default=None),
    current_user: UserResponse = Depends(get_current_user)
) -> dict:
    title = title.strip()
    description = description.strip()
    category = category.strip()
    area = area.strip()
    address = address.strip()
    reporter_name = reporter_name.strip()
    contact = contact.strip()

    user_id_str = str(current_user.id)
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT created_at 
                FROM issues 
                WHERE user_id = %s 
                ORDER BY created_at DESC 
                LIMIT 1
                """,
                (user_id_str,)
            )
            row = cursor.fetchone()
            if row:
                last_time = row["created_at"]
                elapsed = (datetime.now(timezone.utc) - last_time).total_seconds()
                if elapsed < SUBMISSION_COOLDOWN:
                    remaining = int(SUBMISSION_COOLDOWN - elapsed)
                    raise HTTPException(
                        status_code=429,
                        detail=f"Too many requests. Please wait {remaining} seconds before submitting another complaint."
                    )

    if len(title) < 5:
        raise HTTPException(status_code=400, detail="Title must be at least 5 characters")
    if len(description) < 10:
        raise HTTPException(status_code=400, detail="Description must be at least 10 characters")
    if not category:
        raise HTTPException(status_code=400, detail="Category is required")
    if not area:
        raise HTTPException(status_code=400, detail="Area is required")

    _validate_coordinates(latitude, longitude)

    media_list = []
    primary_image_url = None
    if image:
        img_info = await _save_media_file(image, expected_type="image")
        if img_info:
            media_list.append(img_info)
            primary_image_url = img_info["url"]
            
    if audio:
        aud_info = await _save_media_file(audio, expected_type="audio")
        if aud_info:
            media_list.append(aud_info)
            
    if video:
        vid_info = await _save_media_file(video, expected_type="video")
        if vid_info:
            media_list.append(vid_info)

    issue_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc)

    ward_id = routing_service.find_nearest_ward(latitude, longitude)
    dept_id = routing_service.classify_issue(category)

    ipfs_payload = {
        "id": issue_id,
        "title": title,
        "description": description,
        "category": category,
        "area": area,
        "address": address,
        "location": {"latitude": latitude, "longitude": longitude},
        "reporter": {"name": reporter_name, "contact": contact},
        "media": media_list,
        "created_at": created_at.isoformat()
    }
    ipfs_cid = ipfs_service.store_json(ipfs_payload, type_label="issue_report")

    hash_payload = _build_issue_hash_payload(
        issue_id=issue_id,
        title=title,
        description=description,
        category=category,
        area=area,
        address=address,
        latitude=latitude,
        longitude=longitude,
        reporter_name=reporter_name,
        contact=contact,
        image_url=primary_image_url,
        created_at=created_at,
    )
    issue_hash = _compute_hash(hash_payload)

    try:
        blockchain_tx_hash = blockchain_service.store_issue_hash(issue_id, issue_hash)

        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO issues (
                        id, title, description, category, area, address,
                        latitude, longitude, reporter_name, contact,
                        image_url, hash, status, created_at,
                        user_id, ward_id, department_id, priority, ipfs_cid, media_urls
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, 'pending', %s,
                        %s, %s, %s, 'low', %s, %s
                    )
                    RETURNING id
                    """,
                    (
                        issue_id,
                        title,
                        description,
                        category,
                        area,
                        address,
                        latitude,
                        longitude,
                        reporter_name,
                        contact,
                        primary_image_url,
                        issue_hash,
                        created_at,
                        current_user.id,
                        ward_id,
                        dept_id,
                        ipfs_cid,
                        json.dumps(media_list)
                    ),
                )
                cursor.fetchone()
            conn.commit()

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
                    LEFT JOIN departments d ON i.department_id = d.id
                    WHERE i.id = %s
                    """,
                    (issue_id,)
                )
                row = cursor.fetchone()

        issue = _serialize_issue(row)
        return {
            "success": True,
            "message": "Issue submitted successfully and routed.",
            "tx_hash": blockchain_tx_hash,
            "data": issue,
        }
    except Exception as exc:
        logging.exception("Failed to save issue")
        raise HTTPException(status_code=500, detail="Failed to save issue due to a database/server error.") from exc

@router.get("/departments")
async def get_departments() -> dict:
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, name, description FROM departments ORDER BY name")
            depts = cursor.fetchall()
    return {"success": True, "data": depts}

@router.get("/wards")
async def get_wards() -> dict:
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, name, center_latitude, center_longitude, radius_meters FROM wards ORDER BY name")
            wards = cursor.fetchall()
    return {"success": True, "data": wards}

@router.get("/verify/{issue_id}")
async def verify_issue(issue_id: str) -> dict:
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, title, description, category, area, address,
                           latitude, longitude, reporter_name, contact,
                           image_url, created_at, hash, completion_hash
                    FROM issues
                    WHERE id = %s
                    """,
                    (issue_id,),
                )
                row = cursor.fetchone()

        if row is None:
            raise HTTPException(status_code=404, detail="Issue not found")

        hash_payload = _build_issue_hash_payload(
            issue_id=str(row["id"]),
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
            created_at=row["created_at"],
        )
        recomputed_hash = _compute_hash(hash_payload)
        onchain_hash = blockchain_service.get_issue_hash(issue_id)
        db_hash = row.get("hash") or ""

        verified = bool(onchain_hash) and onchain_hash.lower() == recomputed_hash.lower()
        database_consistent = bool(db_hash) and db_hash.lower() == recomputed_hash.lower()

        onchain_completion_hash = blockchain_service.get_completion_hash(issue_id)
        db_completion_hash = row.get("completion_hash")
        completion_verified = False
        if db_completion_hash and onchain_completion_hash:
            completion_verified = db_completion_hash.lower() == onchain_completion_hash.lower()

        return {
            "success": True,
            "issue_id": issue_id,
            "verified": verified,
            "database_consistent": database_consistent,
            "recomputed_hash": recomputed_hash,
            "database_hash": db_hash,
            "onchain_hash": onchain_hash,
            "completion_verified": completion_verified,
            "onchain_completion_hash": onchain_completion_hash,
            "database_completion_hash": db_completion_hash
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to verify issue: {exc}") from exc

@router.get("/verify-all")
async def verify_all_issues() -> dict:
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, title, description, category, area, address,
                           latitude, longitude, reporter_name, contact,
                           image_url, created_at, hash, completion_hash
                    FROM issues
                    ORDER BY created_at DESC
                    """
                )
                rows = cursor.fetchall()

        results = []
        missing_rows = []
        verified_count = 0

        for row in rows:
            issue_id = str(row["id"])
            hash_payload = _build_issue_hash_payload(
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
                created_at=row["created_at"],
            )

            recomputed_hash = _compute_hash(hash_payload)
            db_hash = (row.get("hash") or "").lower()
            onchain_hash = (blockchain_service.get_issue_hash(issue_id) or "").lower()

            missing = []
            if not db_hash:
                missing.append("database_hash")
            if not onchain_hash:
                missing.append("onchain_hash")

            database_consistent = bool(db_hash) and db_hash == recomputed_hash.lower()
            verified = bool(onchain_hash) and onchain_hash == recomputed_hash.lower()

            if verified:
                verified_count += 1
            if missing:
                missing_rows.append({"issue_id": issue_id, "missing": missing})

            onchain_completion_hash = blockchain_service.get_completion_hash(issue_id)
            db_completion_hash = row.get("completion_hash")
            completion_verified = False
            if db_completion_hash and onchain_completion_hash:
                completion_verified = db_completion_hash.lower() == onchain_completion_hash.lower()

            results.append(
                {
                    "issue_id": issue_id,
                    "verified": verified,
                    "database_consistent": database_consistent,
                    "recomputed_hash": recomputed_hash,
                    "database_hash": db_hash,
                    "onchain_hash": onchain_hash,
                    "completion_verified": completion_verified,
                    "onchain_completion_hash": onchain_completion_hash,
                    "database_completion_hash": db_completion_hash,
                    "missing": missing,
                }
            )

        total = len(results)
        return {
            "success": True,
            "total": total,
            "verified_count": verified_count,
            "tampered_or_mismatch_count": total - verified_count,
            "missing_rows_count": len(missing_rows),
            "missing_rows": missing_rows,
            "data": results,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to verify all issues: {exc}") from exc

@router.post("/issues/{issue_id}/vote")
async def vote_issue(
    issue_id: str,
    vote: VoteRequest,
    current_user: UserResponse = Depends(get_current_user)
) -> dict:
    voter_id = str(current_user.id)
    vote_type = vote.vote_type.strip().lower()

    if vote_type not in {"up", "down"}:
        raise HTTPException(status_code=400, detail="vote_type must be 'up' or 'down'")

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT created_at 
                FROM issue_votes 
                WHERE voter_id = %s 
                ORDER BY created_at DESC 
                LIMIT 1
                """,
                (voter_id,)
            )
            row = cursor.fetchone()
            if row:
                last_time = row["created_at"]
                elapsed = (datetime.now(timezone.utc) - last_time).total_seconds()
                if elapsed < VOTE_COOLDOWN:
                    remaining = int(VOTE_COOLDOWN - elapsed)
                    raise HTTPException(
                        status_code=429,
                        detail=f"Voting too fast. Please wait {remaining} seconds."
                    )

    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT id FROM issues WHERE id = %s", (issue_id,))
                if cursor.fetchone() is None:
                    raise HTTPException(status_code=404, detail="Issue not found")

                cursor.execute(
                    """
                    WITH existing AS (
                        SELECT vote_type
                        FROM issue_votes
                        WHERE issue_id = %s AND voter_id = %s
                    ),
                    deleted AS (
                        DELETE FROM issue_votes
                        WHERE issue_id = %s
                          AND voter_id = %s
                          AND EXISTS (
                              SELECT 1
                              FROM existing
                              WHERE existing.vote_type = %s
                          )
                        RETURNING vote_type
                    ),
                    upserted AS (
                        INSERT INTO issue_votes (issue_id, voter_id, vote_type, created_at, updated_at)
                        SELECT %s, %s, %s, NOW(), NOW()
                        WHERE NOT EXISTS (SELECT 1 FROM deleted)
                        ON CONFLICT (issue_id, voter_id)
                        DO UPDATE SET vote_type = EXCLUDED.vote_type, updated_at = NOW()
                        RETURNING vote_type
                    )
                    SELECT (SELECT vote_type FROM upserted) AS user_vote
                    """,
                    (
                        issue_id,
                        voter_id,
                        issue_id,
                        voter_id,
                        vote_type,
                        issue_id,
                        voter_id,
                        vote_type,
                    ),
                )
                vote_result = cursor.fetchone() or {}
                current_user_vote = vote_result.get("user_vote")

                cursor.execute(
                    """
                    UPDATE issues AS i
                    SET
                        upvote_count = counts.upvotes,
                        downvote_count = counts.downvotes
                    FROM (
                        SELECT
                            COALESCE(SUM(CASE WHEN vote_type = 'up' THEN 1 ELSE 0 END), 0)::INTEGER AS upvotes,
                            COALESCE(SUM(CASE WHEN vote_type = 'down' THEN 1 ELSE 0 END), 0)::INTEGER AS downvotes
                        FROM issue_votes
                        WHERE issue_id = %s
                    ) AS counts
                    WHERE i.id = %s
                    RETURNING i.upvote_count AS upvotes, i.downvote_count AS downvotes
                    """,
                    (issue_id, issue_id),
                )
                counts = cursor.fetchone()

            conn.commit()

        upvotes = int(counts.get("upvotes", 0) or 0)
        downvotes = int(counts.get("downvotes", 0) or 0)

        return {
            "success": True,
            "message": "Vote recorded successfully",
            "data": {
                "issue_id": issue_id,
                "user_vote": current_user_vote,
                "upvotes": upvotes,
                "downvotes": downvotes,
                "score": upvotes - downvotes,
            },
        }
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("Failed to record vote")
        raise HTTPException(status_code=500, detail="Failed to record vote due to a database/server error.") from exc
