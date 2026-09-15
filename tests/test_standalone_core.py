import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db import Base
from app.models import UiStyle, Site, Ticket
from app.services.reference_data import ensure_default_reference_data
from app.services.ui_styles import styles_cache, sla_hours_for


def make_db():
    engine=create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_standalone_defaults_exist_without_1c():
    db=make_db()
    created=ensure_default_reference_data(db)
    assert created > 0
    cache=styles_cache(db)
    assert cache['status']['new']['name'] == 'Новая'
    assert cache['priority']['critical']['name'] == 'Срочный'
    assert sla_hours_for(db,'critical') == 2
    assert 'Другое' in cache['category']


def test_local_settings_are_master():
    db=make_db(); ensure_default_reference_data(db)
    row=db.query(UiStyle).filter(UiStyle.kind=='priority',UiStyle.code=='critical').one()
    row.name='Аварийный'; row.sla_hours=1; row.bg_color='#990000'; db.commit()
    cache=styles_cache(db)
    assert cache['priority']['critical']['name'] == 'Аварийный'
    assert cache['priority']['critical']['bg'] == '#990000'
    assert sla_hours_for(db,'critical') == 1
