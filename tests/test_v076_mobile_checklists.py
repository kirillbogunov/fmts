from io import BytesIO
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.datastructures import UploadFile

from app.db import Base
from app.models import User, Site, Equipment, MaintenancePlan, MaintenanceChecklistItem, Ticket, KnowledgeArticle, KnowledgeAttachment
from app.services.maintenance_checklist import plan_checklist_rows, snapshot_checklist, ticket_checklist
from app.routes import enterprise


def make_db():
    engine=create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine,expire_on_commit=False)()


def seed(db):
    user=User(username='tech',full_name='Техник',password_hash='x',role='technician',active=True)
    site=Site(name='Фабрика кухни')
    db.add_all([user,site]);db.flush()
    eq=Equipment(site_id=site.id,name='Холодильник',inventory_no='XO-1',qr_token='q')
    db.add(eq);db.flush()
    plan=MaintenancePlan(equipment_id=eq.id,name='Ежемесячное ТО',interval_days=30,next_run=__import__('datetime').date(2026,10,1),assignee_id=user.id)
    db.add(plan);db.flush()
    return user,site,eq,plan


def test_hierarchical_checklist_numbering_and_snapshot():
    db=make_db();user,site,eq,plan=seed(db)
    a=MaintenanceChecklistItem(plan_id=plan.id,title='Визуальный осмотр',sort_order=10)
    db.add(a);db.flush()
    a1=MaintenanceChecklistItem(plan_id=plan.id,parent_id=a.id,title='Уплотнитель двери',sort_order=10)
    a2=MaintenanceChecklistItem(plan_id=plan.id,parent_id=a.id,title='Петли',sort_order=20)
    db.add_all([a1,a2]);db.flush()
    a11=MaintenanceChecklistItem(plan_id=plan.id,parent_id=a1.id,title='Трещины',sort_order=10)
    b=MaintenanceChecklistItem(plan_id=plan.id,title='Очистка конденсатора',sort_order=20)
    db.add_all([a11,b]);db.commit()
    rows=plan_checklist_rows(db,plan.id)
    assert [r['number'] for r in rows]==['1','1.1','1.1.1','1.2','2']
    ticket=Ticket(number='SR-1',title='ППР',site_id=site.id,equipment_id=eq.id,assignee_id=user.id,maintenance_plan_id=plan.id)
    db.add(ticket);db.flush()
    assert snapshot_checklist(db,plan,ticket)==5
    state=ticket_checklist(db,ticket.id)
    assert state['total']==5 and state['percent']==0 and state['complete'] is False
    for row in state['rows']:
        row.completed=True
    db.flush()
    assert ticket_checklist(db,ticket.id)['complete'] is True


def test_legacy_checklist_is_snapshotted():
    db=make_db();user,site,eq,plan=seed(db)
    plan.checklist='["Проверить температуру", "Очистить фильтр"]'
    ticket=Ticket(number='SR-2',title='ППР',site_id=site.id,equipment_id=eq.id,assignee_id=user.id,maintenance_plan_id=plan.id)
    db.add(ticket);db.flush()
    assert snapshot_checklist(db,plan,ticket)==2
    state=ticket_checklist(db,ticket.id)
    assert [x.number for x in state['rows']]==['1','2']


def test_knowledge_docx_pdf_image_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(enterprise.settings,'upload_dir',str(tmp_path))
    upload=UploadFile(filename='instruction.docx',file=BytesIO(b'PK-test-docx'))
    filename,stored,mime,size=enterprise._save_knowledge_file(upload)
    assert filename=='instruction.docx'
    assert stored.startswith('knowledge/') and Path(tmp_path,stored).exists()
    assert size>0
    bad=UploadFile(filename='script.html',file=BytesIO(b'<script>x</script>'))
    try:
        enterprise._save_knowledge_file(bad)
        assert False,'HTML must be rejected'
    except ValueError:
        pass
