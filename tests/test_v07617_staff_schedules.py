from datetime import datetime, date
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import User, TechnicianAvailability, TechnicianAvailabilityException
from app.services.automation import technician_available

ROOT = Path(__file__).resolve().parents[1]


def make_db():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_default_schedule_is_weekdays_9_to_18_and_weekends_off():
    db = make_db()
    tech = User(username='tech', full_name='Техник', password_hash='x', role='technician', active=True)
    db.add(tech); db.commit()
    assert technician_available(db, tech.id, datetime(2026, 9, 24, 10, 0)) is True   # Thursday
    assert technician_available(db, tech.id, datetime(2026, 9, 24, 20, 0)) is False
    assert technician_available(db, tech.id, datetime(2026, 9, 26, 10, 0)) is False   # Saturday


def test_date_exception_overrides_regular_week():
    db = make_db()
    tech = User(username='tech', full_name='Техник', password_hash='x', role='technician', active=True)
    db.add(tech); db.flush()
    db.add(TechnicianAvailability(user_id=tech.id, weekday=3, start_time='09:00', end_time='18:00', available=True))
    db.add(TechnicianAvailabilityException(user_id=tech.id, exception_date=date(2026, 9, 24), kind='sick', available=False, start_time='09:00', end_time='18:00'))
    db.commit()
    assert technician_available(db, tech.id, datetime(2026, 9, 24, 11, 0)) is False


def test_duty_exception_can_make_weekend_available():
    db = make_db()
    tech = User(username='tech', full_name='Техник', password_hash='x', role='technician', active=True)
    db.add(tech); db.flush()
    db.add(TechnicianAvailabilityException(user_id=tech.id, exception_date=date(2026, 9, 26), kind='duty', available=True, start_time='10:00', end_time='14:00'))
    db.commit()
    assert technician_available(db, tech.id, datetime(2026, 9, 26, 11, 0)) is True
    assert technician_available(db, tech.id, datetime(2026, 9, 26, 16, 0)) is False


def test_schedule_template_is_weekly_and_has_exceptions():
    tpl = (ROOT / 'app/templates/team_schedule.html').read_text(encoding='utf-8')
    assert 'СТАНДАРТНЫЙ ГРАФИК' in tpl
    assert 'Исключения из графика' in tpl
    assert 'Пн–Пт' in tpl
    assert 'Временная смена' in tpl
    assert '/team/schedule/week' in tpl
    assert '/team/schedule/exception/add' in tpl


def test_schedule_link_moved_to_management_area():
    tpl = (ROOT / 'app/templates/base.html').read_text(encoding='utf-8')
    management = tpl.index("{{tr('management')}}")
    schedule = tpl.index('/team/schedule')
    assert schedule > management
