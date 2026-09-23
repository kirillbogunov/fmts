import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import User, Site, Ticket, TicketStatusHistory, TicketReminder, Notification
from app.services.ticket_lifecycle import ensure_initial_history, transition_ticket, status_timeline, effective_sla_due
from app.services.reminders import process_ticket_reminders


def make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def seed(db):
    user = User(username="tech", full_name="Техник", password_hash="x", role="technician", active=True)
    site = Site(name="Объект")
    db.add_all([user, site]); db.flush()
    return user, site


def test_status_history_and_sla_pause_resume():
    db = make_db(); user, site = seed(db)
    base = datetime(2026, 9, 23, 10, 0, 0)
    ticket = Ticket(number="SR-1", title="Работа", site_id=site.id, status="assigned", assignee_id=user.id,
                    created_at=base, updated_at=base, sla_due_at=base + timedelta(hours=4), edit_version=1)
    db.add(ticket); db.flush(); ensure_initial_history(db, ticket, user_id=user.id, source="test")

    transition_ticket(db, ticket, "waiting", user_id=user.id, source="test", changed_at=base + timedelta(hours=1))
    assert ticket.sla_paused_at == base + timedelta(hours=1)
    frozen_due = effective_sla_due(ticket, base + timedelta(hours=2))
    assert frozen_due == base + timedelta(hours=5)

    transition_ticket(db, ticket, "in_progress", user_id=user.id, source="test", changed_at=base + timedelta(hours=3))
    db.flush()
    assert ticket.sla_paused_at is None
    assert ticket.sla_paused_seconds == 7200
    assert ticket.sla_due_at == base + timedelta(hours=6)
    assert ticket.edit_version == 3
    rows = db.query(TicketStatusHistory).filter_by(ticket_id=ticket.id).order_by(TicketStatusHistory.id).all()
    assert [(r.from_status, r.to_status) for r in rows] == [("", "assigned"), ("assigned", "waiting"), ("waiting", "in_progress")]
    assert rows[1].previous_duration_seconds == 3600
    assert rows[2].previous_duration_seconds == 7200


def test_status_timeline_aggregates_time_by_status():
    db = make_db(); user, site = seed(db)
    base = datetime(2026, 9, 23, 10, 0, 0)
    ticket = Ticket(number="SR-2", title="Работа", site_id=site.id, status="assigned", created_at=base, updated_at=base)
    db.add(ticket); db.flush(); ensure_initial_history(db, ticket, source="test")
    transition_ticket(db, ticket, "in_progress", source="test", changed_at=base + timedelta(minutes=30))
    timeline = status_timeline(db, ticket, now=base + timedelta(hours=2))
    totals = {x["status"]: x["seconds"] for x in timeline["totals"]}
    assert totals["assigned"] == 1800
    assert totals["in_progress"] == 5400


def test_due_reminder_creates_notification_once():
    db = make_db(); user, site = seed(db)
    ticket = Ticket(number="SR-3", title="Проверить витрину", site_id=site.id, requester_id=user.id)
    db.add(ticket); db.flush()
    reminder = TicketReminder(ticket_id=ticket.id, user_id=user.id, remind_at=datetime.utcnow() - timedelta(minutes=1), note="Позвонить поставщику")
    db.add(reminder); db.commit()

    assert process_ticket_reminders(db) == 1
    db.refresh(reminder)
    assert reminder.sent_at is not None
    row = db.query(Notification).filter(Notification.user_id == user.id).one()
    assert ticket.number in row.title
    assert "Позвонить" in row.body
    assert process_ticket_reminders(db) == 0
