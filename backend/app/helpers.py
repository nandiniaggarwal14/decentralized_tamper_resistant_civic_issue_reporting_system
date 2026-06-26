import uuid
import json
import hashlib
import shutil
from pathlib import Path
from typing import Optional, Any

from fastapi import HTTPException, UploadFile

from backend.app.config import UPLOADS_DIR
from backend.app.database import get_connection
import backend.app.ipfs_service as ipfs_service
import backend.app.blockchain_service as blockchain_service

def _uuid_to_uint256(value: str) -> int:
    return uuid.UUID(value).int

def _compute_hash(payload: dict) -> str:
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

def _validate_coordinates(latitude: float, longitude: float) -> None:
    if latitude < -90 or latitude > 90:
        raise HTTPException(status_code=400, detail="Latitude must be between -90 and 90")
    if longitude < -180 or longitude > 180:
        raise HTTPException(status_code=400, detail="Longitude must be between -180 and 180")

def _check_magic_bytes(header: bytes, expected_type: str) -> bool:
    if expected_type == "image":
        # PNG, JPEG, GIF, WEBP
        if header.startswith(b"\x89PNG\r\n\x1a\n"):
            return True
        if header.startswith(b"\xff\xd8\xff"):
            return True
        if header.startswith(b"GIF87a") or header.startswith(b"GIF89a"):
            return True
        if header.startswith(b"RIFF") and b"WEBP" in header:
            return True
        return False
    elif expected_type == "audio":
        # MP3, WAV, OGG, WebM
        if header.startswith(b"ID3") or header.startswith(b"\xff\xfb") or header.startswith(b"\xff\xf3") or header.startswith(b"\xff\xf2"):
            return True
        if header.startswith(b"RIFF") and b"WAVE" in header:
            return True
        if header.startswith(b"OggS"):
            return True
        if header.startswith(b"\x1a\x45\xdf\xa3"): # EBML / WebM
            return True
        return False
    elif expected_type == "video":
        # MP4, AVI, MKV, WebM
        if b"ftyp" in header: # MP4
            return True
        if header.startswith(b"RIFF") and b"AVI" in header:
            return True
        if header.startswith(b"\x1a\x45\xdf\xa3"): # EBML / MKV / WebM
            return True
        return False
    elif expected_type == "proof":
        # Image or PDF
        if _check_magic_bytes(header, "image"):
            return True
        if header.startswith(b"%PDF"):
            return True
        return False
    return False

def _validate_media_file(media: Optional[UploadFile], expected_type: str) -> None:
    if not media or not media.filename:
        return
        
    content_type = media.content_type or ""
    
    try:
        media.file.seek(0, 2)
        size = media.file.tell()
        media.file.seek(0)
        header = media.file.read(32)
        media.file.seek(0)
    except Exception:
        # Fallback reading bytes
        try:
            content = media.file.read()
            size = len(content)
            header = content[:32]
            media.file.seek(0)
        except Exception:
            size = 0
            header = b""

    # Validate magic bytes if we got any
    if header and not _check_magic_bytes(header, expected_type):
        raise HTTPException(
            status_code=400,
            detail=f"File content does not match the expected type '{expected_type}' (magic bytes verification failed)."
        )

    if expected_type == "image":
        if not content_type.startswith("image/"):
            ext = Path(media.filename).suffix.lower()
            if ext not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
                raise HTTPException(status_code=400, detail="Invalid image file format. Allowed formats: PNG, JPG, JPEG, WEBP, GIF.")
        if size > 5 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Image file exceeds maximum allowed size of 5MB.")
            
    elif expected_type == "audio":
        if not content_type.startswith("audio/"):
            ext = Path(media.filename).suffix.lower()
            if ext not in {".mp3", ".wav", ".ogg", ".webm", ".m4a"}:
                raise HTTPException(status_code=400, detail="Invalid audio file format. Allowed formats: MP3, WAV, OGG, WEBM, M4A.")
        if size > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Audio file exceeds maximum allowed size of 10MB.")
            
    elif expected_type == "video":
        if not content_type.startswith("video/"):
            ext = Path(media.filename).suffix.lower()
            if ext not in {".mp4", ".avi", ".mov", ".mkv", ".webm"}:
                raise HTTPException(status_code=400, detail="Invalid video file format. Allowed formats: MP4, AVI, MOV, MKV, WEBM.")
        if size > 50 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Video file exceeds maximum allowed size of 50MB.")
            
    elif expected_type == "proof":
        if not (content_type.startswith("image/") or content_type == "application/pdf"):
            ext = Path(media.filename).suffix.lower()
            if ext not in {".png", ".jpg", ".jpeg", ".webp", ".pdf"}:
                raise HTTPException(status_code=400, detail="Invalid proof file format. Allowed formats: PNG, JPG, JPEG, WEBP, PDF.")
        if size > 15 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Proof file exceeds maximum allowed size of 15MB.")

