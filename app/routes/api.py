from datetime import datetime, timedelta
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Request, Header, Body
from sqlalchemy.orm import Session
from app.db import get_db
from app.config import get_settings
from app.models import Site, Equipment, Ticket, InventoryItem, User, UiStyle, ServiceCatalog
from app.services.one_c import OneCClient, OneCError, pick
from app.services.maintenance import next_ticket_number, generate_due_maintenance
from app.services.sync import ticket_to_1c_payload, push_ticket_to_1c, upsert_ticket_from_1c
from app.labels import STATUS_LABELS, PRIORITY_LABELS, EQUIPMENT_STATUS_LABELS
from app.access import has_permission, require_permission, scope_ticket_query
from app.security import current_user
from app.services.ui_styles import upsert_ui_styles, styles_cache, display_name, badge_css, sla_hours_for
from app.services.automation import apply_ticket_rules
from app.services.ticket_lifecycle import ensure_initial_history
from app.services.sla_calendar import apply_service_sla
from app.services.webhooks import enqueue_ticket_event
from app.services.itsm import TICKET_TYPES

router = APIRouter(prefix="/api", tags=["api"])
settings = get_settings()

def _auth(request: Request, db: Session):
    user=current_user(request,db)
    if not user:
        raise HTTPException(401, "Требуется авторизация")
    return user

@router.get("/health")
def health():
    return {
        "ok": True, "service": settings.app_name, "version": settings.app_version,
        "mode": "standalone", "developer": settings.developer_name,
        "telegram": settings.developer_telegram
    }

@router.get("/sites")
def sites(request: Request, db: Session = Depends(get_db)):
    user=_auth(request, db)
    require_permission(user,"site.view","Недостаточно прав для просмотра объектов через API")
    return [{"id": x.id, "name": x.name, "address": x.address, "one_c_id": x.one_c_id} for x in db.query(Site).order_by(Site.name).all()]

@router.get("/equipment")
def equipment(request: Request, db: Session = Depends(get_db)):
    user=_auth(request, db)
    require_permission(user,"equipment.view","Недостаточно прав для просмотра оборудования через API")
    rows = db.query(Equipment).order_by(Equipment.name).all()
    ui=styles_cache(db)
    return [{"id":x.id,"name":x.name,"inventory_no":x.inventory_no,"site":x.site.name,"status":x.status,
             "status_name":display_name(ui,"equipment_status",x.status,EQUIPMENT_STATUS_LABELS.get(x.status,x.status)),
             "status_style":ui.get("equipment_status",{}).get(x.status,{}),"one_c_id":x.one_c_id} for x in rows]

@router.get("/tickets")
def tickets(request: Request, db: Session = Depends(get_db)):
    user=_auth(request, db)
    if not (has_permission(user,"ticket.list") or has_permission(user,"ticket.list_all")):
        raise HTTPException(403,"Недостаточно прав")
    rows = scope_ticket_query(db.query(Ticket),user).order_by(Ticket.id.desc()).limit(500).all()
    ui=styles_cache(db)
    return [{"id":x.id,"number":x.number,"title":x.title,"ticket_type":x.ticket_type,"status":x.status,
             "status_name":display_name(ui,"status",x.status,STATUS_LABELS.get(x.status,x.status)),
             "status_style":ui.get("status",{}).get(x.status,{}),
             "priority":x.priority,"priority_name":display_name(ui,"priority",x.priority,PRIORITY_LABELS.get(x.priority,x.priority)),
             "priority_style":ui.get("priority",{}).get(x.priority,{}),
             "category":x.category,"category_name":display_name(ui,"category",x.category,x.category),
             "category_style":ui.get("category",{}).get(x.category,{}),
             "site":x.site.name,"equipment":x.equipment.name if x.equipment else None,
             "created_at":x.created_at.isoformat(),"sla_due_at":x.sla_due_at.isoformat() if x.sla_due_at else None,"response_due_at":x.response_due_at.isoformat() if x.response_due_at else None,"first_response_at":x.first_response_at.isoformat() if x.first_response_at else None,
             "web_id":x.web_uid,"requester_name":x.requester_name,"phone":x.requester_phone,"room":x.room,"master":x.master_name,
             "labor_cost":float(x.labor_cost or 0),"parts_cost":float(x.parts_cost or 0),"one_c_id":x.one_c_id,
             "onec_synced_at":x.onec_synced_at.isoformat() if x.onec_synced_at else None,
             "onec_sync_error":x.onec_sync_error} for x in rows]

