import sys, json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from jinja2 import Environment, FileSystemLoader
from app.db import Base
from app.models import User, Site, Ticket, AutomationRule, Notification, ServiceCatalog, CustomField, Equipment
from app.security import generate_totp_secret, _totp_code, verify_totp
from app.services.automation import apply_ticket_rules
from app.services.notifications import notify_user
import time

def make_db():
    engine=create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine,expire_on_commit=False)()

def test_totp_roundtrip():
    secret=generate_totp_secret(); code=_totp_code(secret,int(time.time())//30)
    assert len(code)==6 and verify_totp(secret,code)
    assert not verify_totp(secret,'000000') or code=='000000'

def test_automation_assigns_least_loaded_and_sets_sla():
    db=make_db()
    site=Site(name='Магазин'); db.add(site)
    t1=User(username='t1',full_name='Техник 1',password_hash='x',role='technician',active=True)
    t2=User(username='t2',full_name='Техник 2',password_hash='x',role='technician',active=True)
    db.add_all([t1,t2]); db.flush()
    db.add(Ticket(number='SR-1',title='Старая',site_id=site.id,assignee_id=t1.id,status='in_progress'))
    rule=AutomationRule(name='Авто',conditions_json=json.dumps({'category':'Холод'}),actions_json=json.dumps({'assign_least_loaded':True,'set_priority':'critical','sla_hours':2}))
    db.add(rule); db.flush()
    ticket=Ticket(number='SR-2',title='Новая',site_id=site.id,category='Холод',priority='normal',status='new')
    db.add(ticket);db.flush(); applied=apply_ticket_rules(db,ticket);db.commit()
    assert applied==['Авто']
    assert ticket.assignee_id==t2.id
    assert ticket.status=='assigned' and ticket.priority=='critical' and ticket.sla_due_at is not None

def test_notification_dedup():
    db=make_db();u=User(username='u',full_name='U',password_hash='x',role='requester',active=True);db.add(u);db.flush()
    notify_user(db,u,'A','B',dedup_key='x',external=False);notify_user(db,u,'A','B',dedup_key='x',external=False);db.commit()
    assert db.query(Notification).count()==1

def test_service_catalog_and_cmdb_models():
    db=make_db();site=Site(name='S');u=User(username='u',full_name='U',password_hash='x',role='requester',active=True);db.add_all([site,u]);db.flush()
    svc=ServiceCatalog(code='cold',name='Холод',category='Холод',default_priority='high');db.add(svc);db.flush()
    db.add(CustomField(service_id=svc.id,code='temp',name='Температура',field_type='number',required=True))
    parent=Equipment(site_id=site.id,name='Централь',inventory_no='P',qr_token='p');db.add(parent);db.flush()
    child=Equipment(site_id=site.id,name='Витрина',inventory_no='C',qr_token='c',parent_id=parent.id,owner_user_id=u.id,criticality='high');db.add(child);db.commit()
    assert child.parent_id==parent.id and child.criticality=='high'

def test_all_templates_parse():
    root=Path(__file__).resolve().parents[1]/'app'/'templates'
    env=Environment(loader=FileSystemLoader(str(root)))
    for path in root.glob('*.html'):
        env.get_template(path.name)
