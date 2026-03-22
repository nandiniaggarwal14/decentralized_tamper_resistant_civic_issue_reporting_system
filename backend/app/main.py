from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import shutil
import uuid

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.app.database import get_connection, init_db

PROJECT_NAME = "Decentralized Tamper-Resistant Civic Issue Reporting System"
ROOT_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = ROOT_DIR / "frontend" / "src"
UPLOADS_DIR = ROOT_DIR / "uploads"

UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title=PROJECT_NAME, version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/assets", StaticFiles(directory=FRONTEND_DIR), name="assets")
app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")


class VoteRequest(BaseModel):
    voter_id: str
    vote_type: str


@app.on_event("startup")
def startup_event() -> None:
    init_db()


def _validate_coordinates(latitude: float, longitude: float) -> None:
    if latitude < -90 or latitude > 90:
        raise HTTPException(status_code=400, detail="Latitude must be between -90 and 90")
    if longitude < -180 or longitude > 180:
        raise HTTPException(status_code=400, detail="Longitude must be between -180 and 180")


async def _save_uploaded_image(image: Optional[UploadFile]) -> Optional[str]:
    if image is None:
        return None

    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Uploaded file must be an image")

    extension = Path(image.filename or "").suffix.lower()
    allowed_extensions = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    if extension not in allowed_extensions:
        extension = ".jpg"

    saved_name = f"{uuid.uuid4()}{extension}"
    destination = UPLOADS_DIR / saved_name

    with destination.open("wb") as buffer:
        shutil.copyfileobj(image.file, buffer)

    return f"/uploads/{saved_name}"


def _serialize_issue(row: dict) -> dict:
    created_at = row.get("created_at")
    created_at_iso = created_at.isoformat() if created_at else None
    upvotes = int(row.get("upvotes", 0) or 0)
    downvotes = int(row.get("downvotes", 0) or 0)

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
        "status": row["status"],
        "created_at": created_at_iso,
        "votes": {
            "upvotes": upvotes,
            "downvotes": downvotes,
            "score": upvotes - downvotes,
            "user_vote": row.get("user_vote"),
        },
    }


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/report")
async def report_page() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "report.html")


@app.get("/api/health")
async def health() -> dict:
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        return {"success": True, "project": PROJECT_NAME, "database": "connected"}
    except Exception as exc:
        return {
            "success": False,
            "project": PROJECT_NAME,
            "database": "disconnected",
            "error": str(exc),
        }


@app.get("/api/issues")
async def get_issues(voter_id: Optional[str] = None) -> dict:
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT i.id, i.title, i.description, i.category, i.area, i.address,
                           i.latitude, i.longitude, i.reporter_name, i.contact,
                           i.image_url, i.status, i.created_at,
                           i.upvote_count AS upvotes,
                           i.downvote_count AS downvotes,
                           uv.vote_type AS user_vote
                    FROM issues i
                    LEFT JOIN issue_votes uv
                        ON uv.issue_id = i.id AND uv.voter_id = %s
                    ORDER BY i.created_at DESC
                    """,
                    (voter_id or "",),
                )
                rows = cursor.fetchall()

        items = [_serialize_issue(row) for row in rows]
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
) -> dict:
    title = title.strip()
    description = description.strip()
    category = category.strip()
    area = area.strip()
    address = address.strip()
    reporter_name = reporter_name.strip()
    contact = contact.strip()

    if len(title) < 5:
        raise HTTPException(status_code=400, detail="Title must be at least 5 characters")
    if len(description) < 10:
        raise HTTPException(status_code=400, detail="Description must be at least 10 characters")
    if not category:
        raise HTTPException(status_code=400, detail="Category is required")
    if not area:
        raise HTTPException(status_code=400, detail="Area is required")
    if not reporter_name:
        raise HTTPException(status_code=400, detail="Reporter name is required")

    _validate_coordinates(latitude, longitude)

    image_url = await _save_uploaded_image(image)

    issue_id = str(uuid.uuid4())

    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO issues (
                        id, title, description, category, area, address,
                        latitude, longitude, reporter_name, contact,
                        image_url, status, created_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, 'pending', %s
                    )
                    RETURNING id, title, description, category, area, address,
                              latitude, longitude, reporter_name, contact,
                              image_url, status, created_at
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
                        image_url,
                        datetime.now(timezone.utc),
                    ),
                )
                row = cursor.fetchone()
            conn.commit()

        issue = _serialize_issue(row)
        return {"success": True, "message": "Issue submitted successfully", "data": issue}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save issue: {exc}") from exc


@app.post("/api/issues/{issue_id}/vote")
async def vote_issue(issue_id: str, vote: VoteRequest) -> dict:
    voter_id = vote.voter_id.strip()
    vote_type = vote.vote_type.strip().lower()

    if not voter_id:
        raise HTTPException(status_code=400, detail="voter_id is required")
    if vote_type not in {"up", "down"}:
        raise HTTPException(status_code=400, detail="vote_type must be 'up' or 'down'")

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
        raise HTTPException(status_code=500, detail=f"Failed to record vote: {exc}") from exc


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.app.main:app", host="127.0.0.1", port=8000, reload=True)