async def _save_media_file(media: Optional[UploadFile], expected_type: Optional[str] = None) -> Optional[dict]:
    if media is None or not media.filename:
        return None

    if expected_type:
        _validate_media_file(media, expected_type)

    filename = f"{uuid.uuid4()}_{Path(media.filename).name}"
    file_path = UPLOADS_DIR / filename
    
    # Save file locally
    with file_path.open("wb") as buffer:
        shutil.copyfileobj(media.file, buffer)
        
    # Read bytes for IPFS
    file_bytes = file_path.read_bytes()
    cid = ipfs_service.store_file(file_bytes, filename)
    
    media_type = "image"
    if media.content_type:
        if media.content_type.startswith("audio/"):
            media_type = "audio"
        elif media.content_type.startswith("video/"):
            media_type = "video"
            
    return {
        "type": media_type,
        "url": f"/uploads/{filename}",
        "cid": cid,
        "filename": filename
    }

def _build_issue_hash_payload(
    issue_id: str,
    title: str,
    description: str,
    category: str,
    area: str,
    address: str,
    latitude: float,
    longitude: float,
    reporter_name: str,
    contact: str,
    image_url: Optional[str],
    created_at: Any,
) -> dict:
    created_at_str = created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at)
    return {
        "id": issue_id,
        "title": title,
        "description": description,
        "category": category,
        "area": area,
        "address": address,
        "latitude": latitude,
        "longitude": longitude,
        "reporter_name": reporter_name,
        "contact": contact,
        "image_url": image_url or "",
        "created_at": created_at_str,
    }

def _serialize_issue(row: dict) -> dict:
    created_at = row.get("created_at")
    created_at_iso = created_at.isoformat() if created_at else None
    upvotes = int(row.get("upvote_count", 0) or 0)
    downvotes = int(row.get("downvote_count", 0) or 0)
    
    # Load media urls
    media_urls_raw = row.get("media_urls")
    media_urls = []
    if media_urls_raw:
        if isinstance(media_urls_raw, str):
            try:
                media_urls = json.loads(media_urls_raw)
            except Exception:
                pass
        elif isinstance(media_urls_raw, list):
            media_urls = media_urls_raw

    return {
        "id": str(row["id"]),
        "title": row["title"],
        "description": row["description"],
        "category": row["category"],
        "area": row["area"],
        "address": row["address"] or "",
        "location": {
            "latitude": row["latitude"],
            "longitude": row["longitude"],
        },
        "reporter": {
            "name": row["reporter_name"],
            "contact": row["contact"] or "",
        },
        "image_url": row["image_url"],
        "media_urls": media_urls,
        "status": row["status"],
        "created_at": created_at_iso,
        "hash": row.get("hash"),
        "priority": row.get("priority", "medium"),
        "ward_id": row.get("ward_id"),
        "ward_name": row.get("ward_name"),
        "department_id": row.get("department_id"),
        "department_name": row.get("department_name"),
        "ipfs_cid": row.get("ipfs_cid"),
        "completion_proof_ipfs_cid": row.get("completion_proof_ipfs_cid"),
        "completion_hash": row.get("completion_hash"),
        "votes": {
            "upvotes": upvotes,
            "downvotes": downvotes,
            "score": upvotes - downvotes,
            "user_vote": row.get("user_vote"),
        },
    }

def _assign_dynamic_priorities(issues: list) -> list:
    n = len(issues)
    if n == 0:
        return issues
    
    for i, issue in enumerate(issues):
        if n == 1:
            issue["priority"] = "critical"
        elif n == 2:
            issue["priority"] = "critical" if i == 0 else "low"
        elif n == 3:
            if i == 0:
                issue["priority"] = "critical"
            elif i == 1:
                issue["priority"] = "medium"
            else:
                issue["priority"] = "low"
        else:
            pct = i / n
            if pct < 0.25:
                issue["priority"] = "critical"
            elif pct < 0.50:
                issue["priority"] = "high"
            elif pct < 0.75:
                issue["priority"] = "medium"
            else:
                issue["priority"] = "low"
    return issues

async def anchor_ward_profile(user_id: str, username: str, full_name: str, contact: str, ward_id: int):
    profile_payload = {
        "user_id": user_id,
        "username": username,
        "role": "ward_member",
        "full_name": full_name,
        "contact": contact,
        "ward_id": ward_id
    }
    ipfs_cid = ipfs_service.store_json(profile_payload)
    payload_str = json.dumps(profile_payload, sort_keys=True)
    profile_hash = hashlib.sha256(payload_str.encode()).hexdigest()
    blockchain_service.store_personnel_hash(user_id, profile_hash)
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE wards SET ipfs_cid = %s, blockchain_hash = %s WHERE ward_member_id = %s",
                (ipfs_cid, profile_hash, user_id)
            )
        conn.commit()

async def anchor_authority_profile(user_id: str, username: str, full_name: str, contact: str, department_id: int, designation: str):
    profile_payload = {
        "user_id": user_id,
        "username": username,
        "role": "authority",
        "full_name": full_name,
        "contact": contact,
        "department_id": department_id,
        "designation": designation
    }
    ipfs_cid = ipfs_service.store_json(profile_payload)
    payload_str = json.dumps(profile_payload, sort_keys=True)
    profile_hash = hashlib.sha256(payload_str.encode()).hexdigest()
    blockchain_service.store_personnel_hash(user_id, profile_hash)
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE government_personnel SET ipfs_cid = %s, blockchain_hash = %s WHERE user_id = %s",
                (ipfs_cid, profile_hash, user_id)
            )
        conn.commit()