@router.get("/ui/styles")
def ui_styles(request: Request, db: Session = Depends(get_db)):
    _auth(request, db)
    cache = styles_cache(db)
    return {"source":"local-core", "styles":cache}

@router.post("/tickets")
def create_ticket(payload: dict, request: Request, db: Session = Depends(get_db)):
    user = _auth(request, db)
    require_permission(user,"ticket.create","Недостаточно прав для создания заявки")
    site = db.get(Site, int(payload.get("site_id", 0)))
    if not site: raise HTTPException(400, "Не найден объект")
    eq_id=int(payload["equipment_id"]) if payload.get("equipment_id") else None
    if eq_id:
        eq=db.get(Equipment,eq_id)
        if not eq or eq.site_id!=site.id: raise HTTPException(400,"Оборудование не относится к выбранному объекту")
    service=db.get(ServiceCatalog,int(payload.get("service_id"))) if payload.get("service_id") else None
    priority = (service.default_priority if service and service.default_priority else (str(payload.get("priority", "normal")) if has_permission(user,"ticket.set_priority") else "normal"))
    assignee_id=None
    if payload.get("assignee_id") and has_permission(user,"ticket.assign"):
        candidate=db.get(User,int(payload["assignee_id"]))
        if not candidate or not candidate.active or candidate.role!="technician": raise HTTPException(400,"Исполнителем может быть только активный техник")
        assignee_id=candidate.id
    sla_hours = sla_hours_for(db, priority)
    ticket_type=str(payload.get("ticket_type") or "incident")
    if ticket_type not in TICKET_TYPES: ticket_type="incident"
    if ticket_type=="maintenance": ticket_type="request"  # system-only type
    if not has_permission(user,"itsm.view") and ticket_type not in {"incident","request"}: ticket_type="request"
    t = Ticket(number=next_ticket_number(db), title=str(payload.get("title") or "Без названия"),
               description=str(payload.get("description") or ""), category=str(payload.get("category") or "Другое"),
               priority=priority, status="assigned" if assignee_id else "new", site_id=site.id,
               equipment_id=eq_id, requester_id=user.id, creator_id=user.id, requester_name=user.full_name,
               requester_phone=str(payload.get("phone") or ""), room=str(payload.get("room") or ""),
               assignee_id=assignee_id, master_name=(candidate.full_name if assignee_id else ""), service_id=(service.id if service else None),ticket_type=ticket_type)
    apply_service_sla(db,t,service,fallback_resolution_minutes=sla_hours*60)
    db.add(t); db.flush(); apply_ticket_rules(db,t); ensure_initial_history(db,t,user_id=user.id,source="api"); enqueue_ticket_event(db,"ticket.created",t); db.commit(); db.refresh(t)
    push_ticket_to_1c(db, t)
    return {"id": t.id, "number": t.number, "one_c_id": t.one_c_id}

@router.post("/maintenance/generate")
def maintenance_generate(request: Request, db: Session = Depends(get_db)):
    user=_auth(request, db)
    require_permission(user,"maintenance.manage","Недостаточно прав для генерации ППР")
    return {"created": generate_due_maintenance(db)}

