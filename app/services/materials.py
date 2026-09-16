from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.orm import Session

from app.models import StockMovement, Ticket

CENT = Decimal("0.01")


def as_money(value) -> Decimal:
    try:
        return Decimal(str(value or 0)).quantize(CENT, rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal("0.00")


def movement_unit_cost(movement: StockMovement) -> Decimal:
    if movement.unit_cost_snapshot is not None:
        return as_money(movement.unit_cost_snapshot)
    return as_money(movement.item.unit_cost if movement.item else 0)


def movement_amount(movement: StockMovement) -> Decimal:
    if movement.amount is not None:
        return as_money(movement.amount)
    qty = Decimal(str(abs(movement.qty or 0)))
    return (qty * movement_unit_cost(movement)).quantize(CENT, rounding=ROUND_HALF_UP)


def ticket_material_summary(db: Session, ticket_id: int) -> dict:
    movements = (
        db.query(StockMovement)
        .filter(
            StockMovement.ticket_id == ticket_id,
            StockMovement.movement_type == "issue",
        )
        .order_by(StockMovement.created_at.asc(), StockMovement.id.asc())
        .all()
    )
    rows = []
    total = Decimal("0.00")
    for movement in movements:
        amount = movement_amount(movement)
        total += amount
        rows.append({
            "movement": movement,
            "item": movement.item,
            "qty": abs(float(movement.qty or 0)),
            "unit": movement.item.unit if movement.item else "",
            "unit_cost": movement_unit_cost(movement),
            "amount": amount,
            "issued_by": movement.issued_by,
            "created_at": movement.created_at,
        })
    return {
        "rows": rows,
        "total": total.quantize(CENT, rounding=ROUND_HALF_UP),
        "count": len(rows),
    }


def recalc_ticket_parts_cost(db: Session, ticket: Ticket) -> Decimal:
    total = ticket_material_summary(db, ticket.id)["total"]
    ticket.parts_cost = total
    return total
