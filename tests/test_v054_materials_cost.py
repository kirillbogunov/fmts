import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import InventoryItem, Site, StockMovement, Ticket, User
from app.services.materials import ticket_material_summary, recalc_ticket_parts_cost
from app.access import has_permission


def make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_material_snapshot_and_ticket_total():
    db = make_db()
    tech = User(username="tech", full_name="Техник", password_hash="x", role="technician", active=True)
    site = Site(name="Магазин")
    item = InventoryItem(sku="MAT-1", name="Фильтр", qty=10, unit="шт", unit_cost=Decimal("1250.50"))
    db.add_all([tech, site, item]); db.flush()
    ticket = Ticket(number="T-1", title="Ремонт", site_id=site.id, assignee_id=tech.id, status="in_progress", labor_cost=Decimal("3000.00"))
    db.add(ticket); db.flush()
    movement = StockMovement(
        item_id=item.id,
        ticket_id=ticket.id,
        movement_type="issue",
        qty=-2,
        unit_cost_snapshot=Decimal("1250.50"),
        amount=Decimal("2501.00"),
        issued_by_id=tech.id,
    )
    db.add(movement); db.flush()

    summary = ticket_material_summary(db, ticket.id)
    assert summary["count"] == 1
    assert summary["rows"][0]["qty"] == 2
    assert summary["rows"][0]["unit_cost"] == Decimal("1250.50")
    assert summary["rows"][0]["amount"] == Decimal("2501.00")
    assert summary["rows"][0]["issued_by"].id == tech.id
    assert summary["total"] == Decimal("2501.00")

    recalc_ticket_parts_cost(db, ticket)
    assert ticket.parts_cost == Decimal("2501.00")
    assert Decimal(ticket.labor_cost) + Decimal(ticket.parts_cost) == Decimal("5501.00")

    # Historical amount must not change when the catalogue price changes.
    item.unit_cost = Decimal("9999.00")
    db.flush()
    summary2 = ticket_material_summary(db, ticket.id)
    assert summary2["total"] == Decimal("2501.00")


def test_material_permissions():
    db = make_db()
    roles = {}
    for role in ("requester", "technician", "dispatcher", "manager", "admin"):
        u = User(username=role, full_name=role, password_hash="x", role=role, active=True)
        db.add(u); db.flush(); roles[role] = u
    assert not has_permission(roles["requester"], "ticket.materials.view")
    assert has_permission(roles["technician"], "ticket.materials.view")
    assert has_permission(roles["dispatcher"], "ticket.materials.view")
    assert has_permission(roles["manager"], "ticket.materials.view")
    assert has_permission(roles["admin"], "ticket.materials.view")
    assert not has_permission(roles["technician"], "ticket.cost")
    assert has_permission(roles["manager"], "ticket.cost")
