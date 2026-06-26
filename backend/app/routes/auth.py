import logging
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from backend.app.database import get_connection
from backend.app.auth import (
    get_password_hash,
    verify_password,
    create_access_token,
    get_current_user,
    UserResponse
)
from backend.app.models import RegisterRequest, LoginRequest
from backend.app.helpers import anchor_ward_profile, anchor_authority_profile

router = APIRouter(prefix="/api/auth", tags=["auth"])

@router.post("/register")
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

@router.post("/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends()) -> dict:
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

@router.post("/json-login")
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

@router.get("/me")
async def get_me(current_user: UserResponse = Depends(get_current_user)) -> UserResponse:
    return current_user
