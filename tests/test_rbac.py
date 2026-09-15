import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import User, Site, Ticket
from app.access import (
    has_permission, scope_ticket_query, can_view_ticket,
    allowed_statuses, can_change_ticket_status,
)
from app.services.time_tracking import can_track_time


def make_db():
    engine=create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def users(db):
    req=User(username='req',full_name='Заявитель',password_hash='x',role='requester',active=True)
    tech=User(username='tech',full_name='Техник',password_hash='x',role='technician',active=True)
    disp=User(username='disp',full_name='Диспетчер',password_hash='x',role='dispatcher',active=True)
    mgr=User(username='mgr',full_name='Руководитель',password_hash='x',role='manager',active=True)
    adm=User(username='adm',full_name='Администратор',password_hash='x',role='admin',active=True)
    db.add_all([req,tech,disp,mgr,adm]); db.flush()
    return req,tech,disp,mgr,adm


def test_role_permissions_are_strict():
    db=make_db(); req,tech,disp,mgr,adm=users(db)
    assert has_permission(req,'ticket.create')
    assert not has_permission(req,'inventory.view')
    assert has_permission(tech,'ticket.time.track')
    assert not has_permission(tech,'ticket.assign')
    assert has_permission(disp,'ticket.assign')
    assert not has_permission(disp,'users.manage')
    assert not has_permission(disp,'kpi.all')
    assert has_permission(mgr,'kpi.all')
    assert has_permission(mgr,'audit.view')
    assert has_permission(adm,'users.manage')
    assert has_permission(adm,'integration.manage')


def test_ticket_row_level_security():
    db=make_db(); req,tech,disp,mgr,adm=users(db)
    site=Site(name='Объект'); db.add(site); db.flush()
    own=Ticket(number='T-1',title='Своя',site_id=site.id,requester_id=req.id,assignee_id=tech.id,status='assigned')
    other=Ticket(number='T-2',title='Чужая',site_id=site.id,requester_id=disp.id,status='new')
    db.add_all([own,other]); db.commit()

    assert [t.id for t in scope_ticket_query(db.query(Ticket),req).all()] == [own.id]
    assert [t.id for t in scope_ticket_query(db.query(Ticket),tech).all()] == [own.id]
    assert {t.id for t in scope_ticket_query(db.query(Ticket),disp).all()} == {own.id,other.id}
    assert can_view_ticket(req,own)
    assert not can_view_ticket(req,other)
    assert can_view_ticket(tech,own)
    assert not can_view_ticket(tech,other)
    assert can_view_ticket(mgr,other)


def test_technician_status_machine_and_timer_scope():
    db=make_db(); req,tech,disp,mgr,adm=users(db)
    site=Site(name='Объект'); db.add(site); db.flush()
    ticket=Ticket(number='T-1',title='Работа',site_id=site.id,requester_id=req.id,assignee_id=tech.id,status='assigned')
    db.add(ticket); db.commit()

    assert 'in_progress' in allowed_statuses(tech,ticket)
    assert 'closed' not in allowed_statuses(tech,ticket)
    assert can_change_ticket_status(tech,ticket,'in_progress').allowed
    assert not can_change_ticket_status(tech,ticket,'closed').allowed
    assert can_track_time(tech,ticket)

    stranger=User(username='tech2',full_name='Другой техник',password_hash='x',role='technician',active=True)
    db.add(stranger); db.commit()
    assert not can_track_time(stranger,ticket)


def test_manager_can_close_but_dispatcher_cannot():
    db=make_db(); req,tech,disp,mgr,adm=users(db)
    site=Site(name='Объект'); db.add(site); db.flush()
    ticket=Ticket(number='T-1',title='Работа',site_id=site.id,requester_id=req.id,assignee_id=tech.id,status='resolved')
    db.add(ticket); db.commit()
    assert not can_change_ticket_status(disp,ticket,'closed').allowed
    assert can_change_ticket_status(mgr,ticket,'closed').allowed
    assert can_change_ticket_status(adm,ticket,'closed').allowed
