"""schemas/guard_space.py — Guard assignment API shapes"""
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class AddGuardEmailBody(BaseModel):
    email: EmailStr


class GuardInviteCreatedResponse(BaseModel):
    invite_link: str
    email: str
    space_id: UUID


class GuardListItemResponse(BaseModel):
    id: UUID
    email: str
    full_name: str


class GuardListResponse(BaseModel):
    guards: list[GuardListItemResponse]
