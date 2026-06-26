import hashlib
import json
import os
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, List
import shutil
import uuid
import mimetypes

# Fix Windows registry MIME type corruption for JS and CSS files
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel

from backend.app.database import get_connection, init_db, warmup as db_warmup
from backend.app.auth import (
    get_password_hash,
    verify_password,
    create_access_token,
    get_current_user,
    get_optional_current_user,
    RoleChecker,
    UserResponse
)
import backend.app.ipfs_service as ipfs_service
import backend.app.routing as routing_service
import backend.app.blockchain_service as blockchain_service

import time

PROJECT_NAME = "Decentralized Tamper-Resistant Civic Issue Reporting System"
ROOT_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = ROOT_DIR / "frontend" / "src"
UPLOADS_DIR = ROOT_DIR / "uploads"

# DB-backed rate limiting settings
SUBMISSION_COOLDOWN = 30  # seconds between complaint submissions
VOTE_COOLDOWN = 5          # seconds between votes

UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app_instance):
    # ── Startup: warm up the DB connection pool so the first request is fast ──
    import asyncio
    try:
        await asyncio.get_event_loop().run_in_executor(None, db_warmup)
    except Exception as exc:
        logging.warning("DB warmup on startup failed (non-fatal): %s", exc)
    yield
    # ── Shutdown: nothing extra needed, pool auto-closes ──

app = FastAPI(title=PROJECT_NAME, version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    return response

app.mount("/assets", StaticFiles(directory=FRONTEND_DIR), name="assets")
app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")

class VoteRequest(BaseModel):
    vote_type: str

class RegisterRequest(BaseModel):
    username: str
    password: str
    role: str  # citizen, ward_member, authority
    full_name: str
    contact: Optional[str] = None
    department_id: Optional[int] = None
    ward_id: Optional[int] = None

class LoginRequest(BaseModel):
    username: str
    password: str

class PriorityRequest(BaseModel):
    priority: str

class RedirectRequest(BaseModel):
    department_id: int

class StatusRequest(BaseModel):
    status: str
    comments: Optional[str] = None

class ProfileUpdateRequest(BaseModel):
    full_name: str
    contact: Optional[str] = None
    designation: Optional[str] = None

@app.on_event("startup")
def startup_event() -> None:
    init_db()
    # blockchain_service initializes automatically on import, but run verify check here
    blockchain_service.init_blockchain()

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

# --- HTML Page Routes ---
@app.get("/")
@app.get("/index.html")
async def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")

@app.get("/report")
@app.get("/report.html")
async def report_page() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "report.html")

@app.get("/citizen")
@app.get("/citizen.html")
async def citizen_page() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "citizen.html")

@app.get("/ward")
@app.get("/ward.html")
async def ward_page() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "ward.html")

@app.get("/authority")
@app.get("/authority.html")
async def authority_page() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "authority.html")

@app.get("/admin")
@app.get("/admin.html")
async def admin_page() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "admin.html")


@app.get("/api/health")
async def health() -> dict:
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        return {
            "success": True,
            "project": PROJECT_NAME,
            "database": "connected",
            "blockchain": "active" if blockchain_service.is_blockchain_active() else "mock_mode"
        }
    except Exception as exc:
        return {
            "success": False,
            "project": PROJECT_NAME,
            "database": "disconnected",
            "error": str(exc),
        }

async def anchor_ward_profile(user_id: str, username: str, full_name: str, contact: str, ward_id: int):
    profile_payload = {
        "user_id": user_id,
        "username": username,
        "role": "ward_member",
        "full_name": full_name,
        "contact": contact,
        "ward_id": ward_id
    }
    # Store JSON to IPFS
    ipfs_cid = ipfs_service.store_json(profile_payload)
    
    # Compute SHA256 of JSON payload
    payload_str = json.dumps(profile_payload, sort_keys=True)
    profile_hash = hashlib.sha256(payload_str.encode()).hexdigest()
    
    # Anchor to blockchain
    blockchain_service.store_personnel_hash(user_id, profile_hash)
    
    # Update DB
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
    # Store JSON to IPFS
    ipfs_cid = ipfs_service.store_json(profile_payload)
    
    # Compute SHA256 of JSON payload
    payload_str = json.dumps(profile_payload, sort_keys=True)
    profile_hash = hashlib.sha256(payload_str.encode()).hexdigest()
    
    # Anchor to blockchain
    blockchain_service.store_personnel_hash(user_id, profile_hash)
    
    # Update DB
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE government_personnel SET ipfs_cid = %s, blockchain_hash = %s WHERE user_id = %s",
                (ipfs_cid, profile_hash, user_id)
            )
        conn.commit()

