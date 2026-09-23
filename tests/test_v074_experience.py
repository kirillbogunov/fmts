from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import User, Site, SavedFilter, FilterSubscription, Resource, ResourceBooking, SurveyTemplate, SurveyResponse
from app.services.localization import tr, format_dt
from app.services.report_subscriptions import _due, _apply_saved_filter
from app.services.zabbix_sync import sync_zabbix
from app.models import Ticket


def make_db():
    engine=create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_navigation_translation_ru_kk_en():
    assert tr('ru','tickets') == 'Заявки'
    assert tr('kk','tickets') == 'Өтінімдер'
    assert tr('en','tickets') == 'Tickets'


def test_timezone_formatting_uses_user_zone():
    dt=datetime(2026,1,1,0,0,0)
    assert format_dt(dt,'Asia/Almaty','%H:%M') == '05:00'
    assert format_dt(dt,'UTC','%H:%M') == '00:00'


def test_saved_filter_can_include_site_and_assignee():
    db=make_db()
    u=User(username='u',full_name='User',password_hash='x',role='dispatcher')
    s1=Site(name='A');s2=Site(name='B');db.add_all([u,s1,s2]);db.flush()
    t1=Ticket(number='T1',title='One',site_id=s1.id,assignee_id=u.id,priority='high')
    t2=Ticket(number='T2',title='Two',site_id=s2.id,priority='high')
    db.add_all([t1,t2]);db.commit()
    q=_apply_saved_filter(db.query(Ticket),{'site_id':str(s1.id),'assignee_id':str(u.id),'priority':'high'})
    assert [x.number for x in q.all()] == ['T1']


def test_resource_and_survey_models_roundtrip():
    db=make_db()
    u=User(username='u',full_name='User',password_hash='x',role='requester')
    site=Site(name='Shop');db.add_all([u,site]);db.flush()
    r=Resource(name='Автомобиль 1',resource_type='car',site_id=site.id,capacity=1)
    survey=SurveyTemplate(name='Качество',questions_json='[{"type":"rating","label":"Оценка"}]')
    db.add_all([r,survey]);db.flush()
    booking=ResourceBooking(resource_id=r.id,user_id=u.id,title='Выезд',start_at=datetime(2026,1,1,9),end_at=datetime(2026,1,1,10))
    response=SurveyResponse(survey_id=survey.id,ticket_id=1,user_id=u.id,answers_json='{"0":"5"}',score=5)
    # SurveyResponse ticket FK is not enforced by SQLite unless pragma is on; this validates model schema.
    db.add_all([booking,response]);db.commit()
    assert db.query(ResourceBooking).one().resource.name == 'Автомобиль 1'
    assert db.query(SurveyResponse).one().score == 5


def test_subscription_due_rules():
    now=datetime(2026,9,23,12,0,0)
    assert _due('daily',None,now)
    assert _due('daily',datetime(2026,9,22,23),now)
    assert not _due('daily',datetime(2026,9,23,1),now)


def test_zabbix_disabled_is_safe(monkeypatch):
    from app.services import zabbix_sync
    db=make_db()
    monkeypatch.setattr(zabbix_sync.settings,'zabbix_enabled',False)
    assert sync_zabbix(db)['enabled'] is False
