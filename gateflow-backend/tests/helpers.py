"""
tests/helpers.py — Shared test helper functions

These avoid copy-pasting setup code across test files.
"""
from uuid import UUID

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from models.guard_space import GuardSpaceAssignment
from models.user import User, UserRole


async def assign_guard_to_space(
    db: AsyncSession,
    guard_user_id: UUID,
    space_id: str | UUID,
    assigned_by_id: UUID | None = None,
) -> None:
    """Test helper: give a guard-like user access to a space (mirrors organizer assignment)."""
    sid = UUID(space_id) if isinstance(space_id, str) else space_id
    db.add(GuardSpaceAssignment(space_id=sid, guard_user_id=guard_user_id, assigned_by_id=assigned_by_id))
    await db.commit()


async def link_guard_to_space(client: AsyncClient, db: AsyncSession, guard_headers: dict, space: dict) -> None:
    me = await client.get("/auth/me", headers=guard_headers)
    assert me.status_code == 200, me.text
    gid = UUID(me.json()["id"])
    await assign_guard_to_space(db, gid, space["id"], UUID(space["owner_id"]))


async def register_and_login(
    client: AsyncClient, db: AsyncSession, role: str = "ORGANIZER",
) -> tuple[str, dict]:
    """Register a user; patch DB role for GUARD only (public API does not create GUARD).

    RESIDENTIAL_GUARD is created via public /auth/register with role in the body.
    """
    want = UserRole(role.upper())
    if want == UserRole.GUARD:
        email = "guard@example.com"
    elif want == UserRole.RESIDENTIAL_GUARD:
        email = "resguard@example.com"
    else:
        email = f"{role.lower()}@example.com"

    body = {
        "full_name": f"Test {role.title()}",
        "email": email,
        "password": "testpassword123",
    }
    if want == UserRole.RESIDENTIAL_GUARD:
        body["role"] = "RESIDENTIAL_GUARD"

    reg = await client.post("/auth/register", json=body)
    assert reg.status_code == 201, reg.text
    data = reg.json()
    if want not in (UserRole.ORGANIZER, UserRole.RESIDENTIAL_GUARD):
        user = await db.get(User, UUID(data["user"]["id"]))
        assert user is not None
        user.role = want
        await db.commit()
    return data["access_token"], data["user"]


async def auth_headers(client: AsyncClient, db: AsyncSession, role: str = "ORGANIZER") -> dict:
    """Return Bearer authorization headers for a newly registered user."""
    token, _ = await register_and_login(client, db, role)
    return {"Authorization": f"Bearer {token}"}


async def create_space(client: AsyncClient, headers: dict) -> dict:
    """Create a test EVENT space and return the response JSON."""
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    resp = await client.post("/spaces", json={
        "name": "Test Space",
        "type": "EVENT",
        "venue": "Test Venue",
        "start_time": now.isoformat(),
        "end_time": (now + timedelta(hours=8)).isoformat(),
        "walkin_enabled": True,
    }, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def create_apartment_space(client: AsyncClient, headers: dict) -> dict:
    """Create a test APARTMENT space (for residential guard tests)."""
    resp = await client.post("/spaces", json={
        "name": "Test Apartment Block",
        "type": "APARTMENT",
        "address": "123 Test Street, Bengaluru",
        "walkin_enabled": True,
    }, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()
