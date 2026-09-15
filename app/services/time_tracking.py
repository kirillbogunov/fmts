from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Iterable

from sqlalchemy.orm import Session

from app.models import Ticket, TicketWorkSession, User

CLOSED_STATUSES = {"resolved", "closed", "cancelled"}
TIME_ROLES = {"technician", "dispatcher", "manager", "admin"}


def session_seconds(entry: TicketWorkSession, now: datetime | None = None) -> int:
    now = now or datetime.utcnow()
    if entry.ended_at is not None:
        if entry.duration_seconds and entry.duration_seconds > 0:
            return int(entry.duration_seconds)
        return max(0, int((entry.ended_at - entry.started_at).total_seconds()))
    return max(0, int((now - entry.started_at).total_seconds()))


def format_duration(total_seconds: int | float | None) -> str:
    seconds = max(0, int(total_seconds or 0))
    hours, rem = divmod(seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours} ч {minutes:02d} мин"
    if minutes:
        return f"{minutes} мин {seconds:02d} сек"
    return f"{seconds} сек"


def ticket_time_summary(db: Session, ticket_id: int, now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
    entries = (
        db.query(TicketWorkSession)
        .filter(TicketWorkSession.ticket_id == ticket_id)
        .order_by(TicketWorkSession.started_at.desc(), TicketWorkSession.id.desc())
        .all()
    )
    total_seconds = sum(session_seconds(x, now) for x in entries)
    active = [x for x in entries if x.ended_at is None]
    by_user: dict[int, dict] = {}
    for entry in entries:
        uid = entry.user_id
        row = by_user.setdefault(uid, {"user": entry.user, "seconds": 0, "sessions": 0})
        row["seconds"] += session_seconds(entry, now)
        row["sessions"] += 1
    return {
        "entries": entries,
        "active": active,
        "total_seconds": total_seconds,
        "total_label": format_duration(total_seconds),
        "by_user": list(by_user.values()),
    }


def ticket_time_totals(db: Session, ticket_ids: Iterable[int], now: datetime | None = None) -> dict[int, int]:
    ids = [int(x) for x in ticket_ids]
    if not ids:
        return {}
    now = now or datetime.utcnow()
    totals: dict[int, int] = defaultdict(int)
    entries = db.query(TicketWorkSession).filter(TicketWorkSession.ticket_id.in_(ids)).all()
    for entry in entries:
        totals[entry.ticket_id] += session_seconds(entry, now)
    return dict(totals)


def _close_entry(entry: TicketWorkSession, now: datetime) -> None:
    if entry.ended_at is not None:
        return
    entry.ended_at = now
    entry.duration_seconds = max(0, int((now - entry.started_at).total_seconds()))


def close_active_for_user(db: Session, user_id: int, now: datetime | None = None) -> list[TicketWorkSession]:
    now = now or datetime.utcnow()
    entries = (
        db.query(TicketWorkSession)
        .filter(TicketWorkSession.user_id == user_id, TicketWorkSession.ended_at.is_(None))
        .all()
    )
    for entry in entries:
        _close_entry(entry, now)
    return entries


def close_active_for_ticket(db: Session, ticket_id: int, now: datetime | None = None) -> list[TicketWorkSession]:
    now = now or datetime.utcnow()
    entries = (
        db.query(TicketWorkSession)
        .filter(TicketWorkSession.ticket_id == ticket_id, TicketWorkSession.ended_at.is_(None))
        .all()
    )
    for entry in entries:
        _close_entry(entry, now)
    return entries


def can_track_time(user: User, ticket: Ticket) -> bool:
    if user.role not in TIME_ROLES:
        return False
    if ticket.status in CLOSED_STATUSES:
        return False
    if user.role == "technician" and ticket.assignee_id not in (None, user.id):
        return False
    return True


def start_work(db: Session, ticket: Ticket, user: User, note: str = "") -> TicketWorkSession:
    if not can_track_time(user, ticket):
        raise ValueError("У пользователя нет прав на запуск таймера по этой заявке")
    now = datetime.utcnow()
    # Один человек не может одновременно учитывать время по нескольким заявкам.
    close_active_for_user(db, user.id, now)
    if user.role == "technician" and ticket.assignee_id is None:
        ticket.assignee_id = user.id
        ticket.master_name = user.full_name
    if ticket.status in {"new", "assigned", "waiting"}:
        ticket.status = "in_progress"
    ticket.updated_at = now
    entry = TicketWorkSession(
        ticket_id=ticket.id,
        user_id=user.id,
        started_at=now,
        note=(note or "").strip(),
        source="timer",
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def stop_work(db: Session, ticket: Ticket, user: User) -> TicketWorkSession | None:
    now = datetime.utcnow()
    entry = (
        db.query(TicketWorkSession)
        .filter(
            TicketWorkSession.ticket_id == ticket.id,
            TicketWorkSession.user_id == user.id,
            TicketWorkSession.ended_at.is_(None),
        )
        .order_by(TicketWorkSession.started_at.desc())
        .first()
    )
    if entry is None:
        return None
    _close_entry(entry, now)
    ticket.updated_at = now
    db.commit()
    db.refresh(entry)
    return entry
