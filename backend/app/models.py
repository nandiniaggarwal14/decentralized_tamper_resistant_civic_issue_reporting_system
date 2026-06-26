from pydantic import BaseModel
from typing import Optional

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

# Admin management models
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
