"""services/guard_space_service.py — Minimal guard ↔ space authorization"""
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.guard_space import GuardSpaceAssignment
from models.space import Space, SpaceType
from models.user import User, UserRole
from utils.logger import logger
from utils.public_app_url import resolve_public_app_base_url

GUARD_LIKE_ROLES = frozenset({UserRole.GUARD, UserRole.RESIDENTIAL_GUARD})


def is_guard_like(role: UserRole) -> bool:
    """True for roles that may scan entry/exit when assigned to a space."""
    return role in GUARD_LIKE_ROLES


async def is_guard_assigned(db: AsyncSession, guard_user_id: UUID, space_id: UUID) -> bool:
    r = await db.execute(
        select(GuardSpaceAssignment.id).where(
            GuardSpaceAssignment.guard_user_id == guard_user_id,
            GuardSpaceAssignment.space_id == space_id,
        ).limit(1)
    )
    return r.scalar_one_or_none() is not None


async def ensure_guard_assigned_to_space(db: AsyncSession, guard: User, space_id: UUID) -> None:
    """403 unless user is ADMIN or a guard-like role assigned to this space."""
    if guard.role == UserRole.ADMIN:
        return
    if not is_guard_like(guard.role):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only guards or admins can perform this action")
    if not await is_guard_assigned(db, guard.id, space_id):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "You are not assigned to this space — ask the organizer to add you as a guard",
        )


def create_guard_invite_token(space_id: UUID, email: str, invited_by: UUID) -> str:
    """Short-lived signed token for /auth/register-guard (organizer shares link with invitee)."""
    now = datetime.now(timezone.utc)
    exp = now + timedelta(days=14)
    payload: dict[str, Any] = {
        "typ": "guard_invite",
        "space_id": str(space_id),
        "email": email.lower().strip(),
        "inv": str(invited_by),
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_guard_invite_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(
            token.strip(),
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={"verify_exp": True},
        )
    except JWTError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired guard invite link") from e


async def add_guard_by_email(
    db: AsyncSession,
    space_id: UUID,
    email: str,
    actor: User,
) -> GuardSpaceAssignment:
    """Link an existing GUARD or RESIDENTIAL_GUARD user to a space (owner or ADMIN).

    Event spaces accept only GUARD accounts; apartment spaces accept only RESIDENTIAL_GUARD.
    """
    email_norm = email.lower().strip()
    r = await db.execute(select(User).where(User.email == email_norm))
    guard_user = r.scalar_one_or_none()
    if guard_user is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "No account with this email — for events send a guard invite link; for apartments they register first then you add them here",
        )
    if not is_guard_like(guard_user.role):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This user is not a guard account")
    space = await db.get(Space, space_id)
    if space is None or not space.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Space not found")
    if actor.role != UserRole.ADMIN and space.owner_id != actor.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not own this space")
    if space.type == SpaceType.EVENT and guard_user.role != UserRole.GUARD:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Event spaces only accept event guard accounts (created via invite link), not apartment security accounts",
        )
    if space.type == SpaceType.APARTMENT and guard_user.role != UserRole.RESIDENTIAL_GUARD:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Residential spaces only accept apartment security accounts — they self-register, then you add their email here",
        )
    existing = await db.execute(
        select(GuardSpaceAssignment).where(
            GuardSpaceAssignment.space_id == space_id,
            GuardSpaceAssignment.guard_user_id == guard_user.id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "This guard is already assigned to this space")
    row = GuardSpaceAssignment(space_id=space_id, guard_user_id=guard_user.id, assigned_by_id=actor.id)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    logger.info(f"[GUARD] Assigned {email_norm!r} to space {space_id} by {actor.email}")
    return row


async def remove_guard_assignment(db: AsyncSession, space_id: UUID, guard_user_id: UUID, actor: User) -> None:
    space = await db.get(Space, space_id)
    if space is None or not space.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Space not found")
    if actor.role != UserRole.ADMIN and space.owner_id != actor.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not own this space")
    r = await db.execute(
        select(GuardSpaceAssignment).where(
            GuardSpaceAssignment.space_id == space_id,
            GuardSpaceAssignment.guard_user_id == guard_user_id,
        )
    )
    row = r.scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")
    await db.delete(row)
    await db.commit()
    logger.info(f"[GUARD] Removed guard {guard_user_id} from space {space_id}")


async def list_guards_for_space(db: AsyncSession, space_id: UUID, actor: User) -> list[User]:
    space = await db.get(Space, space_id)
    if space is None or not space.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Space not found")
    if actor.role != UserRole.ADMIN and space.owner_id != actor.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not own this space")
    rows = (
        await db.execute(
            select(User)
            .join(GuardSpaceAssignment, GuardSpaceAssignment.guard_user_id == User.id)
            .where(GuardSpaceAssignment.space_id == space_id)
            .order_by(User.email)
        )
    ).scalars().all()
    return list(rows)


async def list_assigned_space_ids(db: AsyncSession, guard_user_id: UUID) -> list[UUID]:
    r = await db.execute(
        select(GuardSpaceAssignment.space_id).where(GuardSpaceAssignment.guard_user_id == guard_user_id)
    )
    return list(r.scalars().all())


async def create_guard_invite_response(
    db: AsyncSession,
    space_id: UUID,
    email: str,
    actor: User,
    *,
    origin: str | None = None,
    referer: str | None = None,
):
    """Return a shareable link for a new **event** guard to register and join this space."""
    from urllib.parse import quote

    from schemas.guard_space import GuardInviteCreatedResponse

    space = await db.get(Space, space_id)
    if space is None or not space.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Space not found")
    if space.type != SpaceType.EVENT:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Guard invite links are only for events. For apartments, security staff register in the app; add them with “Add existing account”.",
        )
    if actor.role != UserRole.ADMIN and space.owner_id != actor.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not own this space")
    token = create_guard_invite_token(space_id, email, actor.id)
    base = resolve_public_app_base_url(origin, referer)
    link = f"{base}/register-guard?token={quote(token, safe='')}"
    return GuardInviteCreatedResponse(invite_link=link, email=email.lower().strip(), space_id=space_id)
