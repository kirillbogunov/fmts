import sys
from decimal import Decimal
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db import Base
from app.models import InventoryItem, Site, StockMovement, Ticket, User
from app.services.materials import movement_amount, movement_unit_cost
from app.access import can_view_ticket, has_permission


def make_db():
    engine=create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine,expire_on_commit=False)()


def test_inventory_history_contains_ticket_and_cost_snapshot():
    db=make_db()
    tech=User(username="tech",full_name="Техник",password_hash="x",role="technician",active=True)
    other=User(username="other",full_name="Другой",password_hash="x",role="technician",active=True)
    manager=User(username="mgr",full_name="Руководитель",password_hash="x",role="manager",active=True)
    site=Site(name="Магазин №1")
    item=InventoryItem(sku="ZIP-10",name="Реле",qty=7,unit="шт",unit_cost=Decimal("900.00"))
    db.add_all([tech,other,manager,site,item]); db.flush()
    own=Ticket(number="T-1",title="Ремонт витрины",site_id=site.id,assignee_id=tech.id,status="in_progress")
    чужая=Ticket(number="T-2",title="Другой ремонт",site_id=site.id,assignee_id=other.id,status="in_progress")
    db.add_all([own,чужая]); db.flush()
    m1=StockMovement(item_id=item.id,ticket_id=own.id,movement_type="issue",qty=-2,unit_cost_snapshot=Decimal("800.00"),amount=Decimal("1600.00"),issued_by_id=tech.id)
    m2=StockMovement(item_id=item.id,ticket_id=чужая.id,movement_type="issue",qty=-1,unit_cost_snapshot=Decimal("850.00"),amount=Decimal("850.00"),issued_by_id=other.id)
    db.add_all([m1,m2]); db.commit()

    assert movement_unit_cost(m1)==Decimal("800.00")
    assert movement_amount(m1)==Decimal("1600.00")
    assert can_view_ticket(tech,own)
    assert not can_view_ticket(tech,чужая)
    assert has_permission(manager,"ticket.cost")
    assert not has_permission(tech,"ticket.cost")
