from __future__ import annotations
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from sqlalchemy.orm import Session
from app.models import Ticket, Site, User
from app.services.one_c import (
    OneCClient, OneCError, pick, status_to_1c, status_from_1c,
    priority_to_1c, priority_from_1c, category_to_1c, parse_1c_datetime,
)
from app.services.maintenance import next_ticket_number
from app.services.ui_styles import sla_hours_for


def ticket_to_1c_payload(t: Ticket) -> dict:
    if not t.web_uid:
        t.web_uid = str(uuid.uuid4())
    requester = t.requester_name or (t.requester.full_name if t.requester else "")
    master = t.master_name or (t.assignee.full_name if t.assignee else "")
    return {
        "id": t.one_c_id,
        "web_id": t.web_uid,
        "number": t.number,
        "date": t.created_at.isoformat() if t.created_at else None,
        "requester": requester,
        "department_id": t.site.one_c_id if t.site else None,
        "department": t.site.name if t.site else "",
        "room": t.room or "",
        "phone": t.requester_phone or "",
        "category": category_to_1c(t.category),
        "priority": priority_to_1c(t.priority),
        "description": t.description or t.title or "",
        "title": t.title or "",
        "master": master,
        "status": status_to_1c(t.status),
        "resolved_at": t.resolved_at.isoformat() if t.resolved_at else None,
        "master_comment": t.master_comment or "",
        "equipment_id": t.equipment.one_c_id if t.equipment else None,
        "equipment_inventory_no": t.equipment.inventory_no if t.equipment else None,
        "labor_cost": float(t.labor_cost or 0),
        "parts_cost": float(t.parts_cost or 0),
        "web_url": f"/tickets/{t.id}",
    }


def push_ticket_to_1c(db: Session, t: Ticket, *, raise_errors: bool = False, force: bool = False) -> dict:
    client = OneCClient()
    if not client.enabled():
        return {"ok": False, "skipped": True, "message": "Интеграция с 1С выключена"}
    if not force and not client.s.onec_auto_push:
        return {"ok": False, "skipped": True, "message": "Автообмен с 1С выключен"}
    try:
        result = client.post_json(client.s.onec_tickets_path, ticket_to_1c_payload(t))
        external_id = result.get("id") or result.get("Ref_Key") or result.get("guid") or result.get("GUID")
        if external_id:
            t.one_c_id = str(external_id)
        t.onec_sync_error = ""
        t.onec_synced_at = datetime.utcnow()
        db.commit()
        return {"ok": True, "result": result}
    except Exception as exc:
        t.onec_sync_error = str(exc)[:2000]
        db.commit()
        if raise_errors:
            raise
        return {"ok": False, "message": str(exc)}


def _find_or_create_site(db: Session, ext_id: str, name: str) -> Site:
    site = db.query(Site).filter(Site.one_c_id == ext_id).first() if ext_id else None
    if not site and name:
        site = db.query(Site).filter(Site.name == name).first()
    if not site:
        site = Site(name=name or "Без подразделения", one_c_id=ext_id or None)
        db.add(site); db.flush()
    elif ext_id and not site.one_c_id:
        site.one_c_id = ext_id
    return site


def upsert_ticket_from_1c(db: Session, row: dict) -> Ticket:
    ext = str(pick(row, "id", "guid", "GUID", "Ref_Key", "Ссылка", default="") or "").strip()
    web_id = str(pick(row, "web_id", "WebID", default="") or "").strip()
    number = str(pick(row, "number", "Номер", "НомерЗаявки", default="") or "").strip()
    department_id = str(pick(row, "department_id", "Подразделение_Key", "ПодразделениеID", default="") or "").strip()
    department = str(pick(row, "department", "Подразделение", "site_name", default="") or "").strip()
    site = _find_or_create_site(db, department_id, department)

    t = db.query(Ticket).filter(Ticket.web_uid == web_id).first() if web_id else None
    if not t and ext:
        t = db.query(Ticket).filter(Ticket.one_c_id == ext).first()
    if not t and number:
        t = db.query(Ticket).filter(Ticket.number == number).first()
    created = False
    if not t:
        t = Ticket(number=number or next_ticket_number(db), title="Заявка из 1С", site_id=site.id)
        db.add(t); db.flush(); created = True

    t.site_id = site.id
    if ext: t.one_c_id = ext
    if web_id: t.web_uid = web_id
    elif not t.web_uid: t.web_uid = str(uuid.uuid4())
    if number and (created or t.number.startswith("TOIR-")): t.number = number
    description = str(pick(row, "description", "Описание", default=t.description or "") or "")
    title = str(pick(row, "title", "Заголовок", default="") or "").strip()
    t.title = title or (description.splitlines()[0][:220] if description else t.title or "Заявка из 1С")
    t.description = description
    t.category = str(pick(row, "category", "Категория", default=t.category or "Другое") or "Другое")
    t.priority = priority_from_1c(pick(row, "priority", "Приоритет", default="Обычный"))
    t.status = status_from_1c(pick(row, "status", "Статус", default="Новая"))
    t.requester_name = str(pick(row, "requester", "Заявитель", default=t.requester_name or "") or "")
    t.requester_phone = str(pick(row, "phone", "Телефон", default=t.requester_phone or "") or "")
    t.room = str(pick(row, "room", "Кабинет", default=t.room or "") or "")
    t.master_name = str(pick(row, "master", "Мастер", default=t.master_name or "") or "")
    t.master_comment = str(pick(row, "master_comment", "КомментарийМастера", default=t.master_comment or "") or "")
    created_at = parse_1c_datetime(pick(row, "date", "Дата", "created_at", default=None))
    if created_at: t.created_at = created_at
    resolved = parse_1c_datetime(pick(row, "resolved_at", "ДатаВыполнения", default=None))
    if resolved: t.resolved_at = resolved
    try: t.labor_cost = Decimal(str(pick(row, "labor_cost", "СтоимостьРабот", default=t.labor_cost or 0) or 0))
    except Exception: pass
    try: t.parts_cost = Decimal(str(pick(row, "parts_cost", "СтоимостьМатериалов", default=t.parts_cost or 0) or 0))
    except Exception: pass

    # Try to link an existing web user/technician by name without forcing a 1C catalog change.
    if t.requester_name:
        u = db.query(User).filter(User.full_name == t.requester_name).first()
        if u: t.requester_id = u.id
    if t.master_name:
        u = db.query(User).filter(User.full_name == t.master_name).first()
        if u: t.assignee_id = u.id

    if not t.sla_due_at:
        hours = sla_hours_for(db, t.priority)
        t.sla_due_at = t.created_at + timedelta(hours=hours)
    t.onec_sync_error = ""
    t.onec_synced_at = datetime.utcnow()
    db.commit(); db.refresh(t)
    return t
