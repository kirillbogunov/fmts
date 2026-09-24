from datetime import date, timedelta, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import User, Site, Equipment, MaintenancePlan, Ticket, Notification, BusinessCalendar
from app.services.maintenance import generate_due_maintenance, complete_maintenance_plan
from app.services.itsm import TICKET_TYPES


def make_db():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def seed_plan(db):
    owner = User(username='owner', full_name='Ответственный', password_hash='x', role='requester', active=True)
    tech = User(username='tech', full_name='Техник', password_hash='x', role='technician', active=True)
    dispatcher = User(username='disp', full_name='Диспетчер', password_hash='x', role='dispatcher', active=True)
    site = Site(name='Фабрика кухни', address='Петропавловск')
    db.add_all([owner, tech, dispatcher, site]); db.flush()
    eq = Equipment(site_id=site.id, name='Холодильник', inventory_no='ХО-1', qr_token='qr-ho-1', owner_user_id=owner.id)
    db.add(eq); db.flush()
    db.add(BusinessCalendar(name='Основной график', timezone='Asia/Almaty', weekdays='0,1,2,3,4', work_start='09:00', work_end='18:00', active=True))
    plan = MaintenancePlan(
        equipment_id=eq.id,
        name='Ежемесячное ТО',
        interval_days=30,
        next_run=date.today() + timedelta(days=7),
        assignee_id=tech.id,
        create_before_days=7,
        notify_before_days=7,
        repeat_notify_before_days=1,
        notify_owner=True,
        notify_assignee=True,
        notify_dispatchers=True,
        response_sla_minutes=480,
        due_time='18:00',
        grace_days=1,
        active=True,
    )
    db.add(plan); db.commit()
    return plan, owner, tech, dispatcher, site, eq


def test_planned_maintenance_ticket_is_system_created_and_site_is_requester():
    db = make_db(); plan, owner, tech, dispatcher, site, eq = seed_plan(db)
    assert generate_due_maintenance(db) == 1
    ticket = db.query(Ticket).filter(Ticket.maintenance_plan_id == plan.id).one()
    assert ticket.ticket_type == 'maintenance'
    assert TICKET_TYPES['maintenance'] == 'Плановое ТО'
    assert ticket.creator is not None and ticket.creator.full_name == 'Система'
    assert ticket.creator.active is False
    assert ticket.requester_id is None
    assert ticket.requester_name == site.name
    assert ticket.site_id == site.id and ticket.equipment_id == eq.id
    assert ticket.assignee_id == tech.id and ticket.status == 'assigned'
    assert ticket.planned_start_at is not None
    assert ticket.planned_end_at is not None
    assert ticket.response_due_at is not None
    assert ticket.sla_due_at is not None and ticket.sla_due_at > ticket.planned_end_at


def test_planned_maintenance_creation_notifies_configured_targets_once():
    db = make_db(); plan, owner, tech, dispatcher, *_ = seed_plan(db)
    generate_due_maintenance(db)
    rows = db.query(Notification).filter(Notification.dedup_key.like(f'maintenance:{plan.id}:%:created:%')).all()
    assert {x.user_id for x in rows} == {owner.id, tech.id, dispatcher.id}
    # The hourly generator is idempotent: no duplicate request and no duplicate notifications.
    assert generate_due_maintenance(db) == 0
    rows2 = db.query(Notification).filter(Notification.dedup_key.like(f'maintenance:{plan.id}:%:created:%')).all()
    assert len(rows2) == 3


def test_plan_advances_only_after_ticket_completion():
    db = make_db(); plan, *_ = seed_plan(db)
    original = plan.next_run
    generate_due_maintenance(db)
    db.refresh(plan)
    assert plan.next_run == original
    ticket = db.query(Ticket).filter(Ticket.maintenance_plan_id == plan.id).one()
    assert complete_maintenance_plan(db, ticket, datetime.utcnow()) is True
    db.commit(); db.refresh(plan)
    assert plan.last_run == original
    assert plan.next_run == original + timedelta(days=30)
    assert complete_maintenance_plan(db, ticket, datetime.utcnow()) is False
