from __future__ import annotations
import base64, csv, io, json, mimetypes, os, secrets, textwrap
from datetime import datetime, date, timedelta
from html import escape as html_escape
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
<<<<<<< HEAD
from app.models import User, Site, Equipment, Ticket, TicketComment, Attachment, MaintenancePlan, InventoryItem, StockMovement, Contractor, UiStyle, TicketWorkSession, AuditLog
from app.security import verify_password, current_user, hash_password
=======
from app.models import User, Site, Equipment, Ticket, TicketComment, Attachment, MaintenancePlan, InventoryItem, StockMovement, Contractor, UiStyle, TicketWorkSession, AuditLog, ServiceCatalog, CustomField, TicketCustomValue, KnowledgeArticle, TicketLink, ApprovalRequest, TicketFeedback, SavedFilter, Notification
from app.security import verify_password, current_user, hash_password, verify_totp
>>>>>>> c83dea0 (Первый коммит)
from app.services.maintenance import next_ticket_number, generate_due_maintenance
from app.services.one_c import OneCClient
from app.services.sync import push_ticket_to_1c
from app.labels import STATUS_LABELS, PRIORITY_LABELS, ROLE_LABELS, EQUIPMENT_STATUS_LABELS
from app.services.ui_styles import styles_cache, badge_css, display_name, options_for, sla_hours_for
from app.services.reference_data import ensure_default_reference_data
from app.services.urls import public_url
from app.services.kpi import calculate_monthly_kpi, parse_period, shift_month
from app.services.time_tracking import ticket_time_summary, ticket_time_totals, format_duration, start_work, stop_work, close_active_for_ticket, can_track_time
from app.services.materials import ticket_material_summary, recalc_ticket_parts_cost, as_money, movement_amount, movement_unit_cost
from app.access import has_permission, scope_ticket_query, can_view_ticket, can_comment_ticket, can_issue_stock, can_track_ticket_time, allowed_statuses, can_change_ticket_status, visible_navigation, role_summary
from app.services.audit import audit
<<<<<<< HEAD
=======
from app.services.ldap_auth import authenticate_ldap
from app.services.automation import apply_ticket_rules
from app.services.notifications import notify_user
>>>>>>> c83dea0 (Первый коммит)

router=APIRouter()
templates=Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))
settings=get_settings()

SAFE_INLINE_MIMES = {
    "image/jpeg", "image/png", "image/webp", "image/gif", "image/avif", "image/heic", "image/heif",
    "application/pdf", "text/plain", "text/csv",
}

def attachment_mime(filename: str) -> str:
    mime = mimetypes.guess_type(filename or "")[0] or "application/octet-stream"
    # SVG/HTML/XML are intentionally not rendered inline under the authenticated
    # application origin because active content could execute in the FMTS session.
    if mime in {"image/svg+xml", "text/html", "application/xhtml+xml", "application/xml", "text/xml"}:
        return "application/octet-stream"
    return mime

def attachment_kind(filename: str) -> str:
    mime = attachment_mime(filename)
    if mime.startswith("image/"): return "image"
    if mime == "application/pdf": return "pdf"
    if mime.startswith("text/"): return "text"
    if mime.startswith("video/"): return "video"
    if mime.startswith("audio/"): return "audio"
    return "document"

def _attachment_path(attachment: Attachment) -> Path | None:
    path=(Path(settings.upload_dir)/attachment.stored_name).resolve()
    root=Path(settings.upload_dir).resolve()
    if root not in path.parents or not path.exists():
        return None
    return path

def _prepare_comment_photo(upload: UploadFile) -> tuple[str, str, bytes]:
    filename=Path(upload.filename or "photo.jpg").name[:255]
    content_type=(upload.content_type or mimetypes.guess_type(filename)[0] or "").lower()
    if not content_type.startswith("image/") or content_type in {"image/svg+xml"}:
        raise ValueError("К комментарию можно прикреплять только фотографии")
    max_bytes=max(1,settings.comment_photo_max_mb)*1024*1024
    data=upload.file.read(max_bytes+1)
    if len(data)>max_bytes:
        raise ValueError(f"Фото превышает {settings.comment_photo_max_mb} МБ")
    if not data:
        raise ValueError("Пустой файл")
    ext=Path(filename).suffix.lower()
    if len(ext)>10 or not ext:
        ext=mimetypes.guess_extension(content_type) or ".jpg"
    stored=f"{secrets.token_hex(16)}{ext}"
    return filename,stored,data

def _qr_png_bytes(url: str) -> bytes:
    qr=qrcode.QRCode(version=None,error_correction=qrcode.constants.ERROR_CORRECT_M,box_size=12,border=2)
    qr.add_data(url); qr.make(fit=True)
    img=qr.make_image(fill_color="#0f172a",back_color="white")
    bio=BytesIO(); img.save(bio,format="PNG")
    return bio.getvalue()

