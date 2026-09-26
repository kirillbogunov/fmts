from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import User, Site, Ticket, TicketWorkSession
from app.routes.enterprise import _build_report_data

ROOT = Path(__file__).resolve().parents[1]


def make_db():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_report_studio_aggregates_operational_financial_and_sla_data():
    db = make_db()
    admin = User(username='admin', full_name='Администратор', password_hash='x', role='admin', active=True)
    tech = User(username='tech', full_name='Петров Пётр', password_hash='x', role='technician', active=True)
    site = Site(name='Фабрика кухни')
    db.add_all([admin, tech, site]); db.flush()
    now = datetime.utcnow()
    done = Ticket(number='R-1', title='Готово', site_id=site.id, requester_id=admin.id, assignee_id=tech.id,
                  status='resolved', created_at=now-timedelta(days=3), resolved_at=now-timedelta(days=2),
                  sla_due_at=now-timedelta(days=1), labor_cost=Decimal('5000'), parts_cost=Decimal('7000'))
    overdue = Ticket(number='R-2', title='Просрочка', site_id=site.id, requester_id=admin.id, assignee_id=tech.id,
                     status='in_progress', created_at=now-timedelta(days=2), sla_due_at=now-timedelta(hours=2),
                     labor_cost=Decimal('1000'), parts_cost=Decimal('2000'))
    db.add_all([done, overdue]); db.flush()
    db.add(TicketWorkSession(ticket_id=done.id, user_id=tech.id, started_at=now-timedelta(days=3), ended_at=now-timedelta(days=3, hours=-1), duration_seconds=3600))
    db.commit()

    report = _build_report_data(db, admin, 'site', 30)
    assert report['summary']['total'] == 2
    assert report['summary']['closed'] == 1
    assert report['summary']['open'] == 1
    assert report['summary']['overdue'] == 1
    assert report['summary']['hours'] == 1.0
    assert report['summary']['total_cost'] == 15000.0
    assert report['rows'][0]['name'] == 'Фабрика кухни'
    assert report['rows'][0]['count'] == 2
    assert report['rows'][0]['completion_pct'] == 50.0
    assert report['trend']
    assert report['status_chart']


def test_report_studio_template_has_interactive_charts_and_mobile_cards():
    html = (ROOT / 'app/templates/report_builder.html').read_text(encoding='utf-8')
    css = (ROOT / 'app/static/app.css').read_text(encoding='utf-8')
    assert 'reportTrendChart' in html
    assert 'reportStatusChart' in html
    assert 'reportGroupChart' in html
    assert 'reportCostChart' in html
    assert '/reports/builder.csv' in html
    assert 'report-kpi-grid' in html
    assert 'FMTS 8.0 — Report Studio' in css
    assert '@media(max-width:520px)' in css


def test_report_studio_version_is_8():
    config = (ROOT / 'app/config.py').read_text(encoding='utf-8')
    sw = (ROOT / 'app/static/service-worker.js').read_text(encoding='utf-8')
    assert 'app_version: str = "8.0.1"' in config
    assert 'fmts-v80' in sw
