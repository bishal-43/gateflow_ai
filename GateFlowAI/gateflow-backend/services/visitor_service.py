"""services/visitor_service.py — Visitor access (no login required)"""
import base64, io
from datetime import datetime, timezone

from fastapi import HTTPException, status
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession
from security import decode_visitor_invite_token
from models.invite import Invite, InviteStatus
from models.space import Space
from schemas.visitor import InviteOpenResponse, QRTokenResponse, VisitorDetailsResponse, VisitorSpaceInfo
from services.invite_service import effective_invite_status
from utils.logger import logger


def _qr_image(qr_token: str) -> str:
    """PNG bytes as raw base64 (no ``data:`` prefix) — frontend adds ``data:image/png;base64,``."""
    import qrcode

    try:
        buf = io.BytesIO()
        qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=4)
        qr.add_data(qr_token)
        qr.make(fit=True)
        # Pillow (qrcode[pil]) — avoids optional ``pypng`` / PyPNGImage issues on some installs.
        img = qr.make_image(fill_color="black", back_color="white")
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception as e:
        logger.exception(f"[VISITOR] QR image generation failed: {e}")
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Could not generate pass QR — check server logs (qrcode / Pillow).",
        ) from e


def _validate_token(token: str) -> dict:
    token = (token or "").strip()
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired invite link")
    try:
        payload = decode_visitor_invite_token(token)
    except JWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired invite link")
    if payload.get("role") != "visitor":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a visitor invite token")
    if not payload.get("invite_id"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Malformed invite token")
    return payload


def _require_invite_date_window(invite: Invite) -> None:
    """DB is source of truth for invite validity — do not rely on JWT exp alone."""
    now = datetime.now(timezone.utc)
    vf = invite.valid_from if invite.valid_from.tzinfo else invite.valid_from.replace(tzinfo=timezone.utc)
    vu = invite.valid_until if invite.valid_until.tzinfo else invite.valid_until.replace(tzinfo=timezone.utc)
    if now < vf:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"This invite is not active yet — valid from {vf.isoformat()}",
        )
    if now > vu:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"This invite has expired — valid until {vu.isoformat()}",
        )


async def _load(db: AsyncSession, invite_id: str, *, allow_used: bool = False) -> tuple[Invite, Space]:
    invite = await db.get(Invite, invite_id)
    if invite is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invite not found")
    if invite.status == InviteStatus.REVOKED:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This invite has been revoked")
    if invite.status == InviteStatus.EXPIRED:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This invite has expired")
    if invite.status == InviteStatus.USED and not allow_used:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This invite has already been used")
    space = await db.get(Space, invite.space_id)
    if space is None or not space.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Space is no longer active")
    _require_invite_date_window(invite)
    return invite, space


def _space_info(space: Space) -> VisitorSpaceInfo:
    return VisitorSpaceInfo(id=space.id, type=space.type, name=space.name,
                            venue=space.venue, address=space.address,
                            start_time=space.start_time, end_time=space.end_time)


async def get_invite_details(db: AsyncSession, token: str) -> InviteOpenResponse:
    payload = _validate_token(token)
    # After a successful entry scan the invite is USED; still allow opening the pass / QR for display.
    invite, space = await _load(db, payload["invite_id"], allow_used=True)
    logger.info(f"[VISITOR] Opened: {invite.visitor_name!r} space={space.name!r}")
    return InviteOpenResponse(invite_id=invite.id, visitor_name=invite.visitor_name,
                              invite_type=invite.invite_type, status=effective_invite_status(invite),
                              valid_from=invite.valid_from, valid_until=invite.valid_until,
                              space=_space_info(space), qr_code_b64=_qr_image(invite.qr_token))


async def get_qr_data(db: AsyncSession, token: str) -> QRTokenResponse:
    payload = _validate_token(token)
    invite, _ = await _load(db, payload["invite_id"], allow_used=True)
    return QRTokenResponse(qr_token=invite.qr_token, valid_from=invite.valid_from,
                           valid_until=invite.valid_until, status=effective_invite_status(invite))


async def get_visitor_space_details(db: AsyncSession, token: str) -> VisitorDetailsResponse:
    payload = _validate_token(token)
    invite, space = await _load(db, payload["invite_id"], allow_used=True)
    return VisitorDetailsResponse(invite_id=invite.id, visitor_name=invite.visitor_name,
                                  visitor_email=invite.visitor_email, invite_type=invite.invite_type,
                                  status=effective_invite_status(invite), valid_from=invite.valid_from,
                                  valid_until=invite.valid_until, space=_space_info(space))