def _wrap_label(text: str, width: int, lines: int=2) -> list[str]:
    raw=" ".join((text or "—").split())
    out=textwrap.wrap(raw,width=width,break_long_words=False,break_on_hyphens=False) or ["—"]
    if len(out)>lines:
        out=out[:lines]
        out[-1]=(out[-1][:-1]+"…") if len(out[-1])>1 else out[-1]+"…"
    return out

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
          "attachment_kind":attachment_kind,
          "can":lambda permission: bool(u and has_permission(u,permission)),
          "nav":visible_navigation(u),
<<<<<<< HEAD
          "role_summary":role_summary}
=======
          "role_summary":role_summary,
          "unread_notifications": (db.query(Notification).filter(Notification.user_id==u.id,Notification.read_at.is_(None)).count() if u else 0),
          "saved_filters": (db.query(SavedFilter).filter(SavedFilter.user_id==u.id).order_by(SavedFilter.name).all() if u else [])}
>>>>>>> c83dea0 (Первый коммит)
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
<<<<<<< HEAD
def login(request:Request, username:str=Form(...), password:str=Form(...), next_url:str=Form(""), db:Session=Depends(get_db)):
    u=db.query(User).filter(User.username==username,User.active==True).first()
    if not u or not verify_password(password,u.password_hash):
        audit(db,request,u,"auth.login",entity_type="user",entity_id=(u.id if u else username),result="denied",details=f"username={username}")
        return templates.TemplateResponse("login.html",ctx(request,db,error="Неверный логин или пароль",next_url=next_url),status_code=401)
=======
def login(request:Request, username:str=Form(...), password:str=Form(...), otp:str=Form(""), next_url:str=Form(""), db:Session=Depends(get_db)):
    u=db.query(User).filter(User.username==username,User.active==True).first()
    local_ok=bool(u and verify_password(password,u.password_hash))
    if not local_ok:
        ldap_user=authenticate_ldap(db,username,password)
        if ldap_user: u=ldap_user; local_ok=True
    if not local_ok:
        audit(db,request,u,"auth.login",entity_type="user",entity_id=(u.id if u else username),result="denied",details=f"username={username}")
        return templates.TemplateResponse("login.html",ctx(request,db,error="Неверный логин или пароль",next_url=next_url),status_code=401)
    if u.totp_enabled and not verify_totp(u.totp_secret,otp):
        audit(db,request,u,"auth.2fa",entity_type="user",entity_id=u.id,result="denied",details="Неверный код 2FA")
        return templates.TemplateResponse("login.html",ctx(request,db,error="Введите корректный 6-значный код двухфакторной авторизации",next_url=next_url),status_code=401)
>>>>>>> c83dea0 (Первый коммит)
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

<<<<<<< HEAD
=======
@router.post("/profile/contact")
def profile_contact(request:Request,email:str=Form(""),phone:str=Form(""),telegram_chat_id:str=Form(""),db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u:return RedirectResponse("/login",303)
    u.email=email.strip();u.phone=phone.strip();u.telegram_chat_id=telegram_chat_id.strip();db.commit()
    audit(db,request,u,"profile.contact_update",entity_type="user",entity_id=u.id)
    return RedirectResponse("/profile",303)

>>>>>>> c83dea0 (Первый коммит)
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
<<<<<<< HEAD
        "Фактическое время работ, ч","Сеансов работы","Просрочено при выполнении","Открытый хвост сейчас","Просрочено сейчас"
=======
        "Фактическое время работ, ч","Сеансов работы","Оценка заявителей / 5","Отзывов","Просрочено при выполнении","Открытый хвост сейчас","Просрочено сейчас"
>>>>>>> c83dea0 (Первый коммит)
    ])
    for row in report["rows"]:
        writer.writerow([
            row["rank"] or "",row["name"],str(row["score"]).replace('.',','),str(row["rating"]).replace('.',','),
            row["handled"],row["completed"],str(row["points"]).replace('.',','),str(row["sla_rate"]).replace('.',','),
            str(row["closure_rate"]).replace('.',','),str(row["productivity_rate"]).replace('.',','),
            str(row["documentation_rate"]).replace('.',','),str(row["avg_resolution_hours"]).replace('.',','),
<<<<<<< HEAD
            str(row["tracked_hours"]).replace('.',','),row["work_sessions"],
=======
            str(row["tracked_hours"]).replace('.',','),row["work_sessions"],str(row.get("customer_rating",0)).replace('.',','),row.get("customer_reviews",0),
>>>>>>> c83dea0 (Первый коммит)
            row["overdue_completed"],row["open_backlog"],row["overdue_open"],
        ])
    payload=('\ufeff'+out.getvalue()).encode('utf-8')
    headers={"Content-Disposition": f'attachment; filename="FMTS_KPI_{period.value}.csv"'}
    return Response(content=payload,media_type="text/csv; charset=utf-8",headers=headers)

@router.get("/tickets", response_class=HTMLResponse)
<<<<<<< HEAD
def tickets(request:Request,status:str="",q:str="",db:Session=Depends(get_db)):
=======
def tickets(request:Request,status:str="",q:str="",priority:str="",site_id:str="",assignee_id:str="",db:Session=Depends(get_db)):
>>>>>>> c83dea0 (Первый коммит)
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    if not has_permission(u,"ticket.list") and not has_permission(u,"ticket.list_all"):
        return forbidden(request,db,u,"ticket.list")
    query=scope_ticket_query(db.query(Ticket),u)
    if status: query=query.filter(Ticket.status==status)
