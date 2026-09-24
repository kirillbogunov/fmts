from __future__ import annotations
from datetime import datetime
from sqlalchemy.orm import Session
from app.models import TicketReminder, Ticket, User
from app.services.notifications import notify_user


def process_ticket_reminders(db: Session, now: datetime | None = None) -> int:
    now = now or datetime.utcnow()
    rows = (
        db.query(TicketReminder)
        .filter(
            TicketReminder.completed_at.is_(None),
            TicketReminder.sent_at.is_(None),
            TicketReminder.remind_at <= now,
        )
        .order_by(TicketReminder.remind_at)
        .limit(100)
        .all()
    )
    sent = 0
    for row in rows:
        ticket = db.get(Ticket, row.ticket_id)
        user = db.get(User, row.user_id)
        if not ticket or not user or not user.active:
            row.completed_at = now
            continue
        notify_user(
            db, user,
            f"Напоминание по {ticket.number}",
            row.note or ticket.title,
            f"/tickets/{ticket.id}#ticket-reminders",
            level="info",
            dedup_key=f"ticket-reminder:{row.id}",
            event_type="reminder",
        )
        row.sent_at = now
        sent += 1
    db.commit()
    return sent
