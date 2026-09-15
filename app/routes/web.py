from __future__ import annotations
import csv, io, json, os, secrets
from datetime import datetime, date, timedelta
from pathlib import Path
from decimal import Decimal
from fastapi import APIRouter, Depends, Request, Form, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session
import qrcode
from io import BytesIO
from app.db import get_db
from app.config import get_settings
from app.models import User, Site, Equipment, Ticket, TicketComment, Attachment, MaintenancePlan, InventoryItem, StockMovement, Contractor, UiStyle
from app.security import verify_password, current_user, hash_password
from app.services.maintenance import next_ticket_number, generate_due_maintenance
from app.services.one_c import OneCClient
from app.services.sync import push_ticket_to_1c
from app.labels import STATUS_LABELS, PRIORITY_LABELS, ROLE_LABELS, EQUIPMENT_STATUS_LABELS
from app.services.ui_styles import styles_cache, badge_css, display_name, options_for, sla_hours_for
from app.services.reference_data import ensure_default_reference_data
from app.services.urls import public_url
from app.services.kpi import calculate_monthly_kpi, parse_period, shift_month

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
          "ui_name":lambda kind,code,fallback=None: display_name(ui,kind,code,fallback)}
    base.update(extra); return base

@router.get("/login", response_class=HTMLResponse)
def login_page(request:Request, db:Session=Depends(get_db)):
    if current_user(request,db): return RedirectResponse("/",303)
    return templates.TemplateResponse("login.html",ctx(request,db,error=None))

@router.post("/login")
def login(request:Request, username:str=Form(...), password:str=Form(...), db:Session=Depends(get_db)):
    u=db.query(User).filter(User.username==username,User.active==True).first()
    if not u or not verify_password(password,u.password_hash):
        return templates.TemplateResponse("login.html",ctx(request,db,error="Неверный логин или пароль"),status_code=401)
    request.session["user_id"]=u.id
    return RedirectResponse("/",303)

@router.get("/logout")
def logout(request:Request):
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
    return templates.TemplateResponse("profile.html",ctx(request,db,message="Пароль изменён",ok=True))

@router.get("/", response_class=HTMLResponse)
def dashboard(request:Request, db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    now=datetime.utcnow()
    open_status=["new","assigned","in_progress","waiting"]
    data={
        "open_count":db.query(Ticket).filter(Ticket.status.in_(open_status)).count(),
        "overdue":db.query(Ticket).filter(Ticket.status.in_(open_status),Ticket.sla_due_at < now).count(),
        "equipment_count":db.query(Equipment).count(),
        "due_maintenance":db.query(MaintenancePlan).filter(MaintenancePlan.active==True,MaintenancePlan.next_run<=date.today()+timedelta(days=7)).count(),
        "low_stock":db.query(InventoryItem).filter(InventoryItem.qty<=InventoryItem.min_qty).count(),
        "recent":db.query(Ticket).order_by(Ticket.id.desc()).limit(8).all(),
        "by_status":db.query(Ticket.status,func.count(Ticket.id)).group_by(Ticket.status).all(),
    }
    return templates.TemplateResponse("dashboard.html",ctx(request,db,**data))


@router.get("/reports/kpi", response_class=HTMLResponse)
def kpi_report(request:Request, month:str="", db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    if u.role not in ("admin","dispatcher","manager","technician"):
        return RedirectResponse("/",303)
    period=parse_period(month)
    technician_ids=[u.id] if u.role=="technician" else None
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
    if u.role not in ("admin","dispatcher","manager","technician"):
        return RedirectResponse("/",303)
    period=parse_period(month)
    technician_ids=[u.id] if u.role=="technician" else None
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
        "Просрочено при выполнении","Открытый хвост сейчас","Просрочено сейчас"
    ])
    for row in report["rows"]:
        writer.writerow([
            row["rank"] or "",row["name"],str(row["score"]).replace('.',','),str(row["rating"]).replace('.',','),
            row["handled"],row["completed"],str(row["points"]).replace('.',','),str(row["sla_rate"]).replace('.',','),
            str(row["closure_rate"]).replace('.',','),str(row["productivity_rate"]).replace('.',','),
            str(row["documentation_rate"]).replace('.',','),str(row["avg_resolution_hours"]).replace('.',','),
            row["overdue_completed"],row["open_backlog"],row["overdue_open"],
        ])
    payload=('\ufeff'+out.getvalue()).encode('utf-8')
    headers={"Content-Disposition": f'attachment; filename="FMTS_KPI_{period.value}.csv"'}
    return Response(content=payload,media_type="text/csv; charset=utf-8",headers=headers)