<<<<<<< HEAD
    if q: query=query.filter((Ticket.title.contains(q)) | (Ticket.number.contains(q)))
    rows=query.order_by(Ticket.id.desc()).all()
    time_totals=ticket_time_totals(db,[x.id for x in rows])
    return templates.TemplateResponse("tickets.html",ctx(request,db,tickets=rows,time_totals=time_totals,status=status,q=q,status_options=options_for(db,"status",list(STATUS_LABELS.items()))))
=======
    if priority: query=query.filter(Ticket.priority==priority)
    if site_id: query=query.filter(Ticket.site_id==int(site_id))
    if assignee_id: query=query.filter(Ticket.assignee_id==int(assignee_id))
    if q: query=query.filter((Ticket.title.contains(q)) | (Ticket.number.contains(q)) | (Ticket.description.contains(q)) | (Ticket.requester_name.contains(q)))
    rows=query.order_by(Ticket.id.desc()).all()
    time_totals=ticket_time_totals(db,[x.id for x in rows])
    return templates.TemplateResponse("tickets.html",ctx(request,db,tickets=rows,time_totals=time_totals,status=status,q=q,priority=priority,site_id=site_id,assignee_id=assignee_id,status_options=options_for(db,"status",list(STATUS_LABELS.items())),priority_options=options_for(db,"priority",list(PRIORITY_LABELS.items())),sites=db.query(Site).order_by(Site.name).all(),technicians=db.query(User).filter(User.role=="technician",User.active==True).order_by(User.full_name).all()))
>>>>>>> c83dea0 (Первый коммит)

@router.get("/tickets/new", response_class=HTMLResponse)
def ticket_new(request:Request,equipment_id:int|None=None,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    if not has_permission(u,"ticket.create"):
        return forbidden(request,db,u,"ticket.create")
    technicians=db.query(User).filter(User.role=="technician",User.active==True).order_by(User.full_name).all() if has_permission(u,"ticket.assign") else []
<<<<<<< HEAD
    return templates.TemplateResponse("ticket_form.html",ctx(request,db,sites=db.query(Site).order_by(Site.name).all(),equipment=db.query(Equipment).order_by(Equipment.name).all(),users=technicians,selected_equipment_id=equipment_id,categories=options_for(db,"category",[(x,x) for x in ["Электрика","Сантехника","Мебель","Отделка","Кондиционер","Окна","Двери","Компьютер","Другое"]]),priority_options=options_for(db,"priority",list(PRIORITY_LABELS.items()))))

@router.post("/tickets/new")
def ticket_create(request:Request,title:str=Form(...),description:str=Form(""),category:str=Form("Другое"),priority:str=Form("normal"),site_id:int=Form(...),equipment_id:str=Form(""),assignee_id:str=Form(""),room:str=Form(""),phone:str=Form(""),attachment:UploadFile|None=File(None),db:Session=Depends(get_db)):
=======
    return templates.TemplateResponse("ticket_form.html",ctx(request,db,sites=db.query(Site).order_by(Site.name).all(),equipment=db.query(Equipment).order_by(Equipment.name).all(),users=technicians,selected_equipment_id=equipment_id,categories=options_for(db,"category",[(x,x) for x in ["Электрика","Сантехника","Мебель","Отделка","Кондиционер","Окна","Двери","Компьютер","Другое"]]),priority_options=options_for(db,"priority",list(PRIORITY_LABELS.items())),services=db.query(ServiceCatalog).filter(ServiceCatalog.active==True).order_by(ServiceCatalog.name).all(),custom_fields=db.query(CustomField).filter(CustomField.active==True).order_by(CustomField.sort_order,CustomField.name).all(),custom_field_options={f.id:(json.loads(f.options_json or "[]") if (f.options_json or "").strip().startswith("[") else []) for f in db.query(CustomField).filter(CustomField.active==True).all()}))

@router.post("/tickets/new")
async def ticket_create(request:Request,title:str=Form(...),description:str=Form(""),category:str=Form("Другое"),priority:str=Form("normal"),service_id:str=Form(""),site_id:int=Form(...),equipment_id:str=Form(""),assignee_id:str=Form(""),room:str=Form(""),phone:str=Form(""),attachment:UploadFile|None=File(None),db:Session=Depends(get_db)):
>>>>>>> c83dea0 (Первый коммит)
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    if not has_permission(u,"ticket.create"):
        return forbidden(request,db,u,"ticket.create")
    site=db.get(Site,site_id)
    if not site: return templates.TemplateResponse("forbidden.html",ctx(request,db,permission="ticket.create",message="Выбранный объект не существует"),status_code=400)
<<<<<<< HEAD
=======
    service=db.get(ServiceCatalog,int(service_id)) if service_id else None
    if service and service.active:
        category=service.category or category
        if has_permission(u,"ticket.set_priority"): priority=service.default_priority or priority
    form_data=await request.form()
    service_fields=db.query(CustomField).filter(CustomField.active==True,((CustomField.service_id==(service.id if service else None))|(CustomField.service_id.is_(None)))).all()
    missing=[f.name for f in service_fields if f.required and not str(form_data.get(f"field_{f.id}","")).strip()]
    if missing:
        return templates.TemplateResponse("forbidden.html",ctx(request,db,permission="ticket.create",message="Заполните обязательные поля: "+", ".join(missing)),status_code=400)
>>>>>>> c83dea0 (Первый коммит)
    eq_id=int(equipment_id) if equipment_id else None
    if eq_id:
        eq=db.get(Equipment,eq_id)
        if not eq or eq.site_id != site_id:
            return templates.TemplateResponse("forbidden.html",ctx(request,db,permission="ticket.create",message="Оборудование не относится к выбранному объекту"),status_code=400)
    # Заявитель/техник не могут самовольно повышать приоритет или назначать исполнителя.
<<<<<<< HEAD
    effective_priority=priority if has_permission(u,"ticket.set_priority") else "normal"
=======
    effective_priority=(service.default_priority if service and service.default_priority else (priority if has_permission(u,"ticket.set_priority") else "normal"))
>>>>>>> c83dea0 (Первый коммит)
    new_assignee_id=None
    if assignee_id and has_permission(u,"ticket.assign"):
        target=db.get(User,int(assignee_id))
        if target and target.active and target.role=="technician":
            new_assignee_id=target.id
    sla_hours=sla_hours_for(db,effective_priority)
    t=Ticket(number=next_ticket_number(db),title=title,description=description,category=category,priority=effective_priority,status="assigned" if new_assignee_id else "new",site_id=site_id,
             equipment_id=eq_id,requester_id=u.id,requester_name=u.full_name,requester_phone=phone,room=room,
<<<<<<< HEAD
             assignee_id=new_assignee_id,master_name="",sla_due_at=datetime.utcnow()+timedelta(hours=sla_hours))
    if new_assignee_id:
        assigned=db.get(User,new_assignee_id); t.master_name=assigned.full_name if assigned else ""
    db.add(t); db.flush()
=======
             assignee_id=new_assignee_id,master_name="",service_id=(service.id if service else None),sla_due_at=datetime.utcnow()+timedelta(hours=(service.default_sla_hours if service and service.default_sla_hours else sla_hours)))
    if new_assignee_id:
        assigned=db.get(User,new_assignee_id); t.master_name=assigned.full_name if assigned else ""
    db.add(t); db.flush()
    apply_ticket_rules(db,t)
    fields=db.query(CustomField).filter(CustomField.active==True,((CustomField.service_id==t.service_id)|(CustomField.service_id.is_(None)))).all()
    for field in fields:
        value=str(form_data.get(f"field_{field.id}","")).strip()
        if value:
            db.add(TicketCustomValue(ticket_id=t.id,field_id=field.id,value=value))
