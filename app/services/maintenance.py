from datetime import date, datetime, timedelta
from sqlalchemy.orm import Session
from app.models import MaintenancePlan, Ticket

def next_ticket_number(db: Session) -> str:
    today = datetime.now().strftime("%y%m%d")
    prefix = f"SR-{today}-"
    last = db.query(Ticket).filter(Ticket.number.like(prefix + "%")).order_by(Ticket.id.desc()).first()
    seq = 1
    if last:
        try: seq = int(last.number.rsplit("-",1)[1]) + 1
        except Exception: pass
    return f"{prefix}{seq:03d}"

def generate_due_maintenance(db: Session) -> int:
    today = date.today()
    plans = db.query(MaintenancePlan).filter(MaintenancePlan.active == True, MaintenancePlan.next_run <= today).all()
    created = 0
    created_tickets = []
    for plan in plans:
        marker = f"[ППР:{plan.id}:{plan.next_run.isoformat()}]"
        exists = db.query(Ticket).filter(Ticket.description.contains(marker)).first()
        if exists: continue
        eq = plan.equipment
        ticket = Ticket(
            number=next_ticket_number(db),
            title=f"ППР: {plan.name} — {eq.name}",
            description=f"Плановая работа по оборудованию {eq.inventory_no}. {marker}\nЧек-лист: {plan.checklist}",
            category="ППР/ТО", priority="normal", status="new",
            site_id=eq.site_id, equipment_id=eq.id, assignee_id=plan.assignee_id,
            sla_due_at=datetime.combine(plan.next_run, datetime.min.time()) + timedelta(hours=23),
        )
        db.add(ticket)
        created_tickets.append(ticket)
        plan.last_run = plan.next_run
        plan.next_run = plan.next_run + timedelta(days=plan.interval_days)
        eq.next_maintenance_at = plan.next_run
        created += 1
    db.commit()
    # Push generated PPR tickets to 1C after the local transaction is committed.
    # Local import avoids a module-level circular dependency.
    try:
        from app.services.sync import push_ticket_to_1c
        for ticket in created_tickets:
            db.refresh(ticket)
            push_ticket_to_1c(db, ticket)
    except Exception as exc:
        print("maintenance 1C sync error:", exc)
    return created
