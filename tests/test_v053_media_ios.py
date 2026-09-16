import sys
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from starlette.datastructures import Headers, UploadFile
from starlette.requests import Request

from app.config import Settings
from app.db import Base
from app.migrations import run_lightweight_migrations
from app.models import Attachment, Equipment, Site, Ticket, TicketComment, User
import app.routes.web as web


def make_request(path='/equipment/1/label.svg'):
    scope={
        'type':'http','http_version':'1.1','method':'GET','scheme':'https',
        'path':path,'raw_path':path.encode(),'query_string':b'',
        'headers':[(b'host',b'fmts.example.kz')],
        'server':('fmts.example.kz',443),'client':('127.0.0.1',12345),
    }
    return Request(scope)


def test_equipment_label_contains_visible_identity(monkeypatch):
    engine=create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    Session=sessionmaker(bind=engine,expire_on_commit=False)
    db=Session()
    admin=User(username='admin',full_name='Администратор',password_hash='x',role='admin',active=True)
    site=Site(name='Семейный №5',address='Петропавловск, ул. Абая 10')
    db.add_all([admin,site]); db.flush()
    eq=Equipment(site_id=site.id,name='Холодильная витрина',inventory_no='INV-005-17',qr_token='token-123')
    db.add(eq); db.commit()
    monkeypatch.setattr(web,'user_or_login',lambda request,db: admin)
    monkeypatch.setattr(web,'settings',Settings(_env_file=None,public_base_url='https://fmts.example.kz'))
    response=web.equipment_label_svg(eq.id,make_request(),db)
    svg=response.body.decode('utf-8')
    assert 'Холодильная витрина' in svg
    assert 'Семейный №5' in svg
    assert 'INV-005-17' in svg
    assert 'ЭТИКЕТКА ОБОРУДОВАНИЯ' in svg
    assert 'data:image/png;base64,' in svg


def test_comment_photo_validation_accepts_photo_and_rejects_svg(monkeypatch):
    monkeypatch.setattr(web,'settings',Settings(_env_file=None,comment_photo_max_mb=1))
    photo=UploadFile(file=BytesIO(b'jpegdata'),filename='photo.jpg',headers=Headers({'content-type':'image/jpeg'}))
    filename,stored,data=web._prepare_comment_photo(photo)
    assert filename == 'photo.jpg'
    assert stored.endswith('.jpg')
    assert data == b'jpegdata'
    svg=UploadFile(file=BytesIO(b'<svg/>'),filename='bad.svg',headers=Headers({'content-type':'image/svg+xml'}))
    try:
        web._prepare_comment_photo(svg)
        assert False, 'SVG must be rejected for comment photos'
    except ValueError:
        pass


def test_comment_attachment_relationship():
    engine=create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    Session=sessionmaker(bind=engine,expire_on_commit=False)
    db=Session()
    site=Site(name='Объект'); user=User(username='t',full_name='Техник',password_hash='x',role='technician',active=True)
    db.add_all([site,user]); db.flush()
    ticket=Ticket(number='T-1',title='Ремонт',site_id=site.id,assignee_id=user.id,status='assigned')
    db.add(ticket); db.flush()
    comment=TicketComment(ticket_id=ticket.id,user_id=user.id,body='Фото после ремонта')
    db.add(comment); db.flush()
    att=Attachment(ticket_id=ticket.id,comment_id=comment.id,filename='after.jpg',stored_name='x.jpg')
    db.add(att); db.commit(); db.refresh(comment)
    assert [x.filename for x in comment.attachments] == ['after.jpg']


def test_existing_attachment_table_gets_comment_id_migration(tmp_path):
    db_path=tmp_path/'old.db'
    engine=create_engine(f'sqlite:///{db_path}')
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE attachments (id INTEGER PRIMARY KEY, ticket_id INTEGER NOT NULL, filename VARCHAR(255), stored_name VARCHAR(255), uploaded_at DATETIME)'))
    run_lightweight_migrations(engine)
    cols={c['name'] for c in inspect(engine).get_columns('attachments')}
    assert 'comment_id' in cols


def test_ios_pwa_header_uses_safe_area_and_non_translucent_status_bar():
    root=Path(__file__).resolve().parents[1]
    css=(root/'app/static/app.css').read_text(encoding='utf-8')
    base=(root/'app/templates/base.html').read_text(encoding='utf-8')
    assert 'padding-top:calc(56px + env(safe-area-inset-top,0px))' in css
    assert 'height:calc(56px + env(safe-area-inset-top,0px))' in css
    assert 'apple-mobile-web-app-status-bar-style" content="black"' in base
