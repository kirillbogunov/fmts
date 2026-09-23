import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import (
    User, Site, Ticket, SupportGroup, SupportGroupMember, TicketObserver,
    TicketTemplate, TicketTemplateTask,
)
from app.access import scope_ticket_query, can_view_ticket
from app.services.operations import pick_group_assignee, sync_group_observers


def make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def seed_people(db):
    admin = User(username="admin", full_name="Админ", password_hash="x", role="admin", active=True)
    tech1 = User(username="t1", full_name="Техник 1", password_hash="x", role="technician", active=True)
    tech2 = User(username="t2", full_name="Техник 2", password_hash="x", role="technician", active=True)
    req1 = User(username="r1", full_name="Заявитель 1", password_hash="x", role="requester", active=True)
    req2 = User(username="r2", full_name="Заявитель 2", password_hash="x", role="requester", active=True)
    site = Site(name="Магазин")
    db.add_all([admin, tech1, tech2, req1, req2, site])
    db.flush()
    return admin, tech1, tech2, req1, req2, site


def test_group_assignment_picks_least_loaded_executor():
    db = make_db()
    _, tech1, tech2, _, _, site = seed_people(db)
    group = SupportGroup(name="Холодильщики")
    db.add(group); db.flush()
    db.add_all([
        SupportGroupMember(group_id=group.id, user_id=tech1.id, member_role="executor"),
        SupportGroupMember(group_id=group.id, user_id=tech2.id, member_role="executor"),
    ])
    db.add(Ticket(number="SR-1", title="Busy", site_id=site.id, assignee_id=tech1.id, status="in_progress"))
    db.flush()
    assert pick_group_assignee(db, group.id).id == tech2.id


def test_group_and_observer_are_in_row_level_scope():
    db = make_db()
    _, tech1, _, req1, req2, site = seed_people(db)
    group = SupportGroup(name="Электрики")
    db.add(group); db.flush()
    db.add(SupportGroupMember(group_id=group.id, user_id=tech1.id, member_role="executor"))
    ticket = Ticket(number="SR-2", title="Group ticket", site_id=site.id, requester_id=req1.id, creator_id=req2.id, group_id=group.id)
    db.add(ticket); db.flush()
    db.add(TicketObserver(ticket_id=ticket.id, user_id=req1.id))
    db.commit()

    assert scope_ticket_query(db.query(Ticket), tech1).filter(Ticket.id == ticket.id).count() == 1
    assert scope_ticket_query(db.query(Ticket), req2).filter(Ticket.id == ticket.id).count() == 1
    assert can_view_ticket(tech1, ticket, db)


def test_group_observer_sync_adds_only_observer_members():
    db = make_db()
    _, tech1, tech2, req1, _, site = seed_people(db)
    group = SupportGroup(name="Команда")
    db.add(group); db.flush()
    db.add_all([
        SupportGroupMember(group_id=group.id, user_id=tech1.id, member_role="executor"),
        SupportGroupMember(group_id=group.id, user_id=tech2.id, member_role="observer"),
    ])
    ticket = Ticket(number="SR-3", title="T", site_id=site.id, requester_id=req1.id, group_id=group.id)
    db.add(ticket); db.flush()
    assert sync_group_observers(db, ticket) == 1
    db.flush()
    assert db.query(TicketObserver).filter_by(ticket_id=ticket.id, user_id=tech2.id).count() == 1
    assert db.query(TicketObserver).filter_by(ticket_id=ticket.id, user_id=tech1.id).count() == 0


def test_ticket_template_models_support_child_work_orders():
    db = make_db()
    tpl = TicketTemplate(name="ППР холодильника", title_template="Плановое ТО", category="Холод", priority="normal")
    db.add(tpl); db.flush()
    db.add_all([
        TicketTemplateTask(template_id=tpl.id, title="Очистить конденсатор", sort_order=10),
        TicketTemplateTask(template_id=tpl.id, title="Проверить давление", sort_order=20),
    ])
    db.commit()
    tasks = db.query(TicketTemplateTask).filter_by(template_id=tpl.id).order_by(TicketTemplateTask.sort_order).all()
    assert [x.title for x in tasks] == ["Очистить конденсатор", "Проверить давление"]
