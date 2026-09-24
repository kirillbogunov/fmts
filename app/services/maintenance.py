from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from sqlalchemy.orm import Session

from app.models import MaintenancePlan, Ticket, User, BusinessCalendar, Equipment
from app.services.ticket_lifecycle import ensure_initial_history
from app.services.maintenance_checklist import snapshot_checklist
from app.services.notifications import notify_user
from app.services.sla_calendar import add_business_minutes, parse_local_to_utc


def next_ticket_number(db: Session) -> str:
    today = datetime.now().strftime("%y%m%d")
    prefix = f"SR-{today}-"
    last = db.query(Ticket).filter(Ticket.number.like(prefix + "%")).order_by(Ticket.id.desc()).first()
    seq = 1
    if last:
        try:
            seq = int(last.number.rsplit("-", 1)[1]) + 1
        except Exception:
            pass
    return f"{prefix}{seq:03d}"


def ensure_system_user(db: Session) -> User:
    """Return a disabled technical account used only as the creator of system jobs."""
    user = db.query(User).filter(User.username == "__system__").first()
    if not user:
        user = User(
            username="__system__",
            full_name="Система",
            password_hash="!SYSTEM-ACCOUNT-NO-LOGIN!",
            role="requester",
            active=False,
            directory_source="system",
            locale="ru",
            timezone="Asia/Almaty",
        )
        db.add(user)
        db.flush()
    else:
        user.full_name = "Система"
        user.active = False
        user.directory_source = "system"
    return user


def _default_calendar(db: Session) -> BusinessCalendar | None:
    return (
        db.query(BusinessCalendar)
        .filter(BusinessCalendar.active == True)
        .order_by(BusinessCalendar.id)
        .first()
    )


def _marker(plan_id: int, run_date: date) -> str:
    return f"[ППР:{plan_id}:{run_date.isoformat()}]"


def _ticket_for_occurrence(db: Session, plan: MaintenancePlan, run_date: date) -> Ticket | None:
    return (
        db.query(Ticket)
        .filter(Ticket.maintenance_plan_id == plan.id, Ticket.description.contains(_marker(plan.id, run_date)))
        .order_by(Ticket.id.desc())
        .first()
    )


def _window_utc(db: Session, plan: MaintenancePlan, run_date: date) -> tuple[datetime, datetime, datetime, BusinessCalendar | None]:
    calendar = _default_calendar(db)
    timezone = calendar.timezone if calendar else "Asia/Almaty"
    start_time = (calendar.work_start if calendar else "09:00") or "09:00"
    due_time = (plan.due_time or (calendar.work_end if calendar else "18:00") or "18:00")[:5]
    planned_start = parse_local_to_utc(f"{run_date.isoformat()}T{start_time}", timezone)
    planned_end = parse_local_to_utc(f"{run_date.isoformat()}T{due_time}", timezone)
    sla_date = run_date + timedelta(days=max(0, int(plan.grace_days or 0)))
    sla_due = parse_local_to_utc(f"{sla_date.isoformat()}T{due_time}", timezone)
    # Defensive fallback; should not be reached for valid HH:MM values.
    planned_start = planned_start or datetime.combine(run_date, datetime.min.time()) + timedelta(hours=9)
    planned_end = planned_end or datetime.combine(run_date, datetime.min.time()) + timedelta(hours=18)
    sla_due = sla_due or planned_end + timedelta(days=max(0, int(plan.grace_days or 0)))
    return planned_start, planned_end, sla_due, calendar


def maintenance_notification_targets(db: Session, plan: MaintenancePlan) -> list[User]:
    ids: set[int] = set()
    eq = plan.equipment
    if plan.notify_assignee and plan.assignee_id:
        ids.add(plan.assignee_id)
    if plan.notify_owner and eq and eq.owner_user_id:
        ids.add(eq.owner_user_id)
    if plan.notify_dispatchers:
        ids.update(
            row.id
            for row in db.query(User)
            .filter(User.active == True, User.role.in_(["dispatcher", "manager", "admin"]))
            .all()
        )
    if not ids:
        return []
    return db.query(User).filter(User.id.in_(ids), User.active == True).order_by(User.full_name).all()


def _notify_occurrence(db: Session, plan: MaintenancePlan, run_date: date, stage: str, ticket: Ticket | None) -> int:
    targets = maintenance_notification_targets(db, plan)
    if not targets:
        return 0
    eq = plan.equipment
    stage_titles = {
        "created": "Создано плановое ТО",
        "first": "Напоминание о плановом ТО",
        "repeat": "Плановое ТО приближается",
        "overdue": "Просрочено плановое ТО",
    }
    title = stage_titles.get(stage, "Плановое ТО")
    if stage == "overdue":
        body = f"{plan.name} · {eq.name} · {eq.site.name}. Плановая дата: {run_date.strftime('%d.%m.%Y')}. Требуется завершить работу."
    else:
        body = f"{plan.name} · {eq.name} · {eq.site.name}. Плановая дата: {run_date.strftime('%d.%m.%Y')}."
    link = f"/tickets/{ticket.id}" if ticket else f"/maintenance#plan-{plan.id}"
    count = 0
    for user in targets:
        row = notify_user(
            db,
            user,
            title,
            body,
            link,
            level="warning" if stage in {"repeat", "overdue"} else "info",
            dedup_key=f"maintenance:{plan.id}:{run_date.isoformat()}:{stage}:{user.id}",
        )
        if row:
            count += 1
    return count


