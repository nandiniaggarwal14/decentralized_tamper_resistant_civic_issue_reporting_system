import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

from backend.app.database import get_connection

# JWT Configuration from environment
SECRET_KEY = os.getenv("JWT_SECRET", "super-secret-key-change-in-prod-civic-reporting")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440")) # 24 hours default

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

class UserResponse(BaseModel):
    id: str
    username: str
    role: str
    full_name: str
    contact: Optional[str] = None
    department_id: Optional[int] = None
    department_name: Optional[str] = None
    is_approved: bool = True

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def get_current_user(token: Optional[str] = Depends(oauth2_scheme)) -> UserResponse:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Fetch user from database
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT u.id, u.username, u.role, u.full_name, u.contact, u.is_approved,
                       gp.department_id, d.name as department_name
                FROM users u
                LEFT JOIN government_personnel gp ON u.id = gp.user_id
                LEFT JOIN departments d ON gp.department_id = d.id
                WHERE u.id = %s
                """,
                (user_id,),
            )
            user_row = cursor.fetchone()
            if user_row is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User not found",
                    headers={"WWW-Authenticate": "Bearer"},
                )

    return UserResponse(
        id=str(user_row["id"]),
        username=user_row["username"],
        role=user_row["role"],
        full_name=user_row["full_name"],
        contact=user_row["contact"],
        department_id=user_row["department_id"],
        department_name=user_row["department_name"],
        is_approved=bool(user_row["is_approved"]),
    )

def get_optional_current_user(token: Optional[str] = Depends(oauth2_scheme)) -> Optional[UserResponse]:
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            return None
    except JWTError:
        return None

    # Fetch user from database
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT u.id, u.username, u.role, u.full_name, u.contact, u.is_approved,
                       gp.department_id, d.name as department_name
                FROM users u
                LEFT JOIN government_personnel gp ON u.id = gp.user_id
                LEFT JOIN departments d ON gp.department_id = d.id
                WHERE u.id = %s
                """,
                (user_id,),
            )
            user_row = cursor.fetchone()
            if user_row is None:
                return None

    return UserResponse(
        id=str(user_row["id"]),
        username=user_row["username"],
        role=user_row["role"],
        full_name=user_row["full_name"],
        contact=user_row["contact"],
        department_id=user_row["department_id"],
        department_name=user_row["department_name"],
        is_approved=bool(user_row["is_approved"]),
    )


class RoleChecker:
    def __init__(self, allowed_roles: list[str]):
        self.allowed_roles = allowed_roles

    def __call__(self, current_user: UserResponse = Depends(get_current_user)) -> UserResponse:
        if current_user.role not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Operation not permitted for this role",
            )
        if not current_user.is_approved:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account pending administrator approval",
            )
        return current_user
