import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Site, Ticket, TicketWorkSession, User
from app.services.time_tracking import format_duration, start_work, stop_work, ticket_time_summary


def make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    return Session()


def test_timer_start_and_stop_records_actual_time():
    db = make_db()
    tech = User(username="tech", full_name="Мастер", password_hash="x", role="technician", active=True)
    site = Site(name="Магазин", address="Петропавловск")
    db.add_all([tech, site]); db.flush()
    ticket = Ticket(number="T-1", title="Ремонт", site_id=site.id, assignee_id=tech.id, status="assigned")
    db.add(ticket); db.commit()

    entry = start_work(db, ticket, tech, "Диагностика")
    assert ticket.status == "in_progress"
    assert entry.ended_at is None

    entry.started_at = datetime.utcnow() - timedelta(minutes=42)
    db.commit()
    stopped = stop_work(db, ticket, tech)
    assert stopped is not None
    assert stopped.duration_seconds >= 41 * 60

    summary = ticket_time_summary(db, ticket.id)
    assert summary["total_seconds"] >= 41 * 60
    assert summary["active"] == []


def test_starting_new_ticket_closes_previous_timer():
    db = make_db()
    tech = User(username="tech", full_name="Мастер", password_hash="x", role="technician", active=True)
    site = Site(name="Магазин", address="Петропавловск")
    db.add_all([tech, site]); db.flush()
    t1 = Ticket(number="T-1", title="Работа 1", site_id=site.id, assignee_id=tech.id, status="assigned")
    t2 = Ticket(number="T-2", title="Работа 2", site_id=site.id, assignee_id=tech.id, status="assigned")
    db.add_all([t1, t2]); db.commit()

    first = start_work(db, t1, tech)
    start_work(db, t2, tech)
    db.refresh(first)
    assert first.ended_at is not None
    active = db.query(TicketWorkSession).filter(TicketWorkSession.user_id == tech.id, TicketWorkSession.ended_at.is_(None)).all()
    assert len(active) == 1
    assert active[0].ticket_id == t2.id


def test_duration_formatting():
    assert format_duration(0) == "0 сек"
    assert format_duration(65) == "1 мин 05 сек"
    assert format_duration(3660) == "1 ч 01 мин"
