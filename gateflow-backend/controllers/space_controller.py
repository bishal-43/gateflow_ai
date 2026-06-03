"""controllers/space_controller.py — Space orchestration"""
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from schemas.guard_space import GuardInviteCreatedResponse, GuardListItemResponse, GuardListResponse
from schemas.space import CreateSpaceRequest, SpaceListResponse, SpaceResponse, UpdateSpaceRequest
from services.guard_space_service import (
    add_guard_by_email,
    create_guard_invite_response,
    list_guards_for_space,
    remove_guard_assignment,
)
from services.space_service import create_space, delete_space, get_space_by_id, get_spaces, update_space


async def create(db: AsyncSession, data: CreateSpaceRequest, user: User) -> SpaceResponse:
    return await create_space(db, data, user)


async def list_spaces(db: AsyncSession, user: User) -> SpaceListResponse:
    total, spaces = await get_spaces(db, user)
    return SpaceListResponse(total=total, spaces=spaces)


async def get_one(db: AsyncSession, space_id: UUID, user: User) -> SpaceResponse:
    return await get_space_by_id(db, space_id, user)


async def update(db: AsyncSession, space_id: UUID, data: UpdateSpaceRequest, user: User) -> SpaceResponse:
    return await update_space(db, space_id, data, user)


async def delete(db: AsyncSession, space_id: UUID, user: User) -> None:
    await delete_space(db, space_id, user)


async def invite_guard(
    db: AsyncSession,
    space_id: UUID,
    email: str,
    user: User,
    *,
    origin: str | None = None,
    referer: str | None = None,
) -> GuardInviteCreatedResponse:
    return await create_guard_invite_response(db, space_id, email, user, origin=origin, referer=referer)


async def add_guard(db: AsyncSession, space_id: UUID, email: str, user: User) -> None:
    await add_guard_by_email(db, space_id, email, user)


async def list_guards(db: AsyncSession, space_id: UUID, user: User) -> GuardListResponse:
    rows = await list_guards_for_space(db, space_id, user)
    return GuardListResponse(
        guards=[GuardListItemResponse(id=u.id, email=u.email, full_name=u.full_name) for u in rows],
    )


async def remove_guard(db: AsyncSession, space_id: UUID, guard_user_id: UUID, user: User) -> None:
    await remove_guard_assignment(db, space_id, guard_user_id, user)
