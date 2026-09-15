from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AuditLog, User


def request_ip(request: Request | None) -> str:
    if request is None:
        return ""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()[:80]
    return (request.client.host if request.client else "")[:80]


def audit(
    db: Session,
    request: Request | None,
    user: User | None,
    action: str,
    *,
    entity_type: str = "",
    entity_id: object = "",
    result: str = "allowed",
    details: str = "",
    commit: bool = True,
) -> AuditLog:
    row = AuditLog(
        user_id=user.id if user else None,
        action=action[:100],
        entity_type=(entity_type or "")[:60],
        entity_id=str(entity_id or "")[:80],
        result=(result or "allowed")[:20],
        details=(details or "")[:4000],
        ip_address=request_ip(request),
    )
    db.add(row)
    if commit:
        db.commit()
    return row
