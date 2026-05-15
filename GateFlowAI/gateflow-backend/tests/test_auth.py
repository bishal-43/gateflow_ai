"""
tests/test_auth.py — Auth flow tests

Covers:
  - register a new user
  - login with valid credentials
  - login with wrong password
  - access a protected route with a valid token
  - access a protected route without a token
"""
import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


REGISTER_PAYLOAD = {
    "full_name": "Test User",
    "email":     "test@example.com",
    "password":  "securepassword123",
}


async def test_register_success(client: AsyncClient):
    response = await client.post("/auth/register", json=REGISTER_PAYLOAD)
    assert response.status_code == 201
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["role"] == "ORGANIZER"
    assert data["user"]["email"] == "test@example.com"


async def test_register_duplicate_email(client: AsyncClient):
    """Registering the same email twice must return 409."""
    await client.post("/auth/register", json=REGISTER_PAYLOAD)
    response = await client.post("/auth/register", json=REGISTER_PAYLOAD)
    assert response.status_code == 409


async def test_login_success(client: AsyncClient):
    await client.post("/auth/register", json=REGISTER_PAYLOAD)
    response = await client.post("/auth/login", json={
        "email": "test@example.com",
        "password": "securepassword123",
    })
    assert response.status_code == 200
    assert "access_token" in response.json()


async def test_login_wrong_password(client: AsyncClient):
    await client.post("/auth/register", json=REGISTER_PAYLOAD)
    response = await client.post("/auth/login", json={
        "email": "test@example.com",
        "password": "wrongpassword",
    })
    assert response.status_code == 401


async def test_login_unknown_email(client: AsyncClient):
    response = await client.post("/auth/login", json={
        "email": "nobody@example.com",
        "password": "anypassword",
    })
    assert response.status_code == 401


async def test_me_with_valid_token(client: AsyncClient):
    reg = await client.post("/auth/register", json=REGISTER_PAYLOAD)
    token = reg.json()["access_token"]
    response = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["email"] == "test@example.com"


async def test_me_without_token(client: AsyncClient):
    """Protected route must return 401 when no token is provided."""
    response = await client.get("/auth/me")
    assert response.status_code == 401


async def test_refresh_token(client: AsyncClient):
    reg = await client.post("/auth/register", json=REGISTER_PAYLOAD)
    refresh_token = reg.json()["refresh_token"]
    response = await client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert response.status_code == 200
    assert "access_token" in response.json()


async def test_register_rejects_admin_role(client: AsyncClient):
    """Public registration cannot choose ADMIN (schema rejects unknown enum values)."""
    bad = {**REGISTER_PAYLOAD, "email": "norole@example.com", "role": "ADMIN"}
    response = await client.post("/auth/register", json=bad)
    assert response.status_code == 422


async def test_register_rejects_guard_public(client: AsyncClient):
    """GUARD accounts must use /auth/register-guard with an organizer invite, not /auth/register."""
    payload = {
        **REGISTER_PAYLOAD,
        "email": "guarduser@example.com",
        "role": "GUARD",
    }
    response = await client.post("/auth/register", json=payload)
    assert response.status_code == 422


async def test_register_residential_guard_public(client: AsyncClient):
    """Apartment security may self-register with RESIDENTIAL_GUARD."""
    payload = {
        "full_name": "Lobby Security",
        "email": "aptguard@example.com",
        "password": "securepassword123",
        "role": "RESIDENTIAL_GUARD",
    }
    response = await client.post("/auth/register", json=payload)
    assert response.status_code == 201, response.text
    assert response.json()["role"] == "RESIDENTIAL_GUARD"


async def test_guard_invite_rejected_for_apartment_space(client: AsyncClient, db):
    """Event guard invite links are not issued for apartment spaces."""
    from tests.helpers import auth_headers, create_apartment_space

    org = await auth_headers(client, db, "ORGANIZER")
    apt = await create_apartment_space(client, org)
    inv = await client.post(
        f"/spaces/{apt['id']}/guards/invite",
        json={"email": "someone@example.com"},
        headers=org,
    )
    assert inv.status_code == 400, inv.text


async def test_add_residential_guard_to_apartment(client: AsyncClient, db):
    """Owner adds self-registered apartment guard by email; wrong role on wrong space type fails."""
    from tests.helpers import auth_headers, create_apartment_space, create_space

    org = await auth_headers(client, db, "ORGANIZER")
    apt = await create_apartment_space(client, org)
    await client.post("/auth/register", json={
        "full_name": "Static Guard",
        "email": "staticg@example.com",
        "password": "securepassword123",
        "role": "RESIDENTIAL_GUARD",
    })
    add = await client.post(
        f"/spaces/{apt['id']}/guards",
        json={"email": "staticg@example.com"},
        headers=org,
    )
    assert add.status_code == 204, add.text

    event_space = await create_space(client, org)
    bad = await client.post(
        f"/spaces/{event_space['id']}/guards",
        json={"email": "staticg@example.com"},
        headers=org,
    )
    assert bad.status_code == 400, bad.text


async def test_event_guard_cannot_be_added_to_apartment(client: AsyncClient, db):
    """GUARD accounts are only assignable to event spaces."""
    from tests.helpers import auth_headers, create_apartment_space, create_space

    org = await auth_headers(client, db, "ORGANIZER")
    apt = await create_apartment_space(client, org)
    event_space = await create_space(client, org)
    inv = await client.post(
        f"/spaces/{event_space['id']}/guards/invite",
        json={"email": "eventonly@example.com"},
        headers=org,
    )
    assert inv.status_code == 201, inv.text
    from urllib.parse import parse_qs, urlparse

    token = parse_qs(urlparse(inv.json()["invite_link"]).query)["token"][0]
    reg = await client.post(
        "/auth/register-guard",
        json={
            "token": token,
            "full_name": "Event Only",
            "email": "eventonly@example.com",
            "password": "securepassword123",
        },
    )
    assert reg.status_code == 201, reg.text
    bad = await client.post(
        f"/spaces/{apt['id']}/guards",
        json={"email": "eventonly@example.com"},
        headers=org,
    )
    assert bad.status_code == 400, bad.text


async def test_register_guard_via_invite(client: AsyncClient, db):
    from tests.helpers import auth_headers, create_space

    org = await auth_headers(client, db, "ORGANIZER")
    space = await create_space(client, org)
    inv = await client.post(
        f"/spaces/{space['id']}/guards/invite",
        json={"email": "newguard@example.com"},
        headers=org,
    )
    assert inv.status_code == 201, inv.text
    from urllib.parse import parse_qs, urlparse

    token = parse_qs(urlparse(inv.json()["invite_link"]).query)["token"][0]
    pv = await client.get("/auth/guard-invite/preview", params={"token": token})
    assert pv.status_code == 200
    assert pv.json()["space_name"] == "Test Space"

    reg = await client.post(
        "/auth/register-guard",
        json={
            "token": token,
            "full_name": "Gate Guard",
            "email": "newguard@example.com",
            "password": "securepassword123",
        },
    )
    assert reg.status_code == 201, reg.text
    assert reg.json()["role"] == "GUARD"