@router.get("/tickets", response_class=HTMLResponse)
def tickets(request:Request,status:str="",q:str="",db:Session=Depends(get_db)):
    if not user_or_login(request,db): return RedirectResponse("/login",303)
    query=db.query(Ticket)
    if status: query=query.filter(Ticket.status==status)
    if q: query=query.filter((Ticket.title.contains(q)) | (Ticket.number.contains(q)))
    rows=query.order_by(Ticket.id.desc()).all()
    return templates.TemplateResponse("tickets.html",ctx(request,db,tickets=rows,status=status,q=q,status_options=options_for(db,"status",list(STATUS_LABELS.items()))))

@router.get("/tickets/new", response_class=HTMLResponse)
def ticket_new(request:Request,equipment_id:int|None=None,db:Session=Depends(get_db)):
    if not user_or_login(request,db): return RedirectResponse("/login",303)
    return templates.TemplateResponse("ticket_form.html",ctx(request,db,sites=db.query(Site).order_by(Site.name).all(),equipment=db.query(Equipment).order_by(Equipment.name).all(),users=db.query(User).filter(User.role.in_(["technician","dispatcher","admin"])).all(),selected_equipment_id=equipment_id,categories=options_for(db,"category",[(x,x) for x in ["Электрика","Сантехника","Мебель","Отделка","Кондиционер","Окна","Двери","Компьютер","Другое"]]),priority_options=options_for(db,"priority",list(PRIORITY_LABELS.items()))))

