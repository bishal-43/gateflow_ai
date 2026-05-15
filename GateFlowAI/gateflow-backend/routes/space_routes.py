"""routes/space_routes.py — Space endpoints only"""
from uuid import UUID
from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
import controllers.space_controller as ctrl
from database import get_db
from dependencies import require_roles
from models.user import User
from schemas.guard_space import AddGuardEmailBody, GuardInviteCreatedResponse, GuardListResponse
from schemas.space import CreateSpaceRequest, SpaceListResponse, SpaceResponse, UpdateSpaceRequest

router = APIRouter()
_OWNER_ROLES = ("ORGANIZER", "RESIDENT", "ADMIN")
_VIEW_ROLES = ("ORGANIZER", "RESIDENT", "ADMIN", "GUARD", "RESIDENTIAL_GUARD")


@router.post("", response_model=SpaceResponse, status_code=201)
async def create(data: CreateSpaceRequest, db: AsyncSession = Depends(get_db), user: User = Depends(require_roles("ORGANIZER", "RESIDENT", "ADMIN"))):
    return await ctrl.create(db, data, user)


@router.get("", response_model=SpaceListResponse)
async def list_spaces(db: AsyncSession = Depends(get_db), user: User = Depends(require_roles(*_VIEW_ROLES))):
    return await ctrl.list_spaces(db, user)


@router.get("/{space_id}", response_model=SpaceResponse)
async def get_one(space_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(require_roles(*_VIEW_ROLES))):
    return await ctrl.get_one(db, space_id, user)


@router.put("/{space_id}", response_model=SpaceResponse)
async def update(space_id: UUID, data: UpdateSpaceRequest, db: AsyncSession = Depends(get_db), user: User = Depends(require_roles(*_OWNER_ROLES))):
    return await ctrl.update(db, space_id, data, user)


@router.delete("/{space_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(space_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(require_roles(*_OWNER_ROLES))):
    await ctrl.delete(db, space_id, user)


@router.post("/{space_id}/guards/invite", response_model=GuardInviteCreatedResponse, status_code=201)
async def invite_guard(
    space_id: UUID,
    body: AddGuardEmailBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*_OWNER_ROLES)),
):
    return await ctrl.invite_guard(
        db,
        space_id,
        body.email,
        user,
        origin=request.headers.get("origin"),
        referer=request.headers.get("referer"),
    )


@router.post("/{space_id}/guards", status_code=status.HTTP_204_NO_CONTENT)
async def add_guard(
    space_id: UUID,
    body: AddGuardEmailBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*_OWNER_ROLES)),
):
    await ctrl.add_guard(db, space_id, body.email, user)


@router.get("/{space_id}/guards", response_model=GuardListResponse)
async def list_guards(
    space_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*_OWNER_ROLES)),
):
    return await ctrl.list_guards(db, space_id, user)


@router.delete("/{space_id}/guards/{guard_user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_guard(
    space_id: UUID,
    guard_user_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(*_OWNER_ROLES)),
):
    await ctrl.remove_guard(db, space_id, guard_user_id, user)
