import logging
import mimetypes
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.app.database import get_connection, warmup as db_warmup
import backend.app.blockchain_service as blockchain_service
from backend.app.config import PROJECT_NAME, FRONTEND_DIR, UPLOADS_DIR

# Fix Windows registry MIME type corruption for JS and CSS files
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")

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

# Mount static directories
app.mount("/assets", StaticFiles(directory=FRONTEND_DIR), name="assets")
app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")

# Include Routers
from backend.app.routes.auth import router as auth_router
from backend.app.routes.issues import router as issues_router
from backend.app.routes.ward import router as ward_router
from backend.app.routes.authority import router as authority_router
from backend.app.routes.admin import router as admin_router
from backend.app.routes.pages import router as pages_router

app.include_router(auth_router)
app.include_router(issues_router)
app.include_router(ward_router)
app.include_router(authority_router)
app.include_router(admin_router)
app.include_router(pages_router)

# General /api/health endpoint
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
            "database": "failed",
            "blockchain": "mock_mode",
            "error": str(exc)
        }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app.main:app", host="127.0.0.1", port=8000, reload=True)
