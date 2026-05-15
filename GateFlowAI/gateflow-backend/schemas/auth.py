"""schemas/auth.py — Auth request/response schemas"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field
from schemas.common import MessageResponse  # noqa: F401 — re-exported for convenience

PublicSignUpRole = Literal["ORGANIZER", "RESIDENT", "RESIDENTIAL_GUARD"]


class RegisterRequest(BaseModel):
    """Public self-registration: ORGANIZER, RESIDENT, or RESIDENTIAL_GUARD (apartment security).

    Event guards (GUARD) must use /auth/register-guard with an organizer invite for an event space.
    """

    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    role: PublicSignUpRole = "ORGANIZER"


class RegisterGuardRequest(BaseModel):
    """Complete guard signup using an organizer-issued invite token (JWT in query string)."""

    model_config = ConfigDict(extra="forbid")

    token: str = Field(..., min_length=10, description="JWT from organizer guard-invite link")
    full_name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)


class GuardInvitePreviewResponse(BaseModel):
    """Public preview so the signup page can show which space the invite is for."""

    space_id: str
    space_name: str
    email: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    auth_provider: str
    avatar_url: str | None = None
    is_active: bool
    is_verified: bool
    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    role: str
    user: UserResponse


TokenResponse.model_rebuild()
