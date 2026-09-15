from __future__ import annotations

import os
from urllib.parse import urlsplit

from fastapi import Request

from app.config import Settings


def _clean_base_url(value: str) -> str:
    """Return a normalized HTTP(S) base URL or an empty string."""
    value = (value or "").strip().rstrip("/")
    if not value:
        return ""
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"


def resolve_public_base_url(request: Request, settings: Settings) -> str:
    """Resolve the public address used in QR codes and external links.

    Priority:
    1. PUBLIC_BASE_URL - explicit production setting.
    2. RENDER_EXTERNAL_URL - automatic Render URL when available.
    3. BASE_URL - backwards-compatible legacy setting.
    4. Proxy/HTTP request host - convenient fallback for local and other hosts.
    """
    for candidate in (
        settings.public_base_url,
        os.getenv("RENDER_EXTERNAL_URL", ""),
        settings.base_url,
    ):
        cleaned = _clean_base_url(candidate)
        if cleaned:
            return cleaned

    forwarded_proto = (request.headers.get("x-forwarded-proto") or "").split(",", 1)[0].strip().lower()
    forwarded_host = (request.headers.get("x-forwarded-host") or "").split(",", 1)[0].strip()

    scheme = forwarded_proto if forwarded_proto in {"http", "https"} else request.url.scheme
    host = forwarded_host or request.headers.get("host") or request.url.netloc
    if host:
        detected = _clean_base_url(f"{scheme}://{host}")
        if detected:
            return detected

    return str(request.base_url).rstrip("/")


def public_url(request: Request, settings: Settings, path: str) -> str:
    base = resolve_public_base_url(request, settings)
    return f"{base}/{path.lstrip('/')}"