>>>>>>> c83dea0 (Первый коммит)
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
    materials=ticket_material_summary(db,t.id) if has_permission(u,"ticket.materials.view") else {"rows":[],"total":Decimal("0.00"),"count":0}
    total_cost=as_money(t.labor_cost)+as_money(materials["total"])
    return templates.TemplateResponse("ticket_detail.html",ctx(request,db,ticket=t,work_time=work_time,active_session=active_session,
        can_track=can_track_ticket_time(u,t),users=technicians,contractors=db.query(Contractor).order_by(Contractor.name).all() if has_permission(u,"contractor.view") or has_permission(u,"ticket.contractor") else [],
        inventory=db.query(InventoryItem).order_by(InventoryItem.name).all() if has_permission(u,"inventory.view") else [],status_options=status_options,
<<<<<<< HEAD
        materials=materials,total_cost=total_cost))
=======
        materials=materials,total_cost=total_cost,
        service=db.get(ServiceCatalog,t.service_id) if t.service_id else None,
        custom_fields=db.query(CustomField).filter(CustomField.active==True,((CustomField.service_id==t.service_id)|(CustomField.service_id.is_(None)))).order_by(CustomField.sort_order,CustomField.name).all(),
        custom_values={x.field_id:x.value for x in db.query(TicketCustomValue).filter(TicketCustomValue.ticket_id==t.id).all()},
        custom_field_options={f.id:(json.loads(f.options_json or "[]") if (f.options_json or "").strip().startswith("[") else []) for f in db.query(CustomField).filter(CustomField.active==True,((CustomField.service_id==t.service_id)|(CustomField.service_id.is_(None)))).all()},
        ticket_links=db.query(TicketLink).filter(TicketLink.ticket_id==t.id).order_by(TicketLink.id.desc()).all(),
        approvals=db.query(ApprovalRequest).filter(ApprovalRequest.ticket_id==t.id).order_by(ApprovalRequest.id.desc()).all(),
        feedback_rows=db.query(TicketFeedback).filter(TicketFeedback.ticket_id==t.id).order_by(TicketFeedback.id.desc()).all(),
        approvers=db.query(User).filter(User.active==True,User.role.in_(["manager","admin"])).order_by(User.full_name).all(),
        knowledge_suggestions=db.query(KnowledgeArticle).filter(KnowledgeArticle.active==True).filter(((KnowledgeArticle.equipment_category==t.equipment.category) if t.equipment else (KnowledgeArticle.equipment_category=="")) | (KnowledgeArticle.service_id==t.service_id)).order_by(KnowledgeArticle.updated_at.desc()).limit(5).all()))