# --- AUTH API ---
@app.post("/api/auth/register")
async def register(req: RegisterRequest) -> dict:
    if len(req.username) < 3:
        raise HTTPException(status_code=400, detail="Username must be at least 3 characters")
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    if req.role not in {"citizen", "ward_member", "authority"}:
        raise HTTPException(status_code=400, detail="Invalid role specified")

    user_id = str(uuid.uuid4())
    pw_hash = get_password_hash(req.password)

    # By default, citizens and admin are approved. Wards and authorities require approval.
    is_approved = True
    if req.role in {"ward_member", "authority"}:
        is_approved = False

    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                # Check uniqueness
                cursor.execute("SELECT id FROM users WHERE username = %s", (req.username,))
                if cursor.fetchone():
                    raise HTTPException(status_code=400, detail="Username is already taken")

                # Insert user
                cursor.execute(
                    """
                    INSERT INTO users (id, username, password, role, full_name, contact, is_approved)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (user_id, req.username, pw_hash, req.role, req.full_name, req.contact, is_approved)
                )

                # Link dependencies depending on role
                if req.role == "authority":
                    if not req.department_id:
                        raise HTTPException(status_code=400, detail="Department ID is required for government authorities")
                    cursor.execute(
                        """
                        INSERT INTO government_personnel (user_id, department_id, designation)
                        VALUES (%s, %s, %s)
                        """,
                        (user_id, req.department_id, "Department Official")
                    )
                elif req.role == "ward_member":
                    if not req.ward_id:
                        raise HTTPException(status_code=400, detail="Ward ID is required for Ward Members")
                    cursor.execute(
                        """
                        UPDATE wards SET ward_member_id = %s WHERE id = %s
                        """,
                        (user_id, req.ward_id)
                    )
            conn.commit()

        if req.role == "ward_member":
            await anchor_ward_profile(user_id, req.username, req.full_name, req.contact or "", req.ward_id)
        elif req.role == "authority":
            await anchor_authority_profile(user_id, req.username, req.full_name, req.contact or "", req.department_id, "Department Official")
            
        return {"success": True, "message": "User registered successfully", "user_id": user_id}
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("Registration failed")
        raise HTTPException(status_code=500, detail="Registration failed due to a system error.")

@app.post("/api/auth/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends()) -> dict:
    # Handles both OAuth2 standard form and can be adjusted if JSON is sent (we also support JSON login via separate login endpoint or this form)
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, password, role FROM users WHERE username = %s", (form_data.username,))
            user = cursor.fetchone()

    if not user or not verify_password(form_data.password, user["password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(data={"sub": str(user["id"]), "role": user["role"]})
    return {"access_token": token, "token_type": "bearer", "role": user["role"]}

@app.post("/api/auth/json-login")
async def json_login(req: LoginRequest) -> dict:
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, password, role FROM users WHERE username = %s", (req.username,))
            user = cursor.fetchone()

    if not user or not verify_password(req.password, user["password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )

    token = create_access_token(data={"sub": str(user["id"]), "role": user["role"]})
    return {"access_token": token, "token_type": "bearer", "role": user["role"]}

@app.get("/api/auth/me")
async def get_me(current_user: UserResponse = Depends(get_current_user)) -> UserResponse:
    return current_user

# --- ISSUES API ---
@app.get("/api/issues")
async def get_issues(
    voter_id: Optional[str] = None,
    current_user: Optional[UserResponse] = Depends(get_optional_current_user)
) -> dict:
    if current_user:
        voter_id = str(current_user.id)
    try:
        # Filter issues depending on role:
        # Citizens see all issues.
        # Ward members see all issues or their ward's issues.
        # Authorities see all issues or their department's issues.
        # Let's return all issues, but include the voter check
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

@app.post("/api/issues")
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
    # Validate fields
    title = title.strip()
    description = description.strip()
    category = category.strip()
    area = area.strip()
    address = address.strip()
    reporter_name = reporter_name.strip()
    contact = contact.strip()

    # DB-backed rate limiting (cooldown: 30 seconds)
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

    # Save files to locally AND simulated IPFS
    media_list = []
    
    # Handle main image
    primary_image_url = None
    if image:
        img_info = await _save_media_file(image, expected_type="image")
        if img_info:
            media_list.append(img_info)
            primary_image_url = img_info["url"]
            
    # Handle audio
    if audio:
        aud_info = await _save_media_file(audio, expected_type="audio")
        if aud_info:
            media_list.append(aud_info)
            
    # Handle video
    if video:
        vid_info = await _save_media_file(video, expected_type="video")
        if vid_info:
            media_list.append(vid_info)

    issue_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc)

    # Auto routing and classification
    ward_id = routing_service.find_nearest_ward(latitude, longitude)
    dept_id = routing_service.classify_issue(category)

    # Store full issue info in simulated IPFS
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

    # Generate standard cryptographic verification hash
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
        # Push hash to blockchain
        blockchain_tx_hash = blockchain_service.store_issue_hash(issue_id, issue_hash)

        # Write to local PostgreSQL DB
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

        # Fetch finalized record with joined info
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

# --- WARD MEMBER API ---
@app.get("/api/ward/profile")
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

@app.post("/api/ward/profile")
async def update_ward_profile(
    req: ProfileUpdateRequest,
    current_user: UserResponse = Depends(RoleChecker(["ward_member"]))
) -> dict:
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                # Update user table
                cursor.execute(
                    "UPDATE users SET full_name = %s, contact = %s WHERE id = %s",
                    (req.full_name, req.contact, current_user.id)
                )
                # Fetch ward_id
                cursor.execute("SELECT id FROM wards WHERE ward_member_id = %s", (current_user.id,))
                ward_row = cursor.fetchone()
                if not ward_row:
                    raise HTTPException(status_code=404, detail="Ward not found for this user")
                ward_id = ward_row["id"]
            conn.commit()

        # Re-anchor profile
        await anchor_ward_profile(current_user.id, current_user.username, req.full_name, req.contact or "", ward_id)
        return {"success": True, "message": "Profile updated and anchored to blockchain successfully"}
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("Failed to update ward profile")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/ward/stats")
async def get_ward_stats(
    current_user: UserResponse = Depends(RoleChecker(["ward_member"]))
) -> dict:
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                # Get ward_id for the current user
                cursor.execute("SELECT id FROM wards WHERE ward_member_id = %s", (current_user.id,))
                ward_row = cursor.fetchone()
                if not ward_row:
                    raise HTTPException(status_code=404, detail="Ward not found for this member")
                ward_id = ward_row["id"]

                # Total issues
                cursor.execute("SELECT COUNT(*) as count FROM issues WHERE ward_id = %s", (ward_id,))
                total_issues = cursor.fetchone()["count"]

                # Status breakdown
                cursor.execute(
                    "SELECT status, COUNT(*) as count FROM issues WHERE ward_id = %s GROUP BY status",
                    (ward_id,)
                )
                status_rows = cursor.fetchall()
                status_breakdown = {r["status"]: r["count"] for r in status_rows}

                # Priority breakdown
                cursor.execute(
                    "SELECT priority, COUNT(*) as count FROM issues WHERE ward_id = %s GROUP BY priority",
                    (ward_id,)
                )
                priority_rows = cursor.fetchall()
                priority_breakdown = {r["priority"]: r["count"] for r in priority_rows}

                # Average resolution time (hours)
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

                # Top categories
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

@app.get("/api/ward/issues")
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

@app.patch("/api/ward/issues/{issue_id}/priority")
async def update_issue_priority(
    issue_id: str,
    req: PriorityRequest,
    current_user: UserResponse = Depends(RoleChecker(["ward_member"]))
) -> dict:
    raise HTTPException(status_code=403, detail="Priority updates are handled automatically by user votes.")

@app.post("/api/ward/issues/{issue_id}/redirect")
async def redirect_issue(
    issue_id: str,
    req: RedirectRequest,
    current_user: UserResponse = Depends(RoleChecker(["ward_member"]))
) -> dict:
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                # Verify ownership
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

                # Verify department exists
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

# --- GOVERNMENT AUTHORITY API ---
@app.get("/api/authority/profile")
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

@app.post("/api/authority/profile")
async def update_authority_profile(
    req: ProfileUpdateRequest,
    current_user: UserResponse = Depends(RoleChecker(["authority"]))
) -> dict:
    try:
        designation = req.designation or "Department Official"
        with get_connection() as conn:
            with conn.cursor() as cursor:
                # Update user table
                cursor.execute(
                    "UPDATE users SET full_name = %s, contact = %s WHERE id = %s",
                    (req.full_name, req.contact, current_user.id)
                )
                # Update government_personnel table
                cursor.execute(
                    "UPDATE government_personnel SET designation = %s WHERE user_id = %s",
                    (designation, current_user.id)
                )
                # Fetch department_id
                cursor.execute("SELECT department_id FROM government_personnel WHERE user_id = %s", (current_user.id,))
                dept_row = cursor.fetchone()
                if not dept_row:
                    raise HTTPException(status_code=404, detail="Department not found for this official")
                department_id = dept_row["department_id"]
            conn.commit()

        # Re-anchor profile
        await anchor_authority_profile(current_user.id, current_user.username, req.full_name, req.contact or "", department_id, designation)
        return {"success": True, "message": "Profile updated and anchored to blockchain successfully"}
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("Failed to update authority profile")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/authority/stats")
async def get_authority_stats(
    current_user: UserResponse = Depends(RoleChecker(["authority"]))
) -> dict:
    try:
        dept_id = current_user.department_id
        if dept_id is None:
            raise HTTPException(status_code=400, detail="User has no department linked")

        with get_connection() as conn:
            with conn.cursor() as cursor:
                # Total issues
                cursor.execute("SELECT COUNT(*) as count FROM issues WHERE department_id = %s", (dept_id,))
                total_issues = cursor.fetchone()["count"]

                # Status breakdown
                cursor.execute(
                    "SELECT status, COUNT(*) as count FROM issues WHERE department_id = %s GROUP BY status",
                    (dept_id,)
                )
                status_rows = cursor.fetchall()
                status_breakdown = {r["status"]: r["count"] for r in status_rows}

                # Resolution rate
                resolved_count = status_breakdown.get("resolved", 0)
                resolution_rate = round((resolved_count / total_issues * 100), 1) if total_issues > 0 else 0.0

                # Average resolution time (hours)
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

                # Comparative: issues per ward forwarded to this department
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

@app.get("/api/authority/issues")
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

@app.patch("/api/authority/issues/{issue_id}/status")
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
                
                # Update status
                cursor.execute(
                    "UPDATE issues SET status = %s WHERE id = %s",
                    (req.status, issue_id)
                )

                # Log to status history
                history_id = str(uuid.uuid4())
                cursor.execute(
                    """
                    INSERT INTO issue_status_history (id, issue_id, old_status, new_status, changed_by, comments)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (history_id, issue_id, old_status, req.status, current_user.id, req.comments)
                )
            conn.commit()
        return {"success": True, "message": f"Status updated to {req.status}"}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to update status: {exc}")

