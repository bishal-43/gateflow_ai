"""Resolve the public SPA base URL for invite and guard-signup links."""
from urllib.parse import urlparse

from config import settings


def _norm(s: str) -> str:
    return s.strip().rstrip("/")


def resolve_public_app_base_url(origin: str | None = None, referer: str | None = None) -> str:
    """
    Prefer ``Origin`` or ``Referer`` when they match ``ALLOWED_ORIGINS``; otherwise ``PUBLIC_APP_URL``.

    When the dashboard runs on e.g. ``http://localhost:5173`` but ``PUBLIC_APP_URL`` still points
    at ``http://localhost:5174``, generated links open a different origin and the browser can block
    or show ``chrome-error://chromewebdata`` when embedded or redirected from an error context.
    """
    whitelist = {_norm(o) for o in settings.allowed_origins_list if o and o.strip()}

    if origin and origin.strip():
        cand = _norm(origin)
        if cand in whitelist:
            return cand

    if referer and referer.strip():
        try:
            p = urlparse(referer.strip())
            if p.scheme and p.netloc:
                cand = _norm(f"{p.scheme}://{p.netloc}")
                if cand in whitelist:
                    return cand
        except Exception:
            pass

    return _norm(settings.PUBLIC_APP_URL)
