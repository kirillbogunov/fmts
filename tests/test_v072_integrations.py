from email.message import EmailMessage
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import User, Site, Ticket, TicketObserver, TicketComment, EmailRule, BackgroundServiceLog
from app.services import email_channel
from app.services.system_jobs import run_logged_job


def make_db():
    engine=create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_email_reply_adds_cc_observer_and_changes_status(monkeypatch):
    db=make_db()
    dispatcher=User(username='disp',full_name='Диспетчер',password_hash='x',role='dispatcher',active=True,email='disp@example.com')
    watcher=User(username='watch',full_name='Наблюдатель',password_hash='x',role='requester',active=True,email='watch@example.com')
    site=Site(name='Магазин')
    db.add_all([dispatcher,watcher,site]);db.flush()
    ticket=Ticket(number='SR-260923-001',title='Холодильник',site_id=site.id,status='assigned',requester_id=dispatcher.id,creator_id=dispatcher.id)
    db.add(ticket);db.commit()

    msg=EmailMessage()
    msg['From']='Диспетчер <disp@example.com>'
    msg['To']='service@example.com'
    msg['Cc']='watch@example.com'
    msg['Subject']='Re: SR-260923-001 холодильник'
    msg.set_content('[Статус: В работе]\nНачали диагностику')
    monkeypatch.setattr(email_channel.settings,'email_add_recipients_as_observers',True)
    monkeypatch.setattr(email_channel.settings,'email_status_commands_enabled',True)

    kind,ticket_id=email_channel.process_message(db,msg)
    db.commit();db.refresh(ticket)
    assert kind=='comment' and ticket_id==ticket.id
    assert ticket.status=='in_progress'
    assert db.query(TicketObserver).filter_by(ticket_id=ticket.id,user_id=watcher.id).count()==1
    assert db.query(TicketComment).filter_by(ticket_id=ticket.id).count()==1


def test_email_rule_changes_new_ticket(monkeypatch):
    db=make_db()
    site=Site(name='Главный объект');db.add(site);db.flush()
    rule=EmailRule(name='Срочная холодилка',subject_contains='холодильник',category='Холод',priority='critical',active=True)
    db.add(rule);db.commit()
    monkeypatch.setattr(email_channel.settings,'imap_default_site_id',site.id)
    msg=EmailMessage();msg['From']='client@example.com';msg['To']='service@example.com';msg['Subject']='Не работает холодильник';msg.set_content('Температура растет')
    kind,ticket_id=email_channel.process_message(db,msg);db.commit()
    ticket=db.get(Ticket,ticket_id)
    assert kind=='ticket'
    assert ticket.category=='Холод'
    assert ticket.priority=='critical'


def test_background_job_log_records_success_and_error(monkeypatch):
    # run_logged_job uses global SessionLocal, so temporarily point it at a fileless in-memory session factory
    from app.services import system_jobs
    db=make_db(); factory=lambda: db
    monkeypatch.setattr(system_jobs,'SessionLocal',factory)
    assert run_logged_job('ok_job',lambda session: 7)==7
    row=db.query(BackgroundServiceLog).filter_by(service='ok_job').one()
    assert row.status=='ok'
    result=run_logged_job('bad_job',lambda session: (_ for _ in ()).throw(RuntimeError('boom')))
    assert result is None
    row=db.query(BackgroundServiceLog).filter_by(service='bad_job').one()
    assert row.status=='error' and 'boom' in row.message
