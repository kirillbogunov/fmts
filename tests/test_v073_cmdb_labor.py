from datetime import datetime, timedelta
from io import BytesIO
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.datastructures import UploadFile

from app.db import Base
from app.models import User, Site, Ticket, TicketWorkSession, CategoryNode
from app.routes.assets_plus import _template_xlsx, _rows_from_upload
from app.services.categories import category_options
from app.services.smart_search import rank_search
from app.services.time_tracking import apply_session_cost, recalculate_ticket_labor_cost


def make_db():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_labor_snapshot_and_ticket_cost():
    db = make_db()
    user = User(username='tech', full_name='Техник', password_hash='x', role='technician', hourly_rate=Decimal('3600'))
    site = Site(name='Магазин')
    db.add_all([user, site]); db.flush()
    ticket = Ticket(number='T-1', title='Ремонт', site_id=site.id, requester_id=user.id, assignee_id=user.id, manual_labor_cost=Decimal('500'))
    db.add(ticket); db.flush()
    entry = TicketWorkSession(ticket_id=ticket.id, user_id=user.id, started_at=datetime.utcnow()-timedelta(minutes=30), ended_at=datetime.utcnow(), duration_seconds=1800, source='manual', hourly_rate_snapshot=Decimal('3600'))
    db.add(entry); db.flush()
    apply_session_cost(entry)
    recalculate_ticket_labor_cost(db, ticket.id)
    assert entry.labor_amount == Decimal('1800.00')
    assert ticket.labor_cost == Decimal('2300.00')


def test_category_tree_paths():
    db = make_db()
    root = CategoryNode(kind='equipment', name='Холодильное оборудование', code='cold')
    db.add(root); db.flush()
    child = CategoryNode(kind='equipment', name='Бонеты', code='bonnet', parent_id=root.id)
    db.add(child); db.commit()
    opts = category_options(db, 'equipment')
    assert [x.code for x in opts] == ['Холодильное оборудование', 'Холодильное оборудование / Бонеты']


def test_search_handles_russian_word_forms():
    class Item:
        def __init__(self, text): self.text = text
    items = [Item('Ремонт холодильника в торговом зале'), Item('Замена лампы')]
    result = rank_search('холодильники', items, lambda x: x.text)
    assert result and result[0].text.startswith('Ремонт холодильника')


def test_excel_import_reader_roundtrip():
    data = _template_xlsx(['inventory_no','name','site'], [['EQ-1','Бонета','Магазин №1']], 'CMDB')
    upload = UploadFile(filename='cmdb.xlsx', file=BytesIO(data))
    rows = _rows_from_upload(upload)
    assert rows[0]['inventory_no'] == 'EQ-1'
    assert rows[0]['name'] == 'Бонета'
    assert rows[0]['site'] == 'Магазин №1'
