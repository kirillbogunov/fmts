from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import User, PushSubscription
from app.services.notifications import push_allowed


def make_db():
    engine=create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine,expire_on_commit=False)()


def test_push_preferences_filter_event_types():
    db=make_db()
    u=User(username='u',full_name='User',password_hash='x',role='requester',active=True,timezone='UTC',push_enabled=True,push_assignments=True,push_comments=False)
    db.add(u);db.commit()
    assert push_allowed(u,'assignment',datetime(2026,9,24,12,0)) is True
    assert push_allowed(u,'comment',datetime(2026,9,24,12,0)) is False


def test_quiet_hours_support_overnight_window():
    db=make_db()
    u=User(username='u2',full_name='User 2',password_hash='x',role='technician',active=True,timezone='UTC',push_enabled=True,push_quiet_start='22:00',push_quiet_end='07:00')
    db.add(u);db.commit()
    assert push_allowed(u,'general',datetime(2026,9,24,23,0)) is False
    assert push_allowed(u,'general',datetime(2026,9,24,6,30)) is False
    assert push_allowed(u,'general',datetime(2026,9,24,12,0)) is True


def test_push_subscription_stores_device_metadata():
    db=make_db()
    u=User(username='u3',full_name='User 3',password_hash='x',role='technician',active=True)
    db.add(u);db.flush()
    sub=PushSubscription(user_id=u.id,endpoint='https://push.example/sub',p256dh='p',auth='a',device_name='iPhone · FMTS PWA',user_agent='Safari',active=True)
    db.add(sub);db.commit();db.refresh(sub)
    assert sub.device_name.startswith('iPhone')
    assert sub.active is True
    assert sub.updated_at is not None
