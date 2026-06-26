from fastapi import APIRouter
from fastapi.responses import FileResponse
from backend.app.config import FRONTEND_DIR

router = APIRouter()

@router.get("/")
@router.get("/index.html")
async def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")

@router.get("/report")
@router.get("/report.html")
async def report_page() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "report.html")

@router.get("/citizen")
@router.get("/citizen.html")
async def citizen_page() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "citizen.html")

@router.get("/ward")
@router.get("/ward.html")
async def ward_page() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "ward.html")

@router.get("/authority")
@router.get("/authority.html")
async def authority_page() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "authority.html")

@router.get("/admin")
@router.get("/admin.html")
async def admin_page() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "admin.html")
