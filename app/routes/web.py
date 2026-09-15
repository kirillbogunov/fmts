from __future__ import annotations
import csv, io, json, os, secrets
from datetime import datetime, date, timedelta
from pathlib import Path
from decimal import Decimal
from fastapi import APIRouter, Depends, Request, Form, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse, Response, FileResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session
import qrcode
from io import BytesIO
from app.db import get_db
from app.config import get_settings
from app.models import User, Site, Equipment, Ticket, TicketComment, Attachment, MaintenancePlan, InventoryItem, StockMovement, Contractor, UiStyle, TicketWorkSession, AuditLog
from app.security import verify_password, current_user, hash_password
from app.services.maintenance import next_ticket_number, generate_due_maintenance
from app.services.one_c import OneCClient
from app.services.sync import push_ticket_to_1c
from app.labels import STATUS_LABELS, PRIORITY_LABELS, ROLE_LABELS, EQUIPMENT_STATUS_LABELS
from app.services.ui_styles import styles_cache, badge_css, display_name, options_for, sla_hours_for
from app.services.reference_data import ensure_default_reference_data
from app.services.urls import public_url
from app.services.kpi import calculate_monthly_kpi, parse_period, shift_month
from app.services.time_tracking import ticket_time_summary, ticket_time_totals, format_duration, start_work, stop_work, close_active_for_ticket, can_track_time
from app.access import has_permission, scope_ticket_query, can_view_ticket, can_comment_ticket, can_issue_stock, can_track_ticket_time, allowed_statuses, can_change_ticket_status, visible_navigation, role_summary
from app.services.audit import audit

router=APIRouter()
templates=Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))
settings=get_settings()

def user_or_login(request:Request, db:Session):
    return current_user(request,db)

def ctx(request, db, **extra):
    u=current_user(request,db)
    ui=styles_cache(db)
    base={"request":request,"user":u,"app_name":settings.app_name,"now":datetime.now(),
          "status_labels":STATUS_LABELS,"priority_labels":PRIORITY_LABELS,
          "role_labels":ROLE_LABELS,"equipment_status_labels":EQUIPMENT_STATUS_LABELS,
          "ui_styles":ui,"settings":settings,
          "app_version":settings.app_version,"developer_name":settings.developer_name,
          "developer_telegram":settings.developer_telegram,"developer_url":settings.developer_url,
          "badge_style":lambda kind,code: badge_css(ui,kind,code),
          "ui_name":lambda kind,code,fallback=None: display_name(ui,kind,code,fallback),
          "format_duration":format_duration,
          "can":lambda permission: bool(u and has_permission(u,permission)),
          "nav":visible_navigation(u),
          "role_summary":role_summary}
    base.update(extra); return base


def forbidden(request:Request, db:Session, user:User|None, permission:str, message:str="Недостаточно прав для выполнения этого действия"):
    # Never let a denied request accidentally commit earlier in-memory changes.
    db.rollback()
    audit(db,request,user,"access.denied",entity_type="permission",entity_id=permission,result="denied",details=message)
    return templates.TemplateResponse("forbidden.html",ctx(request,db,permission=permission,message=message),status_code=403)

def require_web_permission(request:Request, db:Session, user:User|None, permission:str):
    if not user:
        return RedirectResponse("/login",303)
    if not has_permission(user,permission):
        return forbidden(request,db,user,permission)
    return None

@router.get("/login", response_class=HTMLResponse)
def login_page(request:Request, next:str="", db:Session=Depends(get_db)):
    if current_user(request,db): return RedirectResponse(next if next.startswith("/") and not next.startswith("//") else "/",303)
    return templates.TemplateResponse("login.html",ctx(request,db,error=None,next_url=next))

@router.post("/login")
def login(request:Request, username:str=Form(...), password:str=Form(...), next_url:str=Form(""), db:Session=Depends(get_db)):
    u=db.query(User).filter(User.username==username,User.active==True).first()
    if not u or not verify_password(password,u.password_hash):
        audit(db,request,u,"auth.login",entity_type="user",entity_id=(u.id if u else username),result="denied",details=f"username={username}")
        return templates.TemplateResponse("login.html",ctx(request,db,error="Неверный логин или пароль",next_url=next_url),status_code=401)
    request.session["user_id"]=u.id
    audit(db,request,u,"auth.login",entity_type="user",entity_id=u.id,details="Вход выполнен")
    target=next_url if next_url.startswith("/") and not next_url.startswith("//") else "/"
    return RedirectResponse(target,303)

@router.get("/logout")
def logout(request:Request,db:Session=Depends(get_db)):
    u=current_user(request,db)
    if u: audit(db,request,u,"auth.logout",entity_type="user",entity_id=u.id,details="Выход выполнен")
    request.session.clear(); return RedirectResponse("/login",303)

@router.get("/profile", response_class=HTMLResponse)
def profile(request:Request,db:Session=Depends(get_db)):
    if not user_or_login(request,db): return RedirectResponse("/login",303)
    return templates.TemplateResponse("profile.html",ctx(request,db,message=None,ok=True))

@router.get("/about", response_class=HTMLResponse)
def about(request:Request, db:Session=Depends(get_db)):
    if not user_or_login(request,db): return RedirectResponse("/login",303)
    return templates.TemplateResponse("about.html",ctx(request,db))