# ---------- 1C -> TOIR. This endpoint intentionally does NOT use a browser session. ----------
@router.post("/1c/webhook/tickets")
def onec_webhook_ticket(payload: dict, x_toir_token: str | None = Header(default=None, alias="X-TOIR-TOKEN"), db: Session = Depends(get_db)):
    if not settings.onec_enabled:
        raise HTTPException(404, "Коннектор 1С выключен")
    if not settings.onec_webhook_token or x_toir_token != settings.onec_webhook_token:
        raise HTTPException(401, "Неверный X-TOIR-TOKEN")
    t = upsert_ticket_from_1c(db, payload)
    return {"ok": True, "id": t.id, "number": t.number, "one_c_id": t.one_c_id}

@router.post("/1c/webhook/ui")
def onec_webhook_ui(payload: object = Body(...), x_toir_token: str | None = Header(default=None, alias="X-TOIR-TOKEN"), db: Session = Depends(get_db)):
    if not settings.onec_enabled:
        raise HTTPException(404, "Коннектор 1С выключен")
    if not settings.onec_webhook_token or x_toir_token != settings.onec_webhook_token:
        raise HTTPException(401, "Неверный X-TOIR-TOKEN")
    try:
        count = upsert_ui_styles(db, payload, full_replace=False)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "processed": count}

@router.get("/integration/1c/status")
def onec_status(request: Request, db: Session = Depends(get_db)):
    user=_auth(request, db); require_permission(user,"integration.manage","Доступ к интеграциям только администратору")
    return OneCClient().health()

@router.post("/integration/1c/pull/ui")
def onec_pull_ui(request: Request, db: Session = Depends(get_db)):
    user=_auth(request, db); require_permission(user,"integration.manage","Доступ к интеграциям только администратору"); client = OneCClient()
    try:
        rows = client.get_items(client.s.onec_ui_path)
        count = upsert_ui_styles(db, rows, full_replace=False)
    except (OneCError, ValueError) as e:
        raise HTTPException(502, str(e))
    return {"ok": True, "processed": count}

@router.post("/integration/1c/pull/sites")
def onec_pull_sites(request: Request, db: Session = Depends(get_db)):
    user=_auth(request, db); require_permission(user,"integration.manage","Доступ к интеграциям только администратору"); client = OneCClient()
    try: rows = client.get_items(client.s.onec_sites_path)
    except OneCError as e: raise HTTPException(502, str(e))
    count = 0
    for r in rows:
        ext = str(pick(r,"id","Ref_Key","Ссылка","guid",default="") or "")
        name = str(pick(r,"name","Description","Наименование",default="") or "").strip()
        if not name: continue
        obj = db.query(Site).filter(Site.one_c_id == ext).first() if ext else None
        if not obj: obj = db.query(Site).filter(Site.name == name).first()
        if not obj: obj = Site(name=name); db.add(obj)
        obj.one_c_id = ext or obj.one_c_id
        obj.address = str(pick(r,"address","Адрес",default=obj.address or "") or "")
        count += 1
    db.commit(); return {"ok":True,"processed":count}

