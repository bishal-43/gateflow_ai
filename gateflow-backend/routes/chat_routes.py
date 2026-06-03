"""routes/chat_routes.py — Secure visitor chat proxy

Security model:
  - Visitor sends their invite token (same JWT used for QR pass)
  - Backend validates token fully: exists, active, not revoked, not expired, space active
  - Backend derives space_id from the validated invite — frontend NEVER controls space_id
  - Backend proxies the question to the RAG service with the correct space_id
  - If invite is expired/revoked/invalid → 401/400 immediately, no RAG call made

This ensures: expired QR = no chat access. Cross-tenant leakage is impossible.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from services.visitor_service import _validate_token, _load
from utils.logger import logger

router = APIRouter()


class ChatRequest(BaseModel):
    token:    str = Field(..., description="Visitor invite JWT (same token from the invite link)")
    question: str = Field(..., min_length=1, max_length=1000)


class ChatResponse(BaseModel):
    answer:       str
    cache_hit:    bool = False
    space_name:   str  = ""


@router.post(
    "/ask",
    response_model=ChatResponse,
    summary="Visitor asks a question — token validated, space_id derived server-side",
    responses={
        400: {"description": "Invite expired, revoked, or not yet active"},
        401: {"description": "Invalid invite token"},
        503: {"description": "AI service unavailable"},
    },
)
async def visitor_ask(data: ChatRequest, db: AsyncSession = Depends(get_db)):
    # 1. Validate the invite token — raises 401/400/403 on any failure
    payload = _validate_token(data.token)

    # 2. Load invite + space — raises 400 if expired/revoked/used-without-allow/space-inactive
    #    allow_used=True so visitors who already entered can still chat
    invite, space = await _load(db, payload["invite_id"], allow_used=True)

    # 3. space_id is now derived server-side — frontend never controlled it
    space_id = str(invite.space_id)
    logger.info(f"[CHAT] {invite.visitor_name!r} asking in space={space.name!r} q={data.question[:60]!r}")

    # 4. Forward to RAG service
    from config import settings
    import httpx

    rag_url = settings.RAG_BASE_URL if hasattr(settings, "RAG_BASE_URL") else "http://localhost:8001"

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.get(
                f"{rag_url}/ask/{space_id}",
                params={"q": data.question},
            )
        if resp.status_code == 404:
            return ChatResponse(
                answer="No documents have been uploaded for this space yet. Please check with the organizer.",
                cache_hit=False,
                space_name=space.name,
            )
        if resp.status_code != 200:
            logger.warning(f"[CHAT] RAG returned {resp.status_code} for space={space_id}")
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AI service returned an error")

        body = resp.json()
        return ChatResponse(
            answer=body.get("answer", "No answer available."),
            cache_hit=bool(body.get("cache_hit", False)),
            space_name=space.name,
        )

    except httpx.RequestError as e:
        logger.warning(f"[CHAT] RAG unreachable: {e}")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AI service is currently unavailable")