@router.post("/profile/password", response_class=HTMLResponse)
def profile_password(request:Request,current_password:str=Form(...),new_password:str=Form(...),db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    if not verify_password(current_password,u.password_hash):
        return templates.TemplateResponse("profile.html",ctx(request,db,message="Текущий пароль указан неверно",ok=False),status_code=400)
    if len(new_password) < 10:
        return templates.TemplateResponse("profile.html",ctx(request,db,message="Новый пароль должен содержать не менее 10 символов",ok=False),status_code=400)
    u.password_hash=hash_password(new_password); db.commit()
    audit(db,request,u,"auth.password_change",entity_type="user",entity_id=u.id,details="Пользователь изменил свой пароль")
    return templates.TemplateResponse("profile.html",ctx(request,db,message="Пароль изменён",ok=True))

@router.get("/", response_class=HTMLResponse)
def dashboard(request:Request, db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    now=datetime.utcnow()
    open_status=["new","assigned","in_progress","waiting"]
    tq=scope_ticket_query(db.query(Ticket),u)
    recent=tq.order_by(Ticket.id.desc()).limit(8).all()
    by_status=tq.with_entities(Ticket.status,func.count(Ticket.id)).group_by(Ticket.status).all()
    equipment_count=db.query(Equipment).count() if has_permission(u,"equipment.view") else None
    if has_permission(u,"maintenance.view_all"):
        due_maintenance=db.query(MaintenancePlan).filter(MaintenancePlan.active==True,MaintenancePlan.next_run<=date.today()+timedelta(days=7)).count()
    elif has_permission(u,"maintenance.view_assigned"):
        due_maintenance=db.query(MaintenancePlan).filter(MaintenancePlan.assignee_id==u.id,MaintenancePlan.active==True,MaintenancePlan.next_run<=date.today()+timedelta(days=7)).count()
    else:
        due_maintenance=None
    low_stock=db.query(InventoryItem).filter(InventoryItem.qty<=InventoryItem.min_qty).count() if has_permission(u,"inventory.view") else None
    data={
        "open_count":tq.filter(Ticket.status.in_(open_status)).count(),
        "overdue":tq.filter(Ticket.status.in_(open_status),Ticket.sla_due_at < now).count(),
        "equipment_count":equipment_count,
        "due_maintenance":due_maintenance,
        "low_stock":low_stock,
        "recent":recent,
        "by_status":by_status,
    }
    return templates.TemplateResponse("dashboard.html",ctx(request,db,**data))

@router.get("/reports/kpi", response_class=HTMLResponse)
def kpi_report(request:Request, month:str="", db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    if not (has_permission(u,"kpi.all") or has_permission(u,"kpi.self")):
        return forbidden(request,db,u,"kpi.self")
    period=parse_period(month)
    technician_ids=None if has_permission(u,"kpi.all") else [u.id]
    report=calculate_monthly_kpi(
        db, period,
        target_points=settings.kpi_monthly_target_points,
        weight_sla=settings.kpi_weight_sla,
        weight_closure=settings.kpi_weight_closure,
        weight_productivity=settings.kpi_weight_productivity,
        weight_documentation=settings.kpi_weight_documentation,
        technician_ids=technician_ids,
    )
    return templates.TemplateResponse("reports_kpi.html",ctx(
        request,db,report=report,period=period,
        prev_month=shift_month(period,-1),next_month=shift_month(period,1),
    ))

@router.get("/reports/kpi.csv")
def kpi_report_csv(request:Request, month:str="", db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    if not (has_permission(u,"kpi.all") or has_permission(u,"kpi.self")):
        return forbidden(request,db,u,"kpi.self")
    period=parse_period(month)
    technician_ids=None if has_permission(u,"kpi.all") else [u.id]
    report=calculate_monthly_kpi(
        db, period,
        target_points=settings.kpi_monthly_target_points,
        weight_sla=settings.kpi_weight_sla,
        weight_closure=settings.kpi_weight_closure,
        weight_productivity=settings.kpi_weight_productivity,
        weight_documentation=settings.kpi_weight_documentation,
        technician_ids=technician_ids,
    )
    out=io.StringIO()
    writer=csv.writer(out,delimiter=';',lineterminator='\n')
    writer.writerow([
        "Место","Ремонтник","KPI, %","Рейтинг / 5","Заявок в работе за период",
        "Выполнено","Баллы работ","SLA вовремя, %","Закрытие, %",
        "Производительность, %","Документирование, %","Среднее время ремонта, ч",
        "Фактическое время работ, ч","Сеансов работы","Просрочено при выполнении","Открытый хвост сейчас","Просрочено сейчас"
    ])
    for row in report["rows"]:
        writer.writerow([
            row["rank"] or "",row["name"],str(row["score"]).replace('.',','),str(row["rating"]).replace('.',','),
            row["handled"],row["completed"],str(row["points"]).replace('.',','),str(row["sla_rate"]).replace('.',','),
            str(row["closure_rate"]).replace('.',','),str(row["productivity_rate"]).replace('.',','),
            str(row["documentation_rate"]).replace('.',','),str(row["avg_resolution_hours"]).replace('.',','),
            str(row["tracked_hours"]).replace('.',','),row["work_sessions"],
            row["overdue_completed"],row["open_backlog"],row["overdue_open"],
        ])
    payload=('\ufeff'+out.getvalue()).encode('utf-8')
    headers={"Content-Disposition": f'attachment; filename="FMTS_KPI_{period.value}.csv"'}
    return Response(content=payload,media_type="text/csv; charset=utf-8",headers=headers)

@router.get("/tickets", response_class=HTMLResponse)
def tickets(request:Request,status:str="",q:str="",db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    if not has_permission(u,"ticket.list") and not has_permission(u,"ticket.list_all"):
        return forbidden(request,db,u,"ticket.list")
    query=scope_ticket_query(db.query(Ticket),u)
    if status: query=query.filter(Ticket.status==status)
    if q: query=query.filter((Ticket.title.contains(q)) | (Ticket.number.contains(q)))
    rows=query.order_by(Ticket.id.desc()).all()
    time_totals=ticket_time_totals(db,[x.id for x in rows])
    return templates.TemplateResponse("tickets.html",ctx(request,db,tickets=rows,time_totals=time_totals,status=status,q=q,status_options=options_for(db,"status",list(STATUS_LABELS.items()))))

@router.get("/tickets/new", response_class=HTMLResponse)
def ticket_new(request:Request,equipment_id:int|None=None,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    if not has_permission(u,"ticket.create"):
        return forbidden(request,db,u,"ticket.create")
    technicians=db.query(User).filter(User.role=="technician",User.active==True).order_by(User.full_name).all() if has_permission(u,"ticket.assign") else []
    return templates.TemplateResponse("ticket_form.html",ctx(request,db,sites=db.query(Site).order_by(Site.name).all(),equipment=db.query(Equipment).order_by(Equipment.name).all(),users=technicians,selected_equipment_id=equipment_id,categories=options_for(db,"category",[(x,x) for x in ["Электрика","Сантехника","Мебель","Отделка","Кондиционер","Окна","Двери","Компьютер","Другое"]]),priority_options=options_for(db,"priority",list(PRIORITY_LABELS.items()))))

@router.post("/tickets/new")
def ticket_create(request:Request,title:str=Form(...),description:str=Form(""),category:str=Form("Другое"),priority:str=Form("normal"),site_id:int=Form(...),equipment_id:str=Form(""),assignee_id:str=Form(""),room:str=Form(""),phone:str=Form(""),attachment:UploadFile|None=File(None),db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    if not has_permission(u,"ticket.create"):
        return forbidden(request,db,u,"ticket.create")
    site=db.get(Site,site_id)
    if not site: return templates.TemplateResponse("forbidden.html",ctx(request,db,permission="ticket.create",message="Выбранный объект не существует"),status_code=400)
    eq_id=int(equipment_id) if equipment_id else None
    if eq_id:
        eq=db.get(Equipment,eq_id)
        if not eq or eq.site_id != site_id:
            return templates.TemplateResponse("forbidden.html",ctx(request,db,permission="ticket.create",message="Оборудование не относится к выбранному объекту"),status_code=400)
    # Заявитель/техник не могут самовольно повышать приоритет или назначать исполнителя.
    effective_priority=priority if has_permission(u,"ticket.set_priority") else "normal"
    new_assignee_id=None
    if assignee_id and has_permission(u,"ticket.assign"):
        target=db.get(User,int(assignee_id))
        if target and target.active and target.role=="technician":
            new_assignee_id=target.id
    sla_hours=sla_hours_for(db,effective_priority)
    t=Ticket(number=next_ticket_number(db),title=title,description=description,category=category,priority=effective_priority,status="assigned" if new_assignee_id else "new",site_id=site_id,
             equipment_id=eq_id,requester_id=u.id,requester_name=u.full_name,requester_phone=phone,room=room,
             assignee_id=new_assignee_id,master_name="",sla_due_at=datetime.utcnow()+timedelta(hours=sla_hours))
    if new_assignee_id:
        assigned=db.get(User,new_assignee_id); t.master_name=assigned.full_name if assigned else ""
    db.add(t); db.flush()
    if attachment and attachment.filename:
        Path(settings.upload_dir).mkdir(parents=True,exist_ok=True)
        ext=Path(attachment.filename).suffix
        stored=f"{secrets.token_hex(16)}{ext}"
        with open(Path(settings.upload_dir)/stored,"wb") as f: f.write(attachment.file.read())
        db.add(Attachment(ticket_id=t.id,filename=attachment.filename,stored_name=stored))
    db.commit(); db.refresh(t)
    audit(db,request,u,"ticket.create",entity_type="ticket",entity_id=t.id,details=f"{t.number}: {t.title}")
    push_ticket_to_1c(db,t)
    return RedirectResponse(f"/tickets/{t.id}",303)

@router.get("/tickets/{ticket_id}", response_class=HTMLResponse)
def ticket_detail(ticket_id:int,request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    t=db.get(Ticket,ticket_id)
    if not t: return RedirectResponse("/tickets",303)
    if not can_view_ticket(u,t):
        return forbidden(request,db,u,"ticket.view", "Эта заявка не входит в область доступа вашей роли")
    work_time=ticket_time_summary(db,t.id)
    active_session=next((x for x in work_time["active"] if x.user_id==u.id),None)
    allowed=allowed_statuses(u,t)
    status_options=[x for x in options_for(db,"status",list(STATUS_LABELS.items())) if x.get("code") in allowed]
    technicians=db.query(User).filter(User.role=="technician",User.active==True).order_by(User.full_name).all() if has_permission(u,"ticket.assign") else []
    return templates.TemplateResponse("ticket_detail.html",ctx(request,db,ticket=t,work_time=work_time,active_session=active_session,
        can_track=can_track_ticket_time(u,t),users=technicians,contractors=db.query(Contractor).order_by(Contractor.name).all() if has_permission(u,"contractor.view") or has_permission(u,"ticket.contractor") else [],
        inventory=db.query(InventoryItem).order_by(InventoryItem.name).all() if has_permission(u,"inventory.view") else [],status_options=status_options))

@router.post("/tickets/{ticket_id}/update")
def ticket_update(ticket_id:int,request:Request,status:str=Form(...),assignee_id:str=Form(""),contractor_id:str=Form(""),labor_cost:float=Form(0),master_comment:str=Form(""),db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    t=db.get(Ticket,ticket_id)
    if not t: return RedirectResponse("/tickets",303)
    if not can_view_ticket(u,t):
        return forbidden(request,db,u,"ticket.view")

    old_status=t.status
    old_assignee_id=t.assignee_id
    requested_assignee=int(assignee_id) if assignee_id else None
    requested_contractor=int(contractor_id) if contractor_id else None

    # Assignment itself drives the NEW -> ASSIGNED transition. This prevents
    # contradictory states such as "Новая" with an assigned technician.
    effective_status=status
    if requested_assignee is not None and old_status=="new" and status=="new":
        effective_status="assigned"
    if requested_assignee is None and requested_contractor is None and old_status=="assigned" and status=="assigned":
        effective_status="new"

    decision=can_change_ticket_status(u,t,effective_status)
    if not decision.allowed:
        return forbidden(request,db,u,"ticket.change_status",decision.reason)

    if requested_assignee != old_assignee_id:
        if not has_permission(u,"ticket.assign"):
            return forbidden(request,db,u,"ticket.assign","Назначение и переназначение исполнителя доступно только диспетчеру, руководителю или администратору")
        if requested_assignee is not None:
            target=db.get(User,requested_assignee)
            if not target or not target.active or target.role!="technician":
                return templates.TemplateResponse("forbidden.html",ctx(request,db,permission="ticket.assign",message="Исполнителем может быть только активный пользователь с ролью «Техник»"),status_code=400)
        close_active_for_ticket(db,t.id,datetime.utcnow())
        t.assignee_id=requested_assignee
        t.master_name=db.get(User,requested_assignee).full_name if requested_assignee else ""

    if requested_contractor != t.contractor_id:
        if not has_permission(u,"ticket.contractor"):
            return forbidden(request,db,u,"ticket.contractor")
        t.contractor_id=requested_contractor

    new_cost=Decimal(str(labor_cost or 0))
    if new_cost != Decimal(str(t.labor_cost or 0)):
        if not has_permission(u,"ticket.cost"):
            return forbidden(request,db,u,"ticket.cost","Стоимость работ может корректировать только руководитель или администратор")
        t.labor_cost=new_cost

    # Technician is allowed to document only his own assigned work.
    if u.role=="technician" and t.assignee_id!=u.id:
        return forbidden(request,db,u,"ticket.work_status")
    if master_comment != (t.master_comment or ""):
        if not has_permission(u,"ticket.master_comment"):
            return forbidden(request,db,u,"ticket.master_comment","Комментарий мастера может менять только назначенный техник или администратор")
        t.master_comment=master_comment

    # Hard workflow invariants: work states require an executor, completion
    # requires a repair note and recorded time for internally assigned work.
    if effective_status in {"assigned","in_progress","waiting","resolved","closed"} and t.assignee_id is None and t.contractor_id is None:
        return templates.TemplateResponse("forbidden.html",ctx(request,db,permission="ticket.workflow",message="Для этого статуса сначала назначьте техника или подрядчика"),status_code=400)
    if effective_status in {"resolved","closed"}:
        if not (t.master_comment or "").strip():
            return templates.TemplateResponse("forbidden.html",ctx(request,db,permission="ticket.workflow",message="Перед выполнением/закрытием обязателен комментарий мастера о выполненной работе"),status_code=400)
        if t.assignee_id is not None:
            tracked=ticket_time_summary(db,t.id)["total_seconds"]
            if tracked < 60:
                return templates.TemplateResponse("forbidden.html",ctx(request,db,permission="ticket.workflow",message="Перед выполнением заявки необходимо зафиксировать фактическое время работ (не менее 1 минуты)"),status_code=400)

    t.status=effective_status
    t.updated_at=datetime.utcnow()
    if effective_status in ("resolved","closed") and not t.resolved_at:
        t.resolved_at=datetime.utcnow(); close_active_for_ticket(db,t.id,t.resolved_at)
    elif effective_status == "cancelled":
        close_active_for_ticket(db,t.id,datetime.utcnow())
    elif effective_status not in ("resolved","closed") and t.resolved_at:
        t.resolved_at=None
    db.commit(); db.refresh(t)
    audit(db,request,u,"ticket.update",entity_type="ticket",entity_id=t.id,details=f"status {old_status}->{t.status}; assignee {old_assignee_id}->{t.assignee_id}")
    push_ticket_to_1c(db,t)
    return RedirectResponse(f"/tickets/{ticket_id}",303)

@router.post("/tickets/{ticket_id}/time/start")
def ticket_time_start(ticket_id:int,request:Request,note:str=Form(""),db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    t=db.get(Ticket,ticket_id)
    if not t or not can_view_ticket(u,t): return forbidden(request,db,u,"ticket.time.track")
    if not can_track_ticket_time(u,t):
        return forbidden(request,db,u,"ticket.time.track","Таймер может запускать только назначенный на заявку техник")
    try:
        entry=start_work(db,t,u,note)
        audit(db,request,u,"time.start",entity_type="ticket",entity_id=t.id,details=f"session={entry.id}")
    except ValueError as exc:
        return forbidden(request,db,u,"ticket.time.track",str(exc))
    return RedirectResponse(f"/tickets/{ticket_id}#ticket-time",303)

@router.post("/tickets/{ticket_id}/time/stop")
def ticket_time_stop(ticket_id:int,request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    t=db.get(Ticket,ticket_id)
    if not t or not can_view_ticket(u,t): return forbidden(request,db,u,"ticket.time.track")
    if u.role!="technician" or t.assignee_id!=u.id:
        return forbidden(request,db,u,"ticket.time.track","Остановить таймер может только назначенный техник")
    entry=stop_work(db,t,u)
    if entry: audit(db,request,u,"time.stop",entity_type="ticket",entity_id=t.id,details=f"session={entry.id}; seconds={entry.duration_seconds}")
    return RedirectResponse(f"/tickets/{ticket_id}#ticket-time",303)

@router.post("/tickets/{ticket_id}/time/manual")
def ticket_time_manual(ticket_id:int,request:Request,minutes:int=Form(...),work_started_at:str=Form(""),note:str=Form(""),db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    t=db.get(Ticket,ticket_id)
    if not t or not can_view_ticket(u,t) or not has_permission(u,"ticket.time.manual_self") or u.role!="technician" or t.assignee_id!=u.id:
        return forbidden(request,db,u,"ticket.time.manual_self","Вручную добавить своё время может только назначенный техник")
    if t.status in ("resolved","closed","cancelled"):
        return forbidden(request,db,u,"ticket.time.manual_self","Для закрытой или отменённой заявки добавление времени запрещено")
    minutes=max(1,min(int(minutes),24*60))
    try:
        started=datetime.fromisoformat(work_started_at) if work_started_at else datetime.utcnow()-timedelta(minutes=minutes)
    except Exception:
        started=datetime.utcnow()-timedelta(minutes=minutes)
    ended=started+timedelta(minutes=minutes)
    entry=TicketWorkSession(ticket_id=t.id,user_id=u.id,started_at=started,ended_at=ended,duration_seconds=minutes*60,note=(note or "").strip(),source="manual")
    db.add(entry); db.commit(); db.refresh(entry)
    audit(db,request,u,"time.manual",entity_type="ticket",entity_id=t.id,details=f"session={entry.id}; minutes={minutes}")
    return RedirectResponse(f"/tickets/{ticket_id}#ticket-time",303)

@router.post("/tickets/{ticket_id}/time/{entry_id}/delete")
def ticket_time_delete(ticket_id:int,entry_id:int,request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    if not has_permission(u,"ticket.time.delete"):
        return forbidden(request,db,u,"ticket.time.delete","Удалять записи учёта времени может только администратор")
    entry=db.get(TicketWorkSession,entry_id)
    if entry and entry.ticket_id==ticket_id:
        db.delete(entry); db.commit(); audit(db,request,u,"time.delete",entity_type="ticket",entity_id=ticket_id,details=f"session={entry_id}")
    return RedirectResponse(f"/tickets/{ticket_id}#ticket-time",303)

@router.post("/tickets/{ticket_id}/comment")
def ticket_comment(ticket_id:int,request:Request,body:str=Form(...),db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    t=db.get(Ticket,ticket_id)
    if not can_comment_ticket(u,t):
        return forbidden(request,db,u,"ticket.comment")
    db.add(TicketComment(ticket_id=ticket_id,user_id=u.id,body=body)); db.commit()
    audit(db,request,u,"ticket.comment",entity_type="ticket",entity_id=ticket_id,details=(body or "")[:250])
    return RedirectResponse(f"/tickets/{ticket_id}",303)

@router.post("/tickets/{ticket_id}/stock")
def ticket_stock(ticket_id:int,request:Request,item_id:int=Form(...),qty:float=Form(...),db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    item=db.get(InventoryItem,item_id); t=db.get(Ticket,ticket_id)
    if not t or not can_issue_stock(u,t):
        return forbidden(request,db,u,"ticket.stock.issue","Списание материалов доступно назначенному технику или диспетчеру по доступной заявке")
    if not item or qty<=0 or item.qty < qty:
        return templates.TemplateResponse("forbidden.html",ctx(request,db,permission="ticket.stock.issue",message="Недостаточный остаток или некорректное количество"),status_code=400)
    item.qty-=qty; db.add(StockMovement(item_id=item.id,ticket_id=t.id,movement_type="issue",qty=-qty,comment=f"Списание в {t.number}")); t.parts_cost=Decimal(str(float(t.parts_cost or 0)+qty*float(item.unit_cost or 0))); db.commit(); db.refresh(t)
    audit(db,request,u,"stock.issue",entity_type="ticket",entity_id=t.id,details=f"item={item.sku}; qty={qty}")
    push_ticket_to_1c(db,t)
    return RedirectResponse(f"/tickets/{ticket_id}",303)

@router.get("/uploads/{stored_name}")
def protected_upload(stored_name:str,request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse(f"/login?next=/uploads/{stored_name}",303)
    attachment=db.query(Attachment).filter(Attachment.stored_name==stored_name).first()
    if not attachment: return Response(status_code=404)
    ticket=db.get(Ticket,attachment.ticket_id)
    if not can_view_ticket(u,ticket): return forbidden(request,db,u,"ticket.attachment.view")
    path=(Path(settings.upload_dir)/attachment.stored_name).resolve()
    root=Path(settings.upload_dir).resolve()
    if root not in path.parents or not path.exists(): return Response(status_code=404)
    return FileResponse(str(path),filename=attachment.filename)

@router.get("/sites", response_class=HTMLResponse)
def sites_page(request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    if not has_permission(u,"site.view"): return forbidden(request,db,u,"site.view")
    rows=db.query(Site).order_by(Site.name).all()
    return templates.TemplateResponse("sites.html",ctx(request,db,sites=rows))

@router.post("/sites/new")
def site_new(request:Request,name:str=Form(...),address:str=Form(""),db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    if not has_permission(u,"site.manage"): return forbidden(request,db,u,"site.manage")
    if not db.query(Site).filter(Site.name==name).first():
        obj=Site(name=name,address=address); db.add(obj); db.commit(); db.refresh(obj); audit(db,request,u,"site.create",entity_type="site",entity_id=obj.id,details=name)
    return RedirectResponse("/sites",303)

@router.get("/equipment", response_class=HTMLResponse)
def equipment_list(request:Request,site_id:int|None=None,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    if not has_permission(u,"equipment.view"): return forbidden(request,db,u,"equipment.view")
    q=db.query(Equipment)
    if site_id: q=q.filter(Equipment.site_id==site_id)
    return templates.TemplateResponse("equipment.html",ctx(request,db,equipment=q.order_by(Equipment.name).all(),sites=db.query(Site).order_by(Site.name).all(),site_id=site_id))

@router.get("/equipment/new", response_class=HTMLResponse)
def equipment_new_page(request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    if not has_permission(u,"equipment.manage"): return forbidden(request,db,u,"equipment.manage")
    return templates.TemplateResponse("equipment_form.html",ctx(request,db,sites=db.query(Site).order_by(Site.name).all(),status_options=options_for(db,"equipment_status",list(EQUIPMENT_STATUS_LABELS.items()))))

@router.post("/equipment/new")
def equipment_new(request:Request,site_id:int=Form(...),name:str=Form(...),inventory_no:str=Form(...),category:str=Form("Прочее"),model:str=Form(""),serial_no:str=Form(""),status:str=Form("working"),db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    if not has_permission(u,"equipment.manage"): return forbidden(request,db,u,"equipment.manage")
    if db.query(Equipment).filter(Equipment.inventory_no==inventory_no).first(): return RedirectResponse("/equipment",303)
    eq=Equipment(site_id=site_id,name=name,inventory_no=inventory_no,category=category,model=model,serial_no=serial_no,status=status,qr_token=secrets.token_urlsafe(24))
    db.add(eq); db.commit(); db.refresh(eq); audit(db,request,u,"equipment.create",entity_type="equipment",entity_id=eq.id,details=f"{inventory_no} {name}")
    return RedirectResponse(f"/equipment/{eq.id}",303)

@router.get("/equipment/{equipment_id}", response_class=HTMLResponse)
def equipment_detail(equipment_id:int,request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    if not has_permission(u,"equipment.view"): return forbidden(request,db,u,"equipment.view")
    eq=db.get(Equipment,equipment_id)
    if not eq: return RedirectResponse("/equipment",303)
    history_q=scope_ticket_query(db.query(Ticket).filter(Ticket.equipment_id==eq.id),u)
    history=history_q.order_by(Ticket.id.desc()).all()
    plans_q=db.query(MaintenancePlan).filter(MaintenancePlan.equipment_id==eq.id)
    if u.role=="technician": plans_q=plans_q.filter(MaintenancePlan.assignee_id==u.id)
    plans=plans_q.all()
    total=sum(float(x.labor_cost or 0)+float(x.parts_cost or 0) for x in history) if has_permission(u,"ticket.cost") else None
    return templates.TemplateResponse("equipment_detail.html",ctx(request,db,eq=eq,history=history,plans=plans,total_cost=total))

@router.get("/equipment/{equipment_id}/qr.png")
def equipment_qr(equipment_id:int,request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return Response(status_code=401)
    if not has_permission(u,"equipment.view"): return Response(status_code=403)
    eq=db.get(Equipment,equipment_id)
    if not eq: return Response(status_code=404)
    url=public_url(request, settings, f"/scan/{eq.qr_token}")
    img=qrcode.make(url); bio=BytesIO(); img.save(bio,format="PNG")
    return Response(bio.getvalue(),media_type="image/png")

@router.get("/scan/{token}")
def scan_equipment(token:str,request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse(f"/login?next=/scan/{token}",303)
    if not has_permission(u,"ticket.create"): return forbidden(request,db,u,"ticket.create")
    eq=db.query(Equipment).filter(Equipment.qr_token==token).first()
    if not eq: return RedirectResponse("/",303)
    return RedirectResponse(f"/tickets/new?equipment_id={eq.id}",303)

@router.get("/maintenance", response_class=HTMLResponse)
def maintenance(request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    if has_permission(u,"maintenance.view_all"):
        plans=db.query(MaintenancePlan).order_by(MaintenancePlan.next_run).all()
    elif has_permission(u,"maintenance.view_assigned"):
        plans=db.query(MaintenancePlan).filter(MaintenancePlan.assignee_id==u.id).order_by(MaintenancePlan.next_run).all()
    else:
        return forbidden(request,db,u,"maintenance.view_assigned")
    return templates.TemplateResponse("maintenance.html",ctx(request,db,plans=plans,equipment=db.query(Equipment).order_by(Equipment.name).all() if has_permission(u,"maintenance.manage") else [],users=db.query(User).filter(User.role=="technician",User.active==True).order_by(User.full_name).all() if has_permission(u,"maintenance.manage") else []))

@router.post("/maintenance/new")
def maintenance_new(request:Request,equipment_id:int=Form(...),name:str=Form(...),interval_days:int=Form(30),next_run:str=Form(...),assignee_id:str=Form(""),checklist:str=Form(""),db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    if not has_permission(u,"maintenance.manage"): return forbidden(request,db,u,"maintenance.manage")
    if assignee_id:
        tech=db.get(User,int(assignee_id))
        if not tech or not tech.active or tech.role!="technician": return templates.TemplateResponse("forbidden.html",ctx(request,db,permission="maintenance.manage",message="Исполнителем ППР может быть только активный техник"),status_code=400)
    items=[x.strip() for x in checklist.splitlines() if x.strip()]
    plan=MaintenancePlan(equipment_id=equipment_id,name=name,interval_days=interval_days,next_run=date.fromisoformat(next_run),assignee_id=int(assignee_id) if assignee_id else None,checklist=json.dumps(items,ensure_ascii=False))
    db.add(plan); db.commit(); db.refresh(plan); audit(db,request,u,"maintenance.create",entity_type="maintenance",entity_id=plan.id,details=name)
    return RedirectResponse("/maintenance",303)

@router.post("/maintenance/generate")
def maintenance_gen(request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    if not has_permission(u,"maintenance.manage"): return forbidden(request,db,u,"maintenance.manage")
    count=generate_due_maintenance(db); audit(db,request,u,"maintenance.generate",entity_type="maintenance",details=f"created={count}")
    return RedirectResponse("/maintenance",303)

@router.get("/inventory", response_class=HTMLResponse)
def inventory(request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    if not has_permission(u,"inventory.view"): return forbidden(request,db,u,"inventory.view")
    return templates.TemplateResponse("inventory.html",ctx(request,db,items=db.query(InventoryItem).order_by(InventoryItem.name).all()))

@router.post("/inventory/new")
def inventory_new(request:Request,sku:str=Form(...),name:str=Form(...),qty:float=Form(0),min_qty:float=Form(0),unit:str=Form("шт"),unit_cost:float=Form(0),db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    if not has_permission(u,"inventory.manage"): return forbidden(request,db,u,"inventory.manage")
    item=InventoryItem(sku=sku,name=name,qty=qty,min_qty=min_qty,unit=unit,unit_cost=Decimal(str(unit_cost or 0))); db.add(item); db.commit(); db.refresh(item)
    audit(db,request,u,"inventory.create",entity_type="inventory",entity_id=item.id,details=f"{sku} {name}")
    return RedirectResponse("/inventory",303)

@router.get("/contractors", response_class=HTMLResponse)
def contractors(request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    if not has_permission(u,"contractor.view"): return forbidden(request,db,u,"contractor.view")
    return templates.TemplateResponse("contractors.html",ctx(request,db,contractors=db.query(Contractor).order_by(Contractor.name).all()))

@router.post("/contractors/new")
def contractor_new(request:Request,name:str=Form(...),phone:str=Form(""),email:str=Form(""),specialization:str=Form(""),db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    if not has_permission(u,"contractor.manage"): return forbidden(request,db,u,"contractor.manage")
    obj=Contractor(name=name,phone=phone,email=email,specialization=specialization); db.add(obj); db.commit(); db.refresh(obj)
    audit(db,request,u,"contractor.create",entity_type="contractor",entity_id=obj.id,details=name)
    return RedirectResponse("/contractors",303)

@router.get("/users", response_class=HTMLResponse)
def users_page(request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    if not has_permission(u,"users.manage"): return forbidden(request,db,u,"users.manage")
    return templates.TemplateResponse("users.html",ctx(request,db,users=db.query(User).order_by(User.full_name).all()))

@router.post("/users/new")
def user_new(request:Request,username:str=Form(...),full_name:str=Form(...),password:str=Form(...),role:str=Form("requester"),db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    if not has_permission(u,"users.manage"): return forbidden(request,db,u,"users.manage")
    if role not in ("requester","technician","dispatcher","manager","admin"):
        return templates.TemplateResponse("forbidden.html",ctx(request,db,permission="users.manage",message="Недопустимая роль"),status_code=400)
    if len(password)<10:
        return templates.TemplateResponse("forbidden.html",ctx(request,db,permission="users.manage",message="Пароль должен содержать не менее 10 символов"),status_code=400)
    if not db.query(User).filter(User.username==username).first():
        obj=User(username=username,full_name=full_name,password_hash=hash_password(password),role=role,active=True); db.add(obj); db.commit(); db.refresh(obj)
        audit(db,request,u,"user.create",entity_type="user",entity_id=obj.id,details=f"{username}; role={role}")
    return RedirectResponse("/users",303)

@router.post("/users/{user_id}/update")
def user_update(user_id:int,request:Request,role:str=Form(...),active:str=Form(""),db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    if not has_permission(u,"users.manage"): return forbidden(request,db,u,"users.manage")
    target=db.get(User,user_id)
    if not target: return RedirectResponse("/users",303)
    if role not in ("requester","technician","dispatcher","manager","admin"):
        return templates.TemplateResponse("forbidden.html",ctx(request,db,permission="users.manage",message="Недопустимая роль"),status_code=400)
    new_active=(active=="1")
    if target.id==u.id and (not new_active or role!="admin"):
        return templates.TemplateResponse("forbidden.html",ctx(request,db,permission="users.manage",message="Администратор не может отключить себя или снять с себя роль администратора"),status_code=400)
    if target.role=="admin" and (not new_active or role!="admin"):
        active_admins=db.query(User).filter(User.role=="admin",User.active==True,User.id!=target.id).count()
        if active_admins==0:
            return templates.TemplateResponse("forbidden.html",ctx(request,db,permission="users.manage",message="Нельзя отключить или понизить последнего активного администратора"),status_code=400)
    if target.role=="technician" and (not new_active or role!="technician"):
        open_assigned=db.query(Ticket).filter(Ticket.assignee_id==target.id,Ticket.status.in_(["new","assigned","in_progress","waiting"])).count()
        active_timer=db.query(TicketWorkSession).filter(TicketWorkSession.user_id==target.id,TicketWorkSession.ended_at.is_(None)).count()
        if active_timer:
            return templates.TemplateResponse("forbidden.html",ctx(request,db,permission="users.manage",message="Нельзя отключить или сменить роль техника, пока у него запущен таймер. Сначала остановите текущую работу."),status_code=400)
        if open_assigned:
            return templates.TemplateResponse("forbidden.html",ctx(request,db,permission="users.manage",message=f"У техника есть незавершённые назначенные заявки: {open_assigned}. Сначала переназначьте их."),status_code=400)
    old=f"role={target.role}; active={target.active}"
    target.role=role; target.active=new_active; db.commit()
    audit(db,request,u,"user.update",entity_type="user",entity_id=target.id,details=f"{old} -> role={role}; active={new_active}")
    return RedirectResponse("/users",303)

@router.get("/integration", response_class=HTMLResponse)
def integration(request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    if not has_permission(u,"integration.manage"): return forbidden(request,db,u,"integration.manage")
    c=OneCClient()
    return templates.TemplateResponse("integration.html",ctx(request,db,settings=settings,status=c.health()))

@router.get("/audit", response_class=HTMLResponse)
def audit_page(request:Request,result:str="",db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    if not has_permission(u,"audit.view"): return forbidden(request,db,u,"audit.view")
    q=db.query(AuditLog)
    if result: q=q.filter(AuditLog.result==result)
    rows=q.order_by(AuditLog.id.desc()).limit(500).all()
    return templates.TemplateResponse("audit.html",ctx(request,db,rows=rows,result=result))

@router.get("/settings/reference-data", response_class=HTMLResponse)
def reference_settings(request:Request, db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    if not has_permission(u,"settings.manage"): return forbidden(request,db,u,"settings.manage")
    ensure_default_reference_data(db)
    rows=db.query(UiStyle).order_by(UiStyle.kind,UiStyle.sort_order,UiStyle.id).all()
    grouped={}
    for row in rows:
        grouped.setdefault(row.kind,[]).append(row)
    kind_labels={"status":"Статусы заявок","priority":"Приоритеты и SLA","category":"Категории работ","equipment_status":"Статусы оборудования"}
    return templates.TemplateResponse("reference_settings.html",ctx(request,db,grouped=grouped,kind_labels=kind_labels,message=request.query_params.get("message","")))

@router.post("/settings/reference-data/{row_id}/update")
def reference_update(row_id:int, request:Request, name:str=Form(...), bg_color:str=Form(""), text_color:str=Form(""), border_color:str=Form(""), sla_hours:str=Form(""), sort_order:int=Form(100), active:str=Form(""), db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    if not has_permission(u,"settings.manage"): return forbidden(request,db,u,"settings.manage")
    row=db.get(UiStyle,row_id)
    if row:
        row.name=name.strip() or row.code
        row.bg_color=bg_color.strip()
        row.text_color=text_color.strip()
        row.border_color=border_color.strip()
        try: row.sla_hours=int(sla_hours) if sla_hours.strip() else None
        except Exception: row.sla_hours=None
        row.sort_order=sort_order
        row.active=(active=="1")
        db.commit()
    return RedirectResponse("/settings/reference-data?message=Сохранено",303)

@router.post("/settings/reference-data/new")
def reference_new(request:Request, kind:str=Form(...), code:str=Form(...), name:str=Form(...), bg_color:str=Form("#eef1f5"), text_color:str=Form("#536071"), border_color:str=Form("#dce2e9"), sla_hours:str=Form(""), sort_order:int=Form(100), db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    if not has_permission(u,"settings.manage"): return forbidden(request,db,u,"settings.manage")
    kind=kind.strip(); code=code.strip(); name=name.strip()
    if kind == "category" and code and not db.query(UiStyle).filter(UiStyle.kind==kind,UiStyle.code==code).first():
        try: sla=int(sla_hours) if sla_hours.strip() else None
        except Exception: sla=None
        db.add(UiStyle(kind=kind,code=code,name=name or code,bg_color=bg_color,text_color=text_color,border_color=border_color,sla_hours=sla,sort_order=sort_order,active=True))
        db.commit()
    return RedirectResponse("/settings/reference-data?message=Добавлено",303)
