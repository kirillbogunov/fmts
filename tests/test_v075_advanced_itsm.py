from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import BusinessCalendar, ServiceCatalog, Site, Ticket, User, WebhookEndpoint, WebhookDelivery, Equipment, EquipmentRelation
from app.services.sla_calendar import add_business_minutes, apply_service_sla, mark_first_response
from app.services.webhooks import enqueue_ticket_event, process_webhook_deliveries


def make_db():
    engine=create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine,expire_on_commit=False)()


def as_utc_naive(local_dt):
    return local_dt.astimezone(timezone.utc).replace(tzinfo=None)


def test_business_calendar_skips_weekend():
    cal=BusinessCalendar(name='Пятидневка',timezone='Asia/Almaty',weekdays='0,1,2,3,4',work_start='09:00',work_end='18:00',holidays_json='[]')
    start=as_utc_naive(datetime(2026,9,25,17,30,tzinfo=ZoneInfo('Asia/Almaty')))  # Friday
    due=add_business_minutes(start,120,cal)
    local=due.replace(tzinfo=timezone.utc).astimezone(ZoneInfo('Asia/Almaty'))
    assert (local.weekday(),local.hour,local.minute)==(0,10,30)


def test_service_sla_sets_response_and_resolution_deadlines():
    db=make_db()
    cal=BusinessCalendar(name='24 workday',timezone='Asia/Almaty',weekdays='0,1,2,3,4,5,6',work_start='00:00',work_end='23:59',holidays_json='[]')
    db.add(cal);db.flush()
    service=ServiceCatalog(code='repair',name='Ремонт',response_sla_minutes=30,resolution_sla_minutes=120,business_calendar_id=cal.id)
    site=Site(name='Магазин');db.add_all([service,site]);db.flush()
    start=datetime(2026,9,24,5,0,0)
    ticket=Ticket(number='SR-1',title='Неисправность',site_id=site.id,created_at=start)
    apply_service_sla(db,ticket,service,start_at=start)
    assert ticket.business_calendar_id==cal.id
    assert ticket.response_due_at is not None and ticket.sla_due_at is not None
    assert ticket.response_due_at < ticket.sla_due_at


def test_first_response_is_written_once():
    db=make_db();site=Site(name='S');db.add(site);db.flush()
    t=Ticket(number='SR-2',title='A',site_id=site.id)
    db.add(t);db.flush()
    assert mark_first_response(db,t,actor_role='technician',when=datetime(2026,9,24,10,0)) is True
    first=t.first_response_at
    assert mark_first_response(db,t,actor_role='manager',when=datetime(2026,9,24,11,0)) is False
    assert t.first_response_at==first


def test_webhook_queue_and_delivery(monkeypatch):
    db=make_db();site=Site(name='S');db.add(site);db.flush()
    t=Ticket(number='SR-3',title='Webhook',site_id=site.id)
    ep=WebhookEndpoint(name='n8n',url='https://example.test/fmts',secret='secret',events='ticket.created')
    db.add_all([t,ep]);db.flush()
    assert enqueue_ticket_event(db,'ticket.created',t)==1
    db.commit()
    captured={}
    class Resp:
        status_code=200;text='OK'
    class Client:
        def __init__(self,*a,**kw): pass
        def __enter__(self): return self
        def __exit__(self,*a): pass
        def post(self,url,content=None,headers=None):
            captured.update(url=url,content=content,headers=headers);return Resp()
    monkeypatch.setattr('app.services.webhooks.httpx.Client',Client)
    assert process_webhook_deliveries(db)==1
    row=db.query(WebhookDelivery).one()
    assert row.status=='delivered' and row.attempts==1
    assert captured['headers']['X-FMTS-Signature'].startswith('sha256=')
    body=json.loads(captured['content'])
    assert body['event']=='ticket.created' and body['data']['number']=='SR-3'


def test_cmdb_arbitrary_relation_model():
    db=make_db();site=Site(name='S');db.add(site);db.flush()
    a=Equipment(site_id=site.id,name='Щит',inventory_no='A',qr_token='a')
    b=Equipment(site_id=site.id,name='Бонета',inventory_no='B',qr_token='b')
    db.add_all([a,b]);db.flush()
    rel=EquipmentRelation(source_equipment_id=a.id,target_equipment_id=b.id,relation_type='powers',note='Линия 3')
    db.add(rel);db.commit()
    assert rel.source.name=='Щит' and rel.target.name=='Бонета'