@app.post("/api/authority/issues/{issue_id}/resolve")
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

        # Store proof file locally and simulated IPFS
        proof_info = await _save_media_file(proof_file, expected_type="proof")
        if not proof_info:
            raise HTTPException(status_code=400, detail="Failed to save resolution proof file")
            
        proof_cid = proof_info["cid"]
        proof_url = proof_info["url"]

        # Store resolution metadata in IPFS
        completion_data = {
            "issue_id": issue_id,
            "resolved_by": current_user.id,
            "resolved_by_name": current_user.full_name,
            "comments": comments,
            "proof_file": proof_info,
            "resolved_at": datetime.now(timezone.utc).isoformat()
        }
        completion_proof_ipfs_cid = ipfs_service.store_json(completion_data, type_label="completion_proof")

        # Compute completion hash
        completion_hash = hashlib.sha256(
            json.dumps(completion_data, sort_keys=True).encode()
        ).hexdigest()

        # Post hash on-chain
        onchain_tx_hash = blockchain_service.store_completion_hash(issue_id, completion_hash)

        # Update SQL Database
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

                # Log status history
                history_id = str(uuid.uuid4())
                cursor.execute(
                    """
                    INSERT INTO issue_status_history (id, issue_id, old_status, new_status, changed_by, comments, proof_url)
                    VALUES (%s, %s, %s, 'resolved', %s, %s, %s)
                    """,
                    (history_id, issue_id, old_status, current_user.id, comments, proof_url)
                )
            conn.commit()

        return {
            "success": True, 
            "message": "Issue marked as resolved on blockchain & database.",
            "tx_hash": onchain_tx_hash,
            "completion_hash": completion_hash
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to resolve issue: {exc}")

# --- LOOKUP AND META API ---
@app.get("/api/departments")
async def get_departments() -> dict:
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, name, description FROM departments ORDER BY name")
            depts = cursor.fetchall()
    return {"success": True, "data": depts}

@app.get("/api/wards")
async def get_wards() -> dict:
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, name, center_latitude, center_longitude, radius_meters FROM wards ORDER BY name")
            wards = cursor.fetchall()
    return {"success": True, "data": wards}

@app.get("/api/verify/{issue_id}")
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

        # Check resolution/completion status verification
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

@app.get("/api/verify-all")
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

            # Check completion hash
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

@app.post("/api/issues/{issue_id}/vote")
async def vote_issue(
    issue_id: str,
    vote: VoteRequest,
    current_user: UserResponse = Depends(get_current_user)
) -> dict:
    voter_id = str(current_user.id)
    vote_type = vote.vote_type.strip().lower()

    if vote_type not in {"up", "down"}:
        raise HTTPException(status_code=400, detail="vote_type must be 'up' or 'down'")

    # DB-backed rate limiting (cooldown: 5 seconds)
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

@app.get("/api/admin/pending-users")
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
        # Serialize UUID/datetime for JSON
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

@app.post("/api/admin/approve-user/{user_id}")
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

@app.post("/api/admin/reject-user/{user_id}")
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

@app.get("/api/admin/failed-transactions")
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

@app.post("/api/admin/retry-blockchain")
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

@app.get("/api/admin/stats")
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



# ---- Pydantic models for admin management ----
class CreateWardRequest(BaseModel):
    name: str
    center_latitude: float
    center_longitude: float
    radius_meters: float = 5000

class CreateDepartmentRequest(BaseModel):
    name: str
    description: Optional[str] = None

class AssignWardMemberRequest(BaseModel):
    user_id: str   # UUID of the ward_member user

class AssignAuthorityRequest(BaseModel):
    user_id: str       # UUID of the authority user
    designation: Optional[str] = "Department Official"

# ---- GET all users (admin only) ----
@app.get("/api/admin/users")
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

# ---- CREATE ward (admin only) ----
@app.post("/api/admin/wards")
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

# ---- DELETE ward (admin only) ----
@app.delete("/api/admin/wards/{ward_id}")
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

# ---- GET wards with member info (admin only) ----
@app.get("/api/admin/wards")
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

# ---- ASSIGN ward member to ward (admin only) ----
@app.post("/api/admin/wards/{ward_id}/assign-member")
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

# ---- UNASSIGN ward member from ward (admin only) ----
@app.post("/api/admin/wards/{ward_id}/unassign-member")
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

# ---- CREATE department (admin only) ----
@app.post("/api/admin/departments")
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

# ---- DELETE department (admin only) ----
@app.delete("/api/admin/departments/{dept_id}")
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

# ---- GET departments with personnel info (admin only) ----
@app.get("/api/admin/departments")
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
        from collections import defaultdict
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

# ---- ASSIGN authority user to department (admin only) ----
@app.post("/api/admin/departments/{dept_id}/assign-authority")
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

# ---- REMOVE authority from department (admin only) ----
@app.delete("/api/admin/departments/{dept_id}/remove-authority/{user_id}")
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app.main:app", host="127.0.0.1", port=8000, reload=True)