@router.post("/integration/1c/pull/equipment")
def onec_pull_equipment(request: Request, db: Session = Depends(get_db)):
    user=_auth(request, db); require_permission(user,"integration.manage","Доступ к интеграциям только администратору"); client = OneCClient()
    try: rows = client.get_items(client.s.onec_equipment_path)
    except OneCError as e: raise HTTPException(502, str(e))
    count=0; skipped=0
    import secrets
    for r in rows:
        ext=str(pick(r,"id","Ref_Key","Ссылка","guid",default="") or "")
        inv=str(pick(r,"inventory_no","ИнвентарныйНомер","Код",default="") or "").strip()
        name=str(pick(r,"name","Description","Наименование",default="") or "").strip()
        site_ext=str(pick(r,"site_id","Объект_Key","Подразделение_Key",default="") or "")
        site_name=str(pick(r,"site_name","Объект","Подразделение",default="") or "").strip()
        site = db.query(Site).filter(Site.one_c_id==site_ext).first() if site_ext else None
        if not site and site_name: site=db.query(Site).filter(Site.name==site_name).first()
        if not site or not name: skipped+=1; continue
        if not inv: inv = f"1C-{ext[:8] or secrets.token_hex(4)}"
        obj = db.query(Equipment).filter(Equipment.one_c_id==ext).first() if ext else None
        if not obj: obj=db.query(Equipment).filter(Equipment.inventory_no==inv).first()
        if not obj:
            obj=Equipment(site_id=site.id,name=name,inventory_no=inv,qr_token=secrets.token_urlsafe(24)); db.add(obj)
        obj.site_id=site.id; obj.name=name; obj.one_c_id=ext or obj.one_c_id
        obj.category=str(pick(r,"category","Категория",default=obj.category) or obj.category)
        obj.model=str(pick(r,"model","Модель",default=obj.model) or obj.model)
        obj.serial_no=str(pick(r,"serial_no","СерийныйНомер",default=obj.serial_no) or obj.serial_no)
        count+=1
    db.commit(); return {"ok":True,"processed":count,"skipped":skipped}

@router.post("/integration/1c/pull/inventory")
def onec_pull_inventory(request: Request, db: Session = Depends(get_db)):
    user=_auth(request, db); require_permission(user,"integration.manage","Доступ к интеграциям только администратору"); client=OneCClient()
    try: rows=client.get_items(client.s.onec_inventory_path)
    except OneCError as e: raise HTTPException(502, str(e))
    count=0
    for r in rows:
        ext=str(pick(r,"id","Ref_Key","Ссылка","guid",default="") or "")
        sku=str(pick(r,"sku","Code","Код","Артикул",default="") or "").strip()
        name=str(pick(r,"name","Description","Наименование",default="") or "").strip()
        if not name: continue
        if not sku: sku=f"1C-{ext[:8]}"
        obj=db.query(InventoryItem).filter(InventoryItem.one_c_id==ext).first() if ext else None
        if not obj: obj=db.query(InventoryItem).filter(InventoryItem.sku==sku).first()
        if not obj: obj=InventoryItem(sku=sku,name=name); db.add(obj)
        obj.one_c_id=ext or obj.one_c_id; obj.name=name
        try: obj.qty=float(pick(r,"qty","Количество","Остаток",default=obj.qty) or 0)
        except Exception: pass
        obj.unit=str(pick(r,"unit","ЕдиницаИзмерения","ЕдИзм",default=obj.unit) or obj.unit)
        try: obj.unit_cost=Decimal(str(pick(r,"unit_cost","price","Цена","Стоимость",default=obj.unit_cost) or 0))
        except Exception: pass
        count+=1
    db.commit(); return {"ok":True,"processed":count}

@router.post("/integration/1c/pull/tickets")
def onec_pull_tickets(request: Request, db: Session = Depends(get_db)):
    user=_auth(request, db); require_permission(user,"integration.manage","Доступ к интеграциям только администратору"); client=OneCClient()
    try: rows=client.get_items(client.s.onec_tickets_path)
    except OneCError as e: raise HTTPException(502, str(e))
    count=0
    for row in rows:
        upsert_ticket_from_1c(db, row); count += 1
    return {"ok": True, "processed": count}

@router.post("/integration/1c/push/tickets/{ticket_id}")
def onec_push_ticket(ticket_id:int, request: Request, db: Session = Depends(get_db)):
    user=_auth(request, db); require_permission(user,"integration.manage","Доступ к интеграциям только администратору"); t=db.get(Ticket,ticket_id)
    if not t: raise HTTPException(404,"Заявка не найдена")
    try:
        result = push_ticket_to_1c(db, t, raise_errors=True, force=True)
    except OneCError as e:
        raise HTTPException(502,str(e))
    except Exception as e:
        raise HTTPException(502,str(e))
    return result
