from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from app.models import Ticket, TicketStatusHistory, SlaEvent

PAUSED_SLA_STATUSES = {"waiting"}


def ensure_initial_history(db: Session, ticket: Ticket, *, user_id: int | None = None, source: str = "create") -> TicketStatusHistory | None:
    """Create the first lifecycle row once the ticket has an id."""
    if not ticket.id:
        db.flush()
    existing = db.query(TicketStatusHistory.id).filter(TicketStatusHistory.ticket_id == ticket.id).first()
    if existing:
        return None
    row = TicketStatusHistory(
        ticket_id=ticket.id,
        from_status="",
        to_status=ticket.status or "new",
        changed_by_id=user_id,
        changed_at=ticket.created_at or datetime.utcnow(),
        previous_duration_seconds=0,
        source=source,
    )
    db.add(row)
    return row


def _last_changed_at(db: Session, ticket: Ticket) -> datetime:
    row = (
        db.query(TicketStatusHistory)
        .filter(TicketStatusHistory.ticket_id == ticket.id)
        .order_by(TicketStatusHistory.changed_at.desc(), TicketStatusHistory.id.desc())
        .first()
    )
    return row.changed_at if row else (ticket.created_at or datetime.utcnow())


def transition_ticket(
    db: Session,
    ticket: Ticket,
    new_status: str,
    *,
    user_id: int | None = None,
    source: str = "web",
    changed_at: datetime | None = None,
    bump_version: bool = True,
) -> bool:
    """Move a ticket between statuses and keep history + SLA pause state consistent."""
    now = changed_at or datetime.utcnow()
    old_status = ticket.status or "new"
    if new_status == old_status:
        return False

    ensure_initial_history(db, ticket, user_id=user_id, source="backfill")
    started = _last_changed_at(db, ticket)
    previous_seconds = max(0, int((now - started).total_seconds()))

    # Leaving an SLA-paused state extends the deadline by exactly the paused time.
    if old_status in PAUSED_SLA_STATUSES and ticket.sla_paused_at:
        paused_seconds = max(0, int((now - ticket.sla_paused_at).total_seconds()))
        ticket.sla_paused_seconds = int(ticket.sla_paused_seconds or 0) + paused_seconds
        if ticket.sla_due_at:
            ticket.sla_due_at = ticket.sla_due_at + timedelta(seconds=paused_seconds)
        ticket.sla_paused_at = None
        # The effective deadline changed, so old warning/overdue dedup markers
        # must not suppress a fresh notification after work resumes.
        db.query(SlaEvent).filter(SlaEvent.ticket_id == ticket.id).delete(synchronize_session=False)

    # Entering waiting freezes SLA from this moment until the ticket leaves waiting.
    if new_status in PAUSED_SLA_STATUSES and old_status not in PAUSED_SLA_STATUSES and ticket.sla_due_at:
        ticket.sla_paused_at = now

    ticket.status = new_status
    ticket.updated_at = now
    if bump_version:
        ticket.edit_version = int(ticket.edit_version or 1) + 1

    db.add(TicketStatusHistory(
        ticket_id=ticket.id,
        from_status=old_status,
        to_status=new_status,
        changed_by_id=user_id,
        changed_at=now,
        previous_duration_seconds=previous_seconds,
        source=source,
    ))
    return True


def effective_sla_due(ticket: Ticket, now: datetime | None = None) -> datetime | None:
    """Deadline shown while SLA is paused; it moves forward with the pause so remaining time stays frozen."""
    if not ticket.sla_due_at:
        return None
    now = now or datetime.utcnow()
    if ticket.sla_paused_at:
        return ticket.sla_due_at + (now - ticket.sla_paused_at)
    return ticket.sla_due_at


def status_timeline(db: Session, ticket: Ticket, now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
    rows = (
        db.query(TicketStatusHistory)
        .filter(TicketStatusHistory.ticket_id == ticket.id)
        .order_by(TicketStatusHistory.changed_at.asc(), TicketStatusHistory.id.asc())
        .all()
    )
    totals: dict[str, int] = defaultdict(int)
    for row in rows:
        if row.from_status:
            totals[row.from_status] += int(row.previous_duration_seconds or 0)

    current_started = rows[-1].changed_at if rows else (ticket.created_at or now)
    current_seconds = max(0, int((now - current_started).total_seconds()))
    totals[ticket.status] += current_seconds
    return {
        "rows": rows,
        "totals": [{"status": status, "seconds": seconds} for status, seconds in totals.items()],
        "current_started": current_started,
        "current_seconds": current_seconds,
        "has_backfill": any(r.source == "backfill" for r in rows),
    }