>>>>>>> c83dea0 (Первый коммит)

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
<<<<<<< HEAD
=======
    if t.assignee_id and t.assignee_id!=old_assignee_id:
        notify_user(db,db.get(User,t.assignee_id),f"Назначена заявка {t.number}",t.title,f"/tickets/{t.id}",dedup_key=f"assigned:{t.id}:{t.assignee_id}")
        db.commit()
>>>>>>> c83dea0 (Первый коммит)
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
def ticket_comment(ticket_id:int,request:Request,body:str=Form(""),photos:list[UploadFile]|None=File(None),db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    t=db.get(Ticket,ticket_id)
    if not can_comment_ticket(u,t):
        return forbidden(request,db,u,"ticket.comment")
    uploads=[x for x in (photos or []) if x and x.filename]
    if len(uploads)>settings.comment_photo_max_count:
        return templates.TemplateResponse("forbidden.html",ctx(request,db,permission="ticket.comment",message=f"К одному комментарию можно прикрепить не более {settings.comment_photo_max_count} фото"),status_code=400)
    prepared=[]
    try:
        for upload in uploads:
            prepared.append(_prepare_comment_photo(upload))
    except ValueError as exc:
        return templates.TemplateResponse("forbidden.html",ctx(request,db,permission="ticket.comment",message=str(exc)),status_code=400)
    text=(body or "").strip()
    if not text and not prepared:
        return templates.TemplateResponse("forbidden.html",ctx(request,db,permission="ticket.comment",message="Добавьте текст комментария или фотографию"),status_code=400)
    comment=TicketComment(ticket_id=ticket_id,user_id=u.id,body=text)
    db.add(comment); db.flush()
    created_paths=[]
    try:
        Path(settings.upload_dir).mkdir(parents=True,exist_ok=True)
        for filename,stored,data in prepared:
            target=Path(settings.upload_dir)/stored
            target.write_bytes(data); created_paths.append(target)
            db.add(Attachment(ticket_id=ticket_id,comment_id=comment.id,filename=filename,stored_name=stored))
        db.commit()
    except Exception:
        db.rollback()
        for path in created_paths:
            try: path.unlink(missing_ok=True)
            except Exception: pass
        raise
    audit(db,request,u,"ticket.comment",entity_type="ticket",entity_id=ticket_id,details=f"{text[:200]}; photos={len(prepared)}")
<<<<<<< HEAD
=======
    recipients=[]
    if t.assignee_id and t.assignee_id!=u.id: recipients.append(db.get(User,t.assignee_id))
    if t.requester_id and t.requester_id!=u.id: recipients.append(db.get(User,t.requester_id))
    for recipient in recipients:
        notify_user(db,recipient,f"Новый комментарий в {t.number}",(text[:180] or "Прикреплено фото"),f"/tickets/{t.id}#ticket-comments")
    db.commit()
>>>>>>> c83dea0 (Первый коммит)
    return RedirectResponse(f"/tickets/{ticket_id}#ticket-comments",303)

@router.post("/tickets/{ticket_id}/stock")
def ticket_stock(ticket_id:int,request:Request,item_id:int=Form(...),qty:float=Form(...),db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    item=db.get(InventoryItem,item_id); t=db.get(Ticket,ticket_id)
    if not t or not can_issue_stock(u,t):
        return forbidden(request,db,u,"ticket.stock.issue","Списание материалов доступно назначенному технику или диспетчеру по доступной заявке")
    if not item or qty<=0 or item.qty < qty:
        return templates.TemplateResponse("forbidden.html",ctx(request,db,permission="ticket.stock.issue",message="Недостаточный остаток или некорректное количество"),status_code=400)
    unit_cost=as_money(item.unit_cost)
    amount=(Decimal(str(qty))*unit_cost).quantize(Decimal("0.01"))
    item.qty-=qty
    db.add(StockMovement(
        item_id=item.id,
        ticket_id=t.id,
        movement_type="issue",
        qty=-qty,
        unit_cost_snapshot=unit_cost,
        amount=amount,
        issued_by_id=u.id,
        comment=f"Списание в {t.number}",
    ))
    db.flush()
    recalc_ticket_parts_cost(db,t)
    db.commit(); db.refresh(t)
    audit(db,request,u,"stock.issue",entity_type="ticket",entity_id=t.id,details=f"item={item.sku}; qty={qty}; unit_cost={unit_cost}; amount={amount}")
    push_ticket_to_1c(db,t)
    return RedirectResponse(f"/tickets/{ticket_id}",303)

def _visible_attachment(attachment_id:int, user:User, db:Session) -> tuple[Attachment|None, Ticket|None]:
    attachment=db.get(Attachment,attachment_id)
    if not attachment: return None,None
    ticket=db.get(Ticket,attachment.ticket_id)
    if not can_view_ticket(user,ticket): return attachment,None
    return attachment,ticket

@router.get("/attachments/{attachment_id}", response_class=HTMLResponse)
def attachment_view(attachment_id:int,request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse(f"/login?next=/attachments/{attachment_id}",303)
    attachment,ticket=_visible_attachment(attachment_id,u,db)
    if not attachment: return Response(status_code=404)
    if not ticket: return forbidden(request,db,u,"ticket.attachment.view")
    if not _attachment_path(attachment): return Response(status_code=404)
    return templates.TemplateResponse("attachment_view.html",ctx(request,db,attachment=attachment,ticket=ticket,kind=attachment_kind(attachment.filename),mime=attachment_mime(attachment.filename)))

@router.get("/attachments/{attachment_id}/raw")
def attachment_raw(attachment_id:int,request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return Response(status_code=401)
    attachment,ticket=_visible_attachment(attachment_id,u,db)
    if not attachment: return Response(status_code=404)
    if not ticket: return Response(status_code=403)
    path=_attachment_path(attachment)
    if not path: return Response(status_code=404)
    mime=attachment_mime(attachment.filename)
    inline_type=mime if mime in SAFE_INLINE_MIMES else "application/octet-stream"
    return FileResponse(str(path),filename=attachment.filename,media_type=inline_type,content_disposition_type="inline")

@router.get("/attachments/{attachment_id}/download")
def attachment_download(attachment_id:int,request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return Response(status_code=401)
    attachment,ticket=_visible_attachment(attachment_id,u,db)
    if not attachment: return Response(status_code=404)
    if not ticket: return Response(status_code=403)
    path=_attachment_path(attachment)
    if not path: return Response(status_code=404)
    return FileResponse(str(path),filename=attachment.filename,media_type=attachment_mime(attachment.filename),content_disposition_type="attachment")

@router.get("/uploads/{stored_name}")
def protected_upload(stored_name:str,request:Request,db:Session=Depends(get_db)):
    # Compatibility route for old links: opening a file now goes through the
    # protected preview page instead of forcing an immediate download.
    u=user_or_login(request,db)
    if not u: return RedirectResponse(f"/login?next=/uploads/{stored_name}",303)
    attachment=db.query(Attachment).filter(Attachment.stored_name==stored_name).first()
    if not attachment: return Response(status_code=404)
    ticket=db.get(Ticket,attachment.ticket_id)
    if not can_view_ticket(u,ticket): return forbidden(request,db,u,"ticket.attachment.view")
    return RedirectResponse(f"/attachments/{attachment.id}",302)

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
<<<<<<< HEAD
    return templates.TemplateResponse("equipment_form.html",ctx(request,db,sites=db.query(Site).order_by(Site.name).all(),status_options=options_for(db,"equipment_status",list(EQUIPMENT_STATUS_LABELS.items()))))

@router.post("/equipment/new")
def equipment_new(request:Request,site_id:int=Form(...),name:str=Form(...),inventory_no:str=Form(...),category:str=Form("Прочее"),model:str=Form(""),serial_no:str=Form(""),status:str=Form("working"),db:Session=Depends(get_db)):
=======
    return templates.TemplateResponse("equipment_form.html",ctx(request,db,sites=db.query(Site).order_by(Site.name).all(),status_options=options_for(db,"equipment_status",list(EQUIPMENT_STATUS_LABELS.items())),equipment_all=db.query(Equipment).order_by(Equipment.name).all(),owners=db.query(User).filter(User.active==True).order_by(User.full_name).all()))

@router.post("/equipment/new")
def equipment_new(request:Request,site_id:int=Form(...),name:str=Form(...),inventory_no:str=Form(...),category:str=Form("Прочее"),model:str=Form(""),serial_no:str=Form(""),status:str=Form("working"),parent_id:str=Form(""),owner_user_id:str=Form(""),criticality:str=Form("normal"),db:Session=Depends(get_db)):
>>>>>>> c83dea0 (Первый коммит)
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    if not has_permission(u,"equipment.manage"): return forbidden(request,db,u,"equipment.manage")
    if db.query(Equipment).filter(Equipment.inventory_no==inventory_no).first(): return RedirectResponse("/equipment",303)
<<<<<<< HEAD
    eq=Equipment(site_id=site_id,name=name,inventory_no=inventory_no,category=category,model=model,serial_no=serial_no,status=status,qr_token=secrets.token_urlsafe(24))
=======
    eq=Equipment(site_id=site_id,name=name,inventory_no=inventory_no,category=category,model=model,serial_no=serial_no,status=status,qr_token=secrets.token_urlsafe(24),parent_id=int(parent_id) if parent_id else None,owner_user_id=int(owner_user_id) if owner_user_id else None,criticality=criticality)
>>>>>>> c83dea0 (Первый коммит)
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
<<<<<<< HEAD
    return templates.TemplateResponse("equipment_detail.html",ctx(request,db,eq=eq,history=history,plans=plans,total_cost=total))
=======
    return templates.TemplateResponse("equipment_detail.html",ctx(request,db,eq=eq,history=history,plans=plans,total_cost=total,parent_equipment=db.get(Equipment,eq.parent_id) if eq.parent_id else None,child_equipment=db.query(Equipment).filter(Equipment.parent_id==eq.id).order_by(Equipment.name).all(),owner=db.get(User,eq.owner_user_id) if eq.owner_user_id else None))
>>>>>>> c83dea0 (Первый коммит)

@router.get("/equipment/{equipment_id}/qr.png")
def equipment_qr(equipment_id:int,request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return Response(status_code=401)
    if not has_permission(u,"equipment.view"): return Response(status_code=403)
    eq=db.get(Equipment,equipment_id)
    if not eq: return Response(status_code=404)
    url=public_url(request, settings, f"/scan/{eq.qr_token}")
    return Response(_qr_png_bytes(url),media_type="image/png",headers={"Cache-Control":"no-store"})

@router.get("/equipment/{equipment_id}/label.svg")
def equipment_label_svg(equipment_id:int,request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return Response(status_code=401)
    if not has_permission(u,"equipment.view"): return Response(status_code=403)
    eq=db.get(Equipment,equipment_id)
    if not eq: return Response(status_code=404)
    url=public_url(request, settings, f"/scan/{eq.qr_token}")
    qr64=base64.b64encode(_qr_png_bytes(url)).decode("ascii")
    name_lines=_wrap_label(eq.name,30,2)
    site_lines=_wrap_label(eq.site.name if eq.site else "Объект не указан",38,2)
    name_svg="".join(f'<text x="390" y="{150+i*50}" text-anchor="middle" class="equipment">{html_escape(line)}</text>' for i,line in enumerate(name_lines))
    site_y=255 if len(name_lines)>1 else 220
    site_svg="".join(f'<text x="390" y="{site_y+i*30}" text-anchor="middle" class="site">{html_escape(line)}</text>' for i,line in enumerate(site_lines))
    inv_y=site_y+len(site_lines)*30+18
    qr_y=inv_y+72
    footer_y=qr_y+488
    svg=f'''<svg xmlns="http://www.w3.org/2000/svg" width="780" height="980" viewBox="0 0 780 980">
      <style>
        .brand{{font:700 28px -apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;fill:#fff;letter-spacing:2px}}
        .equipment{{font:800 38px -apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;fill:#111827}}
        .site{{font:650 24px -apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;fill:#475569}}
        .inv-label{{font:700 17px -apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;fill:#64748b;letter-spacing:1.8px}}
        .inv{{font:800 29px -apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;fill:#0f172a}}
        .small{{font:600 18px -apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;fill:#64748b}}
      </style>
      <rect x="8" y="8" width="764" height="964" rx="34" fill="#fff" stroke="#cbd5e1" stroke-width="4"/>
      <rect x="8" y="8" width="764" height="92" rx="34" fill="#0f172a"/>
      <path d="M8 72h764v28H8z" fill="#0f172a"/>
      <text x="42" y="65" class="brand">FMTS</text>
      <text x="738" y="61" text-anchor="end" style="font:600 18px -apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;fill:#cbd5e1">ЭТИКЕТКА ОБОРУДОВАНИЯ</text>
      {name_svg}
      {site_svg}
      <rect x="178" y="{inv_y}" width="424" height="58" rx="29" fill="#eff6ff" stroke="#bfdbfe"/>
      <text x="390" y="{inv_y+20}" text-anchor="middle" class="inv-label">ИНВЕНТАРНЫЙ №</text>
      <text x="390" y="{inv_y+49}" text-anchor="middle" class="inv">{html_escape(eq.inventory_no)}</text>
      <rect x="178" y="{qr_y}" width="424" height="424" rx="28" fill="#fff" stroke="#e2e8f0" stroke-width="3"/>
      <image href="data:image/png;base64,{qr64}" x="194" y="{qr_y+16}" width="392" height="392"/>
      <text x="390" y="{qr_y+456}" text-anchor="middle" class="small">Сканируйте QR для заявки по оборудованию</text>
      <text x="390" y="{footer_y}" text-anchor="middle" style="font:500 15px -apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;fill:#94a3b8">{html_escape(eq.site.address if eq.site and eq.site.address else 'FMTS • Facility Management & Task System')}</text>
    </svg>'''
    return Response(svg,media_type="image/svg+xml",headers={"Cache-Control":"no-store"})

@router.get("/equipment/{equipment_id}/label/print", response_class=HTMLResponse)
def equipment_label_print(equipment_id:int,request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse(f"/login?next=/equipment/{equipment_id}/label/print",303)
    if not has_permission(u,"equipment.view"): return forbidden(request,db,u,"equipment.view")
    eq=db.get(Equipment,equipment_id)
    if not eq: return Response(status_code=404)
    return templates.TemplateResponse("equipment_label_print.html",ctx(request,db,eq=eq))

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

@router.get("/inventory/{item_id}", response_class=HTMLResponse)
def inventory_detail(item_id:int, request:Request, db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    if not has_permission(u,"inventory.view"): return forbidden(request,db,u,"inventory.view")
    item=db.get(InventoryItem,item_id)
    if not item:
        return Response("Позиция склада не найдена",status_code=404)

    movements=(db.query(StockMovement)
        .filter(StockMovement.item_id==item.id)
        .order_by(StockMovement.created_at.desc(),StockMovement.id.desc())
        .all())

    # Detailed warehouse history must obey the same row-level access rules as tickets.
    # Technicians see write-offs only for tickets assigned to them; operational roles
    # with ticket.list_all see the complete history.
    if not has_permission(u,"ticket.list_all"):
        movements=[m for m in movements if m.ticket is not None and can_view_ticket(u,m.ticket)]

    issue_rows=[]
    issued_qty=0.0
    issued_total=Decimal("0.00")
    ticket_groups={}
    for movement in movements:
        if movement.movement_type!="issue":
            continue
        qty=abs(float(movement.qty or 0))
        amount=movement_amount(movement)
        issued_qty+=qty
        issued_total+=amount
        issue_rows.append({
            "movement":movement,
            "qty":qty,
            "unit_cost":movement_unit_cost(movement),
            "amount":amount,
            "ticket":movement.ticket,
            "issued_by":movement.issued_by,
        })
        if movement.ticket:
            group=ticket_groups.setdefault(movement.ticket.id,{
                "ticket":movement.ticket,"qty":0.0,"amount":Decimal("0.00"),
                "count":0,"last_at":movement.created_at,
            })
            group["qty"]+=qty
            group["amount"]+=amount
            group["count"]+=1
            if movement.created_at and (not group["last_at"] or movement.created_at>group["last_at"]):
                group["last_at"]=movement.created_at

    usage_by_ticket=sorted(ticket_groups.values(),key=lambda x:x["last_at"] or datetime.min,reverse=True)
    current_value=(Decimal(str(item.qty or 0))*as_money(item.unit_cost)).quantize(Decimal("0.01"))
    stats={
        "issued_qty":issued_qty,
        "issued_total":issued_total.quantize(Decimal("0.01")),
        "ticket_count":len(ticket_groups),
        "movement_count":len(issue_rows),
        "current_value":current_value,
    }
    return templates.TemplateResponse("inventory_detail.html",ctx(
        request,db,item=item,issue_rows=issue_rows,usage_by_ticket=usage_by_ticket,stats=stats,
    ))

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
<<<<<<< HEAD
def user_new(request:Request,username:str=Form(...),full_name:str=Form(...),password:str=Form(...),role:str=Form("requester"),db:Session=Depends(get_db)):
=======
def user_new(request:Request,username:str=Form(...),full_name:str=Form(...),password:str=Form(...),role:str=Form("requester"),email:str=Form(""),phone:str=Form(""),telegram_chat_id:str=Form(""),db:Session=Depends(get_db)):
>>>>>>> c83dea0 (Первый коммит)
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    if not has_permission(u,"users.manage"): return forbidden(request,db,u,"users.manage")
    if role not in ("requester","technician","dispatcher","manager","admin"):
        return templates.TemplateResponse("forbidden.html",ctx(request,db,permission="users.manage",message="Недопустимая роль"),status_code=400)
    if len(password)<10:
        return templates.TemplateResponse("forbidden.html",ctx(request,db,permission="users.manage",message="Пароль должен содержать не менее 10 символов"),status_code=400)
    if not db.query(User).filter(User.username==username).first():
<<<<<<< HEAD
        obj=User(username=username,full_name=full_name,password_hash=hash_password(password),role=role,active=True); db.add(obj); db.commit(); db.refresh(obj)
=======
        obj=User(username=username,full_name=full_name,password_hash=hash_password(password),role=role,active=True,email=email,phone=phone,telegram_chat_id=telegram_chat_id); db.add(obj); db.commit(); db.refresh(obj)
>>>>>>> c83dea0 (Первый коммит)
        audit(db,request,u,"user.create",entity_type="user",entity_id=obj.id,details=f"{username}; role={role}")
    return RedirectResponse("/users",303)

@router.post("/users/{user_id}/update")
<<<<<<< HEAD
def user_update(user_id:int,request:Request,role:str=Form(...),active:str=Form(""),db:Session=Depends(get_db)):
=======
def user_update(user_id:int,request:Request,role:str=Form(...),active:str=Form(""),email:str=Form(""),phone:str=Form(""),telegram_chat_id:str=Form(""),db:Session=Depends(get_db)):
>>>>>>> c83dea0 (Первый коммит)
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
<<<<<<< HEAD
    target.role=role; target.active=new_active; db.commit()
=======
    target.role=role; target.active=new_active; target.email=email; target.phone=phone; target.telegram_chat_id=telegram_chat_id; db.commit()
>>>>>>> c83dea0 (Первый коммит)
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
