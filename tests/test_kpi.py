import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Site, Ticket, User
from app.services.kpi import calculate_monthly_kpi, parse_period


def make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    return Session()


def test_monthly_kpi_score_and_rating():
    db = make_db()
    tech = User(username="tech1", full_name="Мастер 1", password_hash="x", role="technician", active=True)
    site = Site(name="Объект 1", address="Петропавловск")
    db.add_all([tech, site]); db.flush()

    start = datetime(2026, 9, 1, 8, 0)
    t1 = Ticket(
        number="T-1", title="Работа 1", site_id=site.id, assignee_id=tech.id,
        priority="normal", status="resolved", created_at=start,
        sla_due_at=start + timedelta(hours=8), resolved_at=start + timedelta(hours=4),
        master_comment="Сделано",
    )
    t2 = Ticket(
        number="T-2", title="Работа 2", site_id=site.id, assignee_id=tech.id,
        priority="high", status="closed", created_at=start + timedelta(days=1),
        sla_due_at=start + timedelta(days=1, hours=4),
        resolved_at=start + timedelta(days=1, hours=8), master_comment="",
    )
    db.add_all([t1, t2]); db.commit()

    report = calculate_monthly_kpi(db, parse_period("2026-09"), target_points=2)
    row = report["rows"][0]
    assert row["completed"] == 2
    assert row["handled"] == 2
    assert row["sla_rate"] == 50.0
    assert row["closure_rate"] == 100.0
    assert row["productivity_rate"] == 100.0
    assert row["documentation_rate"] == 50.0
    assert row["score"] == 72.5
    assert row["rating"] == 3.6
    assert row["rank"] == 1


def test_technician_without_activity_gets_zero_kpi_and_no_rank():
    db = make_db()
    db.add(User(username="tech2", full_name="Мастер 2", password_hash="x", role="technician", active=True))
    db.commit()
    report = calculate_monthly_kpi(db, parse_period("2026-09"))
    row = report["rows"][0]
    assert row["score"] == 0.0
    assert row["rating"] == 0.0
    assert row["rank"] is None
