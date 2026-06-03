"""controllers/auth_controller.py — Auth orchestration"""
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from models.space import Space
from schemas.auth import (
    GuardInvitePreviewResponse,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterGuardRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from services.auth_service import (
    build_google_auth_url,
    google_callback,
    login_user,
    logout_user,
    refresh_tokens,
    register_guard_from_invite,
    register_user,
    user_to_response,
)
from services.guard_space_service import decode_guard_invite_token


async def register(db: AsyncSession, data: RegisterRequest) -> TokenResponse:
    return await register_user(db, data.full_name, data.email, data.password, data.role)


async def login(db: AsyncSession, data: LoginRequest) -> TokenResponse:
    return await login_user(db, data.email, data.password)


async def logout(access_token: str, refresh_token: str) -> None:
    await logout_user(access_token, refresh_token)


async def refresh(db: AsyncSession, data: RefreshRequest) -> TokenResponse:
    return await refresh_tokens(db, data.refresh_token)


def get_me(user: User) -> UserResponse:
    return user_to_response(user)


async def google_url() -> str:
    return await build_google_auth_url()


async def google_login(db: AsyncSession, code: str, state: str) -> TokenResponse:
    return await google_callback(db, code, state)


async def register_guard(db: AsyncSession, data: RegisterGuardRequest) -> TokenResponse:
    return await register_guard_from_invite(db, data.token, data.full_name, data.email, data.password)


async def guard_invite_preview(db: AsyncSession, token: str) -> GuardInvitePreviewResponse:
    payload = decode_guard_invite_token(token)
    if payload.get("typ") != "guard_invite":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Not a guard invite token")
    sid = UUID(str(payload["space_id"]))
    sp = await db.get(Space, sid)
    if sp is None or not sp.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Space not found")
    return GuardInvitePreviewResponse(
        space_id=str(sid),
        space_name=sp.name,
        email=str(payload.get("email", "")),
    )