@router.post("/tickets/new")
def ticket_create(request:Request,title:str=Form(...),description:str=Form(""),category:str=Form("Другое"),priority:str=Form("normal"),site_id:int=Form(...),equipment_id:str=Form(""),assignee_id:str=Form(""),room:str=Form(""),phone:str=Form(""),attachment:UploadFile|None=File(None),db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    sla_hours=sla_hours_for(db,priority)
    t=Ticket(number=next_ticket_number(db),title=title,description=description,category=category,priority=priority,status="new",site_id=site_id,
             equipment_id=int(equipment_id) if equipment_id else None,requester_id=u.id,requester_name=u.full_name,requester_phone=phone,room=room,
             assignee_id=int(assignee_id) if assignee_id else None,master_name="",sla_due_at=datetime.utcnow()+timedelta(hours=sla_hours))
    if t.assignee_id: t.status="assigned"
    db.add(t); db.flush()
    if attachment and attachment.filename:
        Path(settings.upload_dir).mkdir(parents=True,exist_ok=True)
        ext=Path(attachment.filename).suffix
        stored=f"{secrets.token_hex(16)}{ext}"
        with open(Path(settings.upload_dir)/stored,"wb") as f: f.write(attachment.file.read())
        db.add(Attachment(ticket_id=t.id,filename=attachment.filename,stored_name=stored))
    db.commit(); db.refresh(t); push_ticket_to_1c(db,t); return RedirectResponse(f"/tickets/{t.id}",303)

@router.get("/tickets/{ticket_id}", response_class=HTMLResponse)
def ticket_detail(ticket_id:int,request:Request,db:Session=Depends(get_db)):
    if not user_or_login(request,db): return RedirectResponse("/login",303)
    t=db.get(Ticket,ticket_id)
    if not t: return RedirectResponse("/tickets",303)
    return templates.TemplateResponse("ticket_detail.html",ctx(request,db,ticket=t,users=db.query(User).filter(User.role.in_(["technician","dispatcher","admin"])).all(),contractors=db.query(Contractor).all(),inventory=db.query(InventoryItem).order_by(InventoryItem.name).all(),status_options=options_for(db,"status",list(STATUS_LABELS.items()))))

@router.post("/tickets/{ticket_id}/update")
def ticket_update(ticket_id:int,request:Request,status:str=Form(...),assignee_id:str=Form(""),contractor_id:str=Form(""),labor_cost:float=Form(0),master_comment:str=Form(""),db:Session=Depends(get_db)):
    if not user_or_login(request,db): return RedirectResponse("/login",303)
    t=db.get(Ticket,ticket_id)
    if t:
        t.status=status; t.assignee_id=int(assignee_id) if assignee_id else None; t.contractor_id=int(contractor_id) if contractor_id else None; t.labor_cost=Decimal(str(labor_cost or 0)); t.master_comment=master_comment; t.master_name=t.assignee.full_name if t.assignee else t.master_name; t.updated_at=datetime.utcnow()
        if status in ("resolved","closed") and not t.resolved_at:
            t.resolved_at=datetime.utcnow()
        elif status not in ("resolved","closed") and t.resolved_at:
            # Reopened ticket: final completion time must be recalculated for SLA/KPI.
            t.resolved_at=None
        db.commit(); db.refresh(t); push_ticket_to_1c(db,t)
    return RedirectResponse(f"/tickets/{ticket_id}",303)

@router.post("/tickets/{ticket_id}/comment")
def ticket_comment(ticket_id:int,request:Request,body:str=Form(...),db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    db.add(TicketComment(ticket_id=ticket_id,user_id=u.id,body=body)); db.commit()
    return RedirectResponse(f"/tickets/{ticket_id}",303)

@router.post("/tickets/{ticket_id}/stock")
def ticket_stock(ticket_id:int,request:Request,item_id:int=Form(...),qty:float=Form(...),db:Session=Depends(get_db)):
    if not user_or_login(request,db): return RedirectResponse("/login",303)
    item=db.get(InventoryItem,item_id); t=db.get(Ticket,ticket_id)
    if item and t and qty>0:
        item.qty-=qty; db.add(StockMovement(item_id=item.id,ticket_id=t.id,movement_type="issue",qty=-qty,comment=f"Списание в {t.number}")); t.parts_cost=Decimal(str(float(t.parts_cost or 0)+qty*float(item.unit_cost or 0))); db.commit(); db.refresh(t); push_ticket_to_1c(db,t)
    return RedirectResponse(f"/tickets/{ticket_id}",303)


@router.get("/sites", response_class=HTMLResponse)
def sites_page(request:Request,db:Session=Depends(get_db)):
    if not user_or_login(request,db): return RedirectResponse("/login",303)
    rows=db.query(Site).order_by(Site.name).all()
    return templates.TemplateResponse("sites.html",ctx(request,db,sites=rows))

@router.post("/sites/new")
def site_new(request:Request,name:str=Form(...),address:str=Form(""),db:Session=Depends(get_db)):
    if not user_or_login(request,db): return RedirectResponse("/login",303)
    if not db.query(Site).filter(Site.name==name).first():
        db.add(Site(name=name,address=address)); db.commit()
    return RedirectResponse("/sites",303)

@router.get("/equipment", response_class=HTMLResponse)
def equipment_list(request:Request,site_id:int|None=None,db:Session=Depends(get_db)):
    if not user_or_login(request,db): return RedirectResponse("/login",303)
    q=db.query(Equipment)
    if site_id: q=q.filter(Equipment.site_id==site_id)
    return templates.TemplateResponse("equipment.html",ctx(request,db,equipment=q.order_by(Equipment.name).all(),sites=db.query(Site).order_by(Site.name).all(),site_id=site_id))


@router.get("/equipment/new", response_class=HTMLResponse)
def equipment_new_page(request:Request,db:Session=Depends(get_db)):
    if not user_or_login(request,db): return RedirectResponse("/login",303)
    return templates.TemplateResponse("equipment_form.html",ctx(request,db,sites=db.query(Site).order_by(Site.name).all(),status_options=options_for(db,"equipment_status",list(EQUIPMENT_STATUS_LABELS.items()))))

@router.post("/equipment/new")
def equipment_new(request:Request,site_id:int=Form(...),name:str=Form(...),inventory_no:str=Form(...),category:str=Form("Прочее"),model:str=Form(""),serial_no:str=Form(""),status:str=Form("working"),db:Session=Depends(get_db)):
    if not user_or_login(request,db): return RedirectResponse("/login",303)
    if db.query(Equipment).filter(Equipment.inventory_no==inventory_no).first():
        return RedirectResponse("/equipment",303)
    eq=Equipment(site_id=site_id,name=name,inventory_no=inventory_no,category=category,model=model,serial_no=serial_no,status=status,qr_token=secrets.token_urlsafe(24))
    db.add(eq); db.commit(); return RedirectResponse(f"/equipment/{eq.id}",303)

@router.get("/equipment/{equipment_id}", response_class=HTMLResponse)
def equipment_detail(equipment_id:int,request:Request,db:Session=Depends(get_db)):
    if not user_or_login(request,db): return RedirectResponse("/login",303)
    eq=db.get(Equipment,equipment_id)
    if not eq: return RedirectResponse("/equipment",303)
    history=db.query(Ticket).filter(Ticket.equipment_id==eq.id).order_by(Ticket.id.desc()).all()
    plans=db.query(MaintenancePlan).filter(MaintenancePlan.equipment_id==eq.id).all()
    total=sum(float(x.labor_cost or 0)+float(x.parts_cost or 0) for x in history)
    return templates.TemplateResponse("equipment_detail.html",ctx(request,db,eq=eq,history=history,plans=plans,total_cost=total))

@router.get("/equipment/{equipment_id}/qr.png")
def equipment_qr(equipment_id:int,request:Request,db:Session=Depends(get_db)):
    eq=db.get(Equipment,equipment_id)
    if not eq: return Response(status_code=404)
    url=public_url(request, settings, f"/scan/{eq.qr_token}")
    img=qrcode.make(url); bio=BytesIO(); img.save(bio,format="PNG")
    return Response(bio.getvalue(),media_type="image/png")

@router.get("/scan/{token}")
def scan_equipment(token:str,db:Session=Depends(get_db)):
    eq=db.query(Equipment).filter(Equipment.qr_token==token).first()
    if not eq: return RedirectResponse("/",303)
    return RedirectResponse(f"/tickets/new?equipment_id={eq.id}",303)

@router.get("/maintenance", response_class=HTMLResponse)
def maintenance(request:Request,db:Session=Depends(get_db)):
    if not user_or_login(request,db): return RedirectResponse("/login",303)
    plans=db.query(MaintenancePlan).order_by(MaintenancePlan.next_run).all()
    return templates.TemplateResponse("maintenance.html",ctx(request,db,plans=plans,equipment=db.query(Equipment).order_by(Equipment.name).all(),users=db.query(User).filter(User.role.in_(["technician","admin"])).all()))

@router.post("/maintenance/new")
def maintenance_new(request:Request,equipment_id:int=Form(...),name:str=Form(...),interval_days:int=Form(30),next_run:str=Form(...),assignee_id:str=Form(""),checklist:str=Form(""),db:Session=Depends(get_db)):
    if not user_or_login(request,db): return RedirectResponse("/login",303)
    items=[x.strip() for x in checklist.splitlines() if x.strip()]
    db.add(MaintenancePlan(equipment_id=equipment_id,name=name,interval_days=interval_days,next_run=date.fromisoformat(next_run),assignee_id=int(assignee_id) if assignee_id else None,checklist=json.dumps(items,ensure_ascii=False))); db.commit()
    return RedirectResponse("/maintenance",303)

@router.post("/maintenance/generate")
def maintenance_gen(request:Request,db:Session=Depends(get_db)):
    if not user_or_login(request,db): return RedirectResponse("/login",303)
    generate_due_maintenance(db); return RedirectResponse("/maintenance",303)

@router.get("/inventory", response_class=HTMLResponse)
def inventory(request:Request,db:Session=Depends(get_db)):
    if not user_or_login(request,db): return RedirectResponse("/login",303)
    return templates.TemplateResponse("inventory.html",ctx(request,db,items=db.query(InventoryItem).order_by(InventoryItem.name).all()))

@router.post("/inventory/new")
def inventory_new(request:Request,sku:str=Form(...),name:str=Form(...),qty:float=Form(0),min_qty:float=Form(0),unit:str=Form("шт"),unit_cost:float=Form(0),db:Session=Depends(get_db)):
    if not user_or_login(request,db): return RedirectResponse("/login",303)
    db.add(InventoryItem(sku=sku,name=name,qty=qty,min_qty=min_qty,unit=unit,unit_cost=Decimal(str(unit_cost or 0)))); db.commit(); return RedirectResponse("/inventory",303)

@router.get("/contractors", response_class=HTMLResponse)
def contractors(request:Request,db:Session=Depends(get_db)):
    if not user_or_login(request,db): return RedirectResponse("/login",303)
    return templates.TemplateResponse("contractors.html",ctx(request,db,contractors=db.query(Contractor).order_by(Contractor.name).all()))

@router.post("/contractors/new")
def contractor_new(request:Request,name:str=Form(...),phone:str=Form(""),email:str=Form(""),specialization:str=Form(""),db:Session=Depends(get_db)):
    if not user_or_login(request,db): return RedirectResponse("/login",303)
    db.add(Contractor(name=name,phone=phone,email=email,specialization=specialization)); db.commit(); return RedirectResponse("/contractors",303)


@router.get("/users", response_class=HTMLResponse)
def users_page(request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    if u.role!="admin": return RedirectResponse("/",303)
    return templates.TemplateResponse("users.html",ctx(request,db,users=db.query(User).order_by(User.full_name).all()))

@router.post("/users/new")
def user_new(request:Request,username:str=Form(...),full_name:str=Form(...),password:str=Form(...),role:str=Form("requester"),db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u or u.role!="admin": return RedirectResponse("/",303)
    if not db.query(User).filter(User.username==username).first():
        db.add(User(username=username,full_name=full_name,password_hash=hash_password(password),role=role,active=True)); db.commit()
    return RedirectResponse("/users",303)

@router.get("/integration", response_class=HTMLResponse)
def integration(request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    c=OneCClient()
    return templates.TemplateResponse("integration.html",ctx(request,db,settings=settings,status=c.health()))

@router.get("/settings/reference-data", response_class=HTMLResponse)
def reference_settings(request:Request, db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: return RedirectResponse("/login",303)
    if u.role != "admin": return RedirectResponse("/",303)
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
    if not u or u.role != "admin": return RedirectResponse("/",303)
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
    if not u or u.role != "admin": return RedirectResponse("/",303)
    kind=kind.strip(); code=code.strip(); name=name.strip()
    if kind == "category" and code and not db.query(UiStyle).filter(UiStyle.kind==kind,UiStyle.code==code).first():
        try: sla=int(sla_hours) if sla_hours.strip() else None
        except Exception: sla=None
        db.add(UiStyle(kind=kind,code=code,name=name or code,bg_color=bg_color,text_color=text_color,border_color=border_color,sla_hours=sla,sort_order=sort_order,active=True))
        db.commit()
    return RedirectResponse("/settings/reference-data?message=Добавлено",303)