def process_due_maintenance_notifications(db: Session, today: date | None = None) -> int:
    today = today or date.today()
    sent = 0
    plans = db.query(MaintenancePlan).filter(MaintenancePlan.active == True).all()
    for plan in plans:
        run_date = plan.next_run
        ticket = _ticket_for_occurrence(db, plan, run_date)
        if not ticket:
            continue
        if ticket.status in {"resolved", "closed", "cancelled"}:
            continue
        days_left = (run_date - today).days
        first_days=max(0, int(plan.notify_before_days or 0))
        repeat_days=max(0, int(plan.repeat_notify_before_days or 0))
        create_days=max(0, int(plan.create_before_days or 0))
        # Do not send two identical reminders at the exact moment the request is created.
        if 0 <= days_left <= first_days and not (days_left == create_days and first_days == create_days):
            sent += _notify_occurrence(db, plan, run_date, "first", ticket)
        if 0 <= days_left <= repeat_days and repeat_days < first_days and not (days_left == create_days and repeat_days == create_days):
            sent += _notify_occurrence(db, plan, run_date, "repeat", ticket)
        overdue_from = run_date + timedelta(days=max(0, int(plan.grace_days or 0)))
        if today > overdue_from:
            sent += _notify_occurrence(db, plan, run_date, "overdue", ticket)
    db.commit()
    return sent


def generate_due_maintenance(db: Session) -> int:
    today = date.today()
    plans = db.query(MaintenancePlan).filter(MaintenancePlan.active == True).all()
    created = 0
    created_tickets: list[Ticket] = []
    system_user = ensure_system_user(db)

    for plan in plans:
        run_date = plan.next_run
        create_on = run_date - timedelta(days=max(0, int(plan.create_before_days or 0)))
        if today < create_on:
            continue
        exists = _ticket_for_occurrence(db, plan, run_date)
        if exists:
            # If a legacy close path did not advance the plan, self-heal here.
            if exists.status in {"resolved", "closed"}:
                complete_maintenance_plan(db, exists, exists.resolved_at or datetime.utcnow())
            continue

        eq = plan.equipment
        planned_start, planned_end, sla_due, calendar = _window_utc(db, plan, run_date)
        now = datetime.utcnow()
        status = "assigned" if plan.assignee_id else "new"
        response_due = None
        if int(plan.response_sla_minutes or 0) > 0:
            response_due = (
                add_business_minutes(now, int(plan.response_sla_minutes), calendar)
                if calendar
                else now + timedelta(minutes=int(plan.response_sla_minutes))
            )

        marker = _marker(plan.id, run_date)
        ticket = Ticket(
            number=next_ticket_number(db),
            title=f"Плановое ТО: {plan.name} — {eq.name}",
            description=(
                f"Плановая работа по оборудованию {eq.inventory_no}. {marker}\n"
                f"Объект: {eq.site.name}. Плановая дата: {run_date.strftime('%d.%m.%Y')}."
            ),
            category="ППР/ТО",
            priority="normal",
            status=status,
            ticket_type="maintenance",
            site_id=eq.site_id,
            equipment_id=eq.id,
            requester_id=None,
            requester_name=eq.site.name,
            requester_phone="",
            creator_id=system_user.id,
            assignee_id=plan.assignee_id,
            master_name=(plan.assignee.full_name if plan.assignee else ""),
            maintenance_plan_id=plan.id,
            planned_start_at=planned_start,
            planned_end_at=planned_end,
            response_due_at=response_due,
            sla_due_at=sla_due,
            business_calendar_id=(calendar.id if calendar else None),
            created_at=now,
            updated_at=now,
        )
        db.add(ticket)
        db.flush()
        ensure_initial_history(db, ticket, user_id=system_user.id, source="maintenance")
        snapshot_checklist(db, plan, ticket)
        created_tickets.append(ticket)
        eq.next_maintenance_at = run_date
        _notify_occurrence(db, plan, run_date, "created", ticket)
        created += 1

    db.commit()
    process_due_maintenance_notifications(db, today=today)

    # Push generated PPR tickets to 1C after the local transaction is committed.
    try:
        from app.services.sync import push_ticket_to_1c
        for ticket in created_tickets:
            db.refresh(ticket)
            push_ticket_to_1c(db, ticket)
    except Exception as exc:
        print("maintenance 1C sync error:", exc)
    return created


def _ticket_run_date(ticket: Ticket, plan: MaintenancePlan) -> date:
    marker = re.search(r"\[ППР:\d+:(\d{4}-\d{2}-\d{2})\]", ticket.description or "")
    if marker:
        try:
            return date.fromisoformat(marker.group(1))
        except ValueError:
            pass
    if ticket.planned_start_at:
        return ticket.planned_start_at.date()
    return plan.next_run


def complete_maintenance_plan(db: Session, ticket: Ticket, when: datetime | None = None) -> bool:
    """Advance the recurring plan only after the generated maintenance ticket is completed."""
    if not ticket.maintenance_plan_id:
        return False
    plan = db.get(MaintenancePlan, ticket.maintenance_plan_id)
    if not plan:
        return False
    run_date = _ticket_run_date(ticket, plan)
    if plan.last_run == run_date:
        return False
    plan.last_run = run_date
    if plan.next_run <= run_date:
        plan.next_run = run_date + timedelta(days=max(1, int(plan.interval_days or 1)))
    if plan.equipment:
        plan.equipment.next_maintenance_at = plan.next_run
    return True
