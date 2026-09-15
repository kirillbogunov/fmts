import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db import Base
from app.models import UiStyle
from app.services.ui_styles import upsert_ui_styles, styles_cache, sla_hours_for


def test_external_style_import_is_supported_when_requested():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    count = upsert_ui_styles(db, [
        {"kind":"status","code":"new","name":"Новая","bg_color":"#112233","text_color":"#FFFFFF","border_color":"#445566","active":True},
        {"kind":"priority","code":"critical","name":"Срочный","bg_color":"#AA0000","text_color":"#FFFFFF","border_color":"#660000","sla_hours":1,"active":True},
    ])
    assert count == 2
    cache = styles_cache(db)
    assert cache['status']['new']['bg'] == '#112233'
    assert cache['priority']['critical']['text'] == '#FFFFFF'
    assert sla_hours_for(db, 'critical') == 1
