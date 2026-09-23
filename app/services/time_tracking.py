from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

from sqlalchemy.orm import Session

from app.models import Ticket, TicketWorkSession, User
from app.services.ticket_lifecycle import transition_ticket

CLOSED_STATUSES = {"resolved", "closed", "cancelled"}
TIME_ROLES = {"technician"}


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
        row = by_user.setdefault(uid, {"user": entry.user, "seconds": 0, "sessions": 0, "amount": Decimal("0.00")})
        row["seconds"] += session_seconds(entry, now)
        row["sessions"] += 1
        if entry.ended_at is not None:
            row["amount"] += money(entry.labor_amount)
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


def money(value) -> Decimal:
    try:
        return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal("0.00")

def calculate_session_cost(entry: TicketWorkSession) -> Decimal:
    seconds = max(0, int(entry.duration_seconds or 0))
    rate = money(entry.hourly_rate_snapshot if entry.hourly_rate_snapshot is not None else (entry.user.hourly_rate if entry.user else 0))
    return (rate * Decimal(seconds) / Decimal(3600)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def apply_session_cost(entry: TicketWorkSession) -> None:
    if entry.hourly_rate_snapshot is None:
        entry.hourly_rate_snapshot = money(entry.user.hourly_rate if entry.user else 0)
    entry.labor_amount = calculate_session_cost(entry)

def recalculate_ticket_labor_cost(db: Session, ticket_id: int) -> Decimal:
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        return Decimal("0.00")
    entries = db.query(TicketWorkSession).filter(TicketWorkSession.ticket_id == ticket_id).all()
    automatic = sum((money(x.labor_amount) for x in entries if x.ended_at is not None), Decimal("0.00"))
    total = (money(getattr(ticket, "manual_labor_cost", 0)) + automatic).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    ticket.labor_cost = total
    return total


def _close_entry(entry: TicketWorkSession, now: datetime) -> None:
    if entry.ended_at is not None:
        return
    entry.ended_at = now
    entry.duration_seconds = max(0, int((now - entry.started_at).total_seconds()))
    apply_session_cost(entry)


def close_active_for_user(db: Session, user_id: int, now: datetime | None = None) -> list[TicketWorkSession]:
    now = now or datetime.utcnow()
    entries = (
        db.query(TicketWorkSession)
        .filter(TicketWorkSession.user_id == user_id, TicketWorkSession.ended_at.is_(None))
        .all()
    )
    ticket_ids=set()
    for entry in entries:
        _close_entry(entry, now)
        ticket_ids.add(entry.ticket_id)
    for ticket_id in ticket_ids:
        recalculate_ticket_labor_cost(db, ticket_id)
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
    recalculate_ticket_labor_cost(db, ticket_id)
    return entries


def can_track_time(user: User, ticket: Ticket) -> bool:
    # Only the technician explicitly assigned to the ticket can book repair time.
    # Dispatchers/managers can supervise the entries but must not distort technician KPI.
    if user.role not in TIME_ROLES or not user.active:
        return False
    if ticket.status in CLOSED_STATUSES:
        return False
    return ticket.assignee_id == user.id


def start_work(db: Session, ticket: Ticket, user: User, note: str = "") -> TicketWorkSession:
    if not can_track_time(user, ticket):
        raise ValueError("У пользователя нет прав на запуск таймера по этой заявке")
    now = datetime.utcnow()
    # Один человек не может одновременно учитывать время по нескольким заявкам.
    close_active_for_user(db, user.id, now)
    if ticket.status in {"new", "assigned", "waiting"}:
        transition_ticket(db, ticket, "in_progress", user_id=user.id, source="timer", changed_at=now)
    else:
        ticket.updated_at = now
    entry = TicketWorkSession(
        ticket_id=ticket.id,
        user_id=user.id,
        started_at=now,
        note=(note or "").strip(),
        source="timer",
        hourly_rate_snapshot=money(user.hourly_rate),
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
    recalculate_ticket_labor_cost(db, ticket.id)
    ticket.updated_at = now
    db.commit()
    db.refresh(entry)
    return entry
