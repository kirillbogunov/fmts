from __future__ import annotations
import json, qrcode
from collections import defaultdict
from datetime import datetime, timedelta
from io import BytesIO
from urllib.parse import urlencode
from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse, Response, JSONResponse
from sqlalchemy.orm import Session
from app.db import get_db
from app.config import get_settings
from app.models import (User, Site, Equipment, Ticket, ServiceCatalog, CustomField, TicketCustomValue,
    KnowledgeArticle, AutomationRule, Notification, PushSubscription, TicketLink, ApprovalRequest,
    TicketFeedback, SavedFilter, ReportSubscription, TechnicianAvailability, BusinessCalendar)
from app.security import current_user, generate_totp_secret, verify_totp, totp_uri
from app.access import has_permission, can_view_ticket, scope_ticket_query
from app.routes.web import ctx, templates, forbidden
from app.services.audit import audit
from app.services.notifications import notify_user
from app.services.smart_search import rank_search
from app.services.categories import category_options

router=APIRouter()
settings=get_settings()

def user_or_login(request:Request,db:Session): return current_user(request,db)

def _require(request,db,u,perm):
    if not u: return RedirectResponse('/login',303)
    if not has_permission(u,perm): return forbidden(request,db,u,perm)
    return None

def _json(value,default):
    try: return json.loads(value or '')
    except Exception: return default

# ---------- Notifications ----------
@router.get('/notifications',response_class=HTMLResponse)
def notifications_page(request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u:return RedirectResponse('/login',303)
    denied=_require(request,db,u,'notifications.view')
    if denied:return denied
    rows=db.query(Notification).filter(Notification.user_id==u.id).order_by(Notification.id.desc()).limit(200).all()
    return templates.TemplateResponse('notifications.html',ctx(request,db,rows=rows,push_enabled=bool(settings.push_vapid_public_key)))

@router.post('/notifications/{row_id}/read')
def notification_read(row_id:int,request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u:return RedirectResponse('/login',303)
    row=db.get(Notification,row_id)
    if row and row.user_id==u.id: row.read_at=datetime.utcnow(); db.commit()
    return RedirectResponse(row.link if row and row.link else '/notifications',303)

@router.post('/notifications/read-all')
def notification_read_all(request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u:return RedirectResponse('/login',303)
    db.query(Notification).filter(Notification.user_id==u.id,Notification.read_at.is_(None)).update({'read_at':datetime.utcnow()}); db.commit()
    return RedirectResponse('/notifications',303)

@router.get('/api/push/public-key')
def push_public_key(): return {'public_key':settings.push_vapid_public_key}

@router.post('/api/push/subscribe')
async def push_subscribe(request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: raise HTTPException(401,'Требуется авторизация')
    payload=await request.json(); endpoint=str(payload.get('endpoint') or '')
    keys=payload.get('keys') or {}
    if not endpoint: raise HTTPException(400,'Нет endpoint')
    row=db.query(PushSubscription).filter(PushSubscription.user_id==u.id,PushSubscription.endpoint==endpoint).first()
    if not row: row=PushSubscription(user_id=u.id,endpoint=endpoint); db.add(row)
    row.p256dh=str(keys.get('p256dh') or ''); row.auth=str(keys.get('auth') or ''); db.commit()
    return {'ok':True}

# ---------- Knowledge base ----------
@router.get('/knowledge',response_class=HTMLResponse)
def knowledge_page(request:Request,q:str='',db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u:return RedirectResponse('/login',303)
    denied=_require(request,db,u,'knowledge.view')
    if denied:return denied
    query=db.query(KnowledgeArticle).filter(KnowledgeArticle.active==True)
    if q:
        like=f'%{q}%'; query=query.filter((KnowledgeArticle.title.ilike(like))|(KnowledgeArticle.body.ilike(like))|(KnowledgeArticle.tags.ilike(like)))
    rows=query.order_by(KnowledgeArticle.updated_at.desc()).all()
    return templates.TemplateResponse('knowledge.html',ctx(request,db,rows=rows,q=q,services=db.query(ServiceCatalog).filter(ServiceCatalog.active==True).all()))

@router.get('/knowledge/{article_id}',response_class=HTMLResponse)
def knowledge_detail(article_id:int,request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u:return RedirectResponse('/login',303)
    denied=_require(request,db,u,'knowledge.view')
    if denied:return denied
    row=db.get(KnowledgeArticle,article_id)
    if not row:return RedirectResponse('/knowledge',303)
    return templates.TemplateResponse('knowledge_detail.html',ctx(request,db,article=row))

@router.post('/knowledge/new')
def knowledge_new(request:Request,title:str=Form(...),body:str=Form(''),tags:str=Form(''),equipment_category:str=Form(''),service_id:str=Form(''),db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u:return RedirectResponse('/login',303)
    if not has_permission(u,'knowledge.manage'): return forbidden(request,db,u,'knowledge.manage')
    row=KnowledgeArticle(title=title,body=body,tags=tags,equipment_category=equipment_category,service_id=int(service_id) if service_id else None,created_by_id=u.id)
    db.add(row);db.commit();audit(db,request,u,'knowledge.create','knowledge',row.id,details=title)
    return RedirectResponse(f'/knowledge/{row.id}',303)

# ---------- Service catalog and custom forms ----------
@router.get('/services',response_class=HTMLResponse)
def services_page(request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u:return RedirectResponse('/login',303)
    denied=_require(request,db,u,'service.view')
    if denied:return denied
    rows=db.query(ServiceCatalog).order_by(ServiceCatalog.active.desc(),ServiceCatalog.name).all()
    fields=db.query(CustomField).order_by(CustomField.service_id,CustomField.sort_order,CustomField.name).all()
    grouped=defaultdict(list)
    for f in fields: grouped[f.service_id].append(f)
    return templates.TemplateResponse('services.html',ctx(request,db,rows=rows,fields_by_service=grouped,service_categories=category_options(db,'service'),sla_calendars=db.query(BusinessCalendar).filter(BusinessCalendar.active==True).order_by(BusinessCalendar.name).all()))

@router.post('/services/new')
def service_new(request:Request,code:str=Form(...),name:str=Form(...),description:str=Form(''),category:str=Form('Другое'),default_priority:str=Form('normal'),default_sla_hours:str=Form(''),db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u:return RedirectResponse('/login',303)
    if not has_permission(u,'service.manage'): return forbidden(request,db,u,'service.manage')
    row=ServiceCatalog(code=code.strip(),name=name.strip(),description=description,category=category,default_priority=default_priority,default_sla_hours=int(default_sla_hours) if default_sla_hours else None)
    db.add(row);db.commit(); return RedirectResponse('/services',303)

@router.post('/services/{service_id}/fields/new')
def service_field_new(service_id:int,request:Request,code:str=Form(...),name:str=Form(...),field_type:str=Form('text'),options:str=Form(''),required:str=Form(''),db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u:return RedirectResponse('/login',303)
    if not has_permission(u,'service.manage'): return forbidden(request,db,u,'service.manage')
    opts=[x.strip() for x in options.split('|') if x.strip()]
    db.add(CustomField(service_id=service_id,code=code.strip(),name=name.strip(),field_type=field_type,options_json=json.dumps(opts,ensure_ascii=False),required=bool(required)))
    db.commit(); return RedirectResponse('/services',303)

# ---------- Automation ----------
@router.get('/automation',response_class=HTMLResponse)
def automation_page(request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u:return RedirectResponse('/login',303)
    denied=_require(request,db,u,'automation.manage')
    if denied:return denied
    rows=db.query(AutomationRule).order_by(AutomationRule.sort_order,AutomationRule.id).all()
    return templates.TemplateResponse('automation.html',ctx(request,db,rows=rows,sites=db.query(Site).order_by(Site.name).all(),technicians=db.query(User).filter(User.role=='technician',User.active==True).all()))

@router.post('/automation/new')
def automation_new(request:Request,name:str=Form(...),category:str=Form(''),priority:str=Form(''),site_id:str=Form(''),title_contains:str=Form(''),set_priority:str=Form(''),sla_hours:str=Form(''),assign_user_id:str=Form(''),assign_least_loaded:str=Form(''),notify_manager:str=Form(''),db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u:return RedirectResponse('/login',303)
    if not has_permission(u,'automation.manage'):return forbidden(request,db,u,'automation.manage')
    cond={k:v for k,v in {'category':category,'priority':priority,'site_id':int(site_id) if site_id else None,'title_contains':title_contains}.items() if v not in ('',None)}
    act={k:v for k,v in {'set_priority':set_priority,'sla_hours':float(sla_hours) if sla_hours else None,'assign_user_id':int(assign_user_id) if assign_user_id else None,'assign_least_loaded':bool(assign_least_loaded),'notify_manager':bool(notify_manager)}.items() if v not in ('',None,False)}
    db.add(AutomationRule(name=name,conditions_json=json.dumps(cond,ensure_ascii=False),actions_json=json.dumps(act,ensure_ascii=False)));db.commit()
    return RedirectResponse('/automation',303)

@router.post('/automation/{rule_id}/toggle')
def automation_toggle(rule_id:int,request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u:return RedirectResponse('/login',303)
    if not has_permission(u,'automation.manage'):return forbidden(request,db,u,'automation.manage')
    row=db.get(AutomationRule,rule_id)
    if row: row.active=not row.active;db.commit()
    return RedirectResponse('/automation',303)

# ---------- Search / saved filters ----------
@router.get('/search',response_class=HTMLResponse)
def global_search(request:Request,q:str='',db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u:return RedirectResponse('/login',303)
    tickets=[]; equipment=[]; articles=[]
    if q:
        ticket_pool=scope_ticket_query(db.query(Ticket),u).order_by(Ticket.id.desc()).limit(2000).all()
        tickets=rank_search(q,ticket_pool,lambda t: f"{t.number} {t.title} {t.description} {t.category} {t.requester_name} {(t.site.name if t.site else '')}",50)
        if has_permission(u,'equipment.view'):
            equipment_pool=db.query(Equipment).order_by(Equipment.id.desc()).limit(2000).all()
            equipment=rank_search(q,equipment_pool,lambda e: f"{e.name} {e.inventory_no} {e.serial_no} {e.model} {e.category} {(e.site.name if e.site else '')}",50)
        if has_permission(u,'knowledge.view'):
            article_pool=db.query(KnowledgeArticle).filter(KnowledgeArticle.active==True).order_by(KnowledgeArticle.id.desc()).limit(2000).all()
            articles=rank_search(q,article_pool,lambda a: f"{a.title} {a.body} {a.tags} {a.equipment_category}",50)
    return templates.TemplateResponse('search.html',ctx(request,db,q=q,tickets=tickets,equipment=equipment,articles=articles))

@router.post('/saved-filters/new')
def saved_filter_new(request:Request,name:str=Form(...),status:str=Form(''),q:str=Form(''),priority:str=Form(''),site_id:str=Form(''),assignee_id:str=Form(''),ticket_type:str=Form(''),db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u:return RedirectResponse('/login',303)
    payload={k:v for k,v in {'status':status,'q':q,'priority':priority,'site_id':site_id,'assignee_id':assignee_id,'ticket_type':ticket_type}.items() if v}
    db.add(SavedFilter(user_id=u.id,name=name,filters_json=json.dumps(payload,ensure_ascii=False)));db.commit();return RedirectResponse('/tickets',303)

@router.get('/saved-filters/{filter_id}/apply')
def saved_filter_apply(filter_id:int,request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u:return RedirectResponse('/login',303)
    row=db.get(SavedFilter,filter_id)
    if not row or row.user_id!=u.id:return RedirectResponse('/tickets',303)
    return RedirectResponse('/tickets?'+urlencode(_json(row.filters_json,{})),303)

# ---------- Report builder ----------
@router.get('/reports/builder',response_class=HTMLResponse)
def report_builder(request:Request,group_by:str='site',days:int=30,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u:return RedirectResponse('/login',303)
    denied=_require(request,db,u,'report.builder')
    if denied:return denied
    since=datetime.utcnow()-timedelta(days=max(1,min(days,3650)))
    rows=scope_ticket_query(db.query(Ticket),u).filter(Ticket.created_at>=since).all()
    agg={}
    for t in rows:
        if group_by=='category': key=t.category or '—'
        elif group_by=='status': key=t.status or '—'
        elif group_by=='assignee': key=t.assignee.full_name if t.assignee else 'Не назначен'
        elif group_by=='equipment_category': key=t.equipment.category if t.equipment else 'Без оборудования'
        else: key=t.site.name if t.site else '—'
        x=agg.setdefault(key,{'name':key,'count':0,'closed':0,'overdue':0,'labor':0.0,'parts':0.0,'hours':0.0})
        x['count']+=1; x['closed']+=int(t.status in {'resolved','closed'}); x['overdue']+=int(bool(t.sla_due_at and t.sla_due_at<datetime.utcnow() and t.status not in {'resolved','closed','cancelled','waiting'}))
        if has_permission(u,'ticket.cost'): x['labor']+=float(t.labor_cost or 0);x['parts']+=float(t.parts_cost or 0)
        x['hours']+=sum(float(ws.duration_seconds or 0) for ws in t.work_sessions)/3600
    data=sorted(agg.values(),key=lambda x:(-x['count'],x['name']))
    return templates.TemplateResponse('report_builder.html',ctx(request,db,rows=data,group_by=group_by,days=days))

@router.post('/reports/subscriptions/new')
def report_subscription_new(request:Request,name:str=Form(...),group_by:str=Form('site'),periodicity:str=Form('monthly'),db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u:return RedirectResponse('/login',303)
    if not has_permission(u,'report.builder'):return forbidden(request,db,u,'report.builder')
    db.add(ReportSubscription(user_id=u.id,name=name,config_json=json.dumps({'group_by':group_by}),periodicity=periodicity));db.commit()
    return RedirectResponse(f'/reports/builder?group_by={group_by}',303)

# ---------- Ticket links, custom fields, approvals, feedback ----------
@router.post('/tickets/{ticket_id}/links')
def ticket_link_add(ticket_id:int,request:Request,linked_ticket_no:str=Form(...),link_type:str=Form('related'),db:Session=Depends(get_db)):
    u=user_or_login(request,db); t=db.get(Ticket,ticket_id)
    if not u:return RedirectResponse('/login',303)
    if not t or not can_view_ticket(u,t,db) or not has_permission(u,'ticket.link'):return forbidden(request,db,u,'ticket.link')
    other=db.query(Ticket).filter(Ticket.number==linked_ticket_no.strip()).first()
    if not other or not can_view_ticket(u,other,db) or other.id==t.id:return RedirectResponse(f'/tickets/{t.id}',303)
    exists=db.query(TicketLink).filter(TicketLink.ticket_id==t.id,TicketLink.linked_ticket_id==other.id).first()
    if not exists:db.add(TicketLink(ticket_id=t.id,linked_ticket_id=other.id,link_type=link_type,created_by_id=u.id));db.commit()
    return RedirectResponse(f'/tickets/{t.id}#enterprise-ticket',303)

@router.post('/tickets/{ticket_id}/custom-fields')
async def ticket_custom_fields(ticket_id:int,request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db);t=db.get(Ticket,ticket_id)
    if not u:return RedirectResponse('/login',303)
    if not t or not can_view_ticket(u,t,db):return forbidden(request,db,u,'ticket.view')
    if u.role=='requester' and t.requester_id!=u.id:return forbidden(request,db,u,'ticket.view')
    form=await request.form()
    fields=db.query(CustomField).filter(CustomField.active==True,((CustomField.service_id==t.service_id)|(CustomField.service_id.is_(None)))).all()
    for f in fields:
        value=str(form.get(f'field_{f.id}','')).strip()
        if f.required and not value:
            return templates.TemplateResponse('forbidden.html',ctx(request,db,permission='ticket.custom_fields',message=f'Поле «{f.name}» обязательно'),status_code=400)
        row=db.query(TicketCustomValue).filter(TicketCustomValue.ticket_id==t.id,TicketCustomValue.field_id==f.id).first()
        if not row: row=TicketCustomValue(ticket_id=t.id,field_id=f.id);db.add(row)
        row.value=value
    db.commit();return RedirectResponse(f'/tickets/{t.id}#enterprise-ticket',303)

@router.post('/tickets/{ticket_id}/approvals')
def approval_new(ticket_id:int,request:Request,approver_id:str=Form(''),comment:str=Form(''),db:Session=Depends(get_db)):
    u=user_or_login(request,db);t=db.get(Ticket,ticket_id)
    if not u:return RedirectResponse('/login',303)
    if not t or not can_view_ticket(u,t,db) or not has_permission(u,'approval.request'):return forbidden(request,db,u,'approval.request')
    approver=db.get(User,int(approver_id)) if approver_id else db.query(User).filter(User.active==True,User.role.in_(['manager','admin'])).order_by(User.role).first()
    if not approver:return RedirectResponse(f'/tickets/{t.id}',303)
    row=ApprovalRequest(ticket_id=t.id,requested_by_id=u.id,approver_id=approver.id,comment=comment);db.add(row);db.flush()
    notify_user(db,approver,f'Требуется согласование {t.number}',comment or t.title,f'/tickets/{t.id}',dedup_key=f'approval:{row.id}')
    db.commit();return RedirectResponse(f'/tickets/{t.id}#enterprise-ticket',303)

@router.post('/approvals/{approval_id}/decide')
def approval_decide(approval_id:int,request:Request,decision:str=Form(...),comment:str=Form(''),db:Session=Depends(get_db)):
    u=user_or_login(request,db); row=db.get(ApprovalRequest,approval_id)
    if not u:return RedirectResponse('/login',303)
    if not row or not has_permission(u,'approval.decide'):return forbidden(request,db,u,'approval.decide')
    if row.approver_id and row.approver_id!=u.id and u.role!='admin':return forbidden(request,db,u,'approval.decide')
    row.status='approved' if decision=='approve' else 'rejected'; row.decided_at=datetime.utcnow(); row.comment=(row.comment+'\n'+comment).strip();db.commit()
    if row.requested_by_id:notify_user(db,db.get(User,row.requested_by_id),f'Согласование {row.status}',f'Заявка #{row.ticket_id}',f'/tickets/{row.ticket_id}') ; db.commit()
    return RedirectResponse(f'/tickets/{row.ticket_id}#enterprise-ticket',303)

@router.post('/tickets/{ticket_id}/feedback')
def ticket_feedback(ticket_id:int,request:Request,rating:int=Form(...),comment:str=Form(''),db:Session=Depends(get_db)):
    u=user_or_login(request,db);t=db.get(Ticket,ticket_id)
    if not u:return RedirectResponse('/login',303)
    if not t or not can_view_ticket(u,t,db) or not has_permission(u,'feedback.create'):return forbidden(request,db,u,'feedback.create')
    if t.status not in {'resolved','closed'}:return RedirectResponse(f'/tickets/{t.id}',303)
    rating=max(1,min(5,rating)); row=db.query(TicketFeedback).filter(TicketFeedback.ticket_id==t.id,TicketFeedback.user_id==u.id).first()
    if not row: row=TicketFeedback(ticket_id=t.id,user_id=u.id);db.add(row)
    row.rating=rating;row.comment=comment;db.commit();return RedirectResponse(f'/tickets/{t.id}#enterprise-ticket',303)

# ---------- 2FA ----------
@router.post('/profile/2fa/setup')
def profile_2fa_setup(request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u:return RedirectResponse('/login',303)
    u.totp_secret=generate_totp_secret();u.totp_enabled=False;db.commit();return RedirectResponse('/profile',303)

@router.get('/profile/2fa/qr.png')
def profile_2fa_qr(request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u or not u.totp_secret:raise HTTPException(404)
    qr=qrcode.QRCode(box_size=8,border=2);qr.add_data(totp_uri(u.totp_secret,u.username,settings.app_name));qr.make(fit=True);img=qr.make_image(fill_color='black',back_color='white');bio=BytesIO();img.save(bio,format='PNG')
    return Response(bio.getvalue(),media_type='image/png')

@router.post('/profile/2fa/enable')
def profile_2fa_enable(request:Request,code:str=Form(...),db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u:return RedirectResponse('/login',303)
    if u.totp_secret and verify_totp(u.totp_secret,code):u.totp_enabled=True;db.commit();audit(db,request,u,'auth.2fa_enable','user',u.id)
    return RedirectResponse('/profile',303)

@router.post('/profile/2fa/disable')
def profile_2fa_disable(request:Request,code:str=Form(...),db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u:return RedirectResponse('/login',303)
    if verify_totp(u.totp_secret,code):u.totp_enabled=False;u.totp_secret='';db.commit();audit(db,request,u,'auth.2fa_disable','user',u.id)
    return RedirectResponse('/profile',303)

# ---------- Technician schedule ----------
@router.get('/team/schedule',response_class=HTMLResponse)
def team_schedule(request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u:return RedirectResponse('/login',303)
    if u.role not in {'dispatcher','manager','admin'}:return forbidden(request,db,u,'schedule.view')
    techs=db.query(User).filter(User.role=='technician',User.active==True).order_by(User.full_name).all(); rows=db.query(TechnicianAvailability).all()
    return templates.TemplateResponse('team_schedule.html',ctx(request,db,technicians=techs,rows=rows))

@router.post('/team/schedule/save')
def team_schedule_save(request:Request,user_id:int=Form(...),weekday:int=Form(...),start_time:str=Form('09:00'),end_time:str=Form('18:00'),available:str=Form(''),db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u:return RedirectResponse('/login',303)
    if u.role not in {'dispatcher','manager','admin'}:return forbidden(request,db,u,'schedule.manage')
    row=db.query(TechnicianAvailability).filter(TechnicianAvailability.user_id==user_id,TechnicianAvailability.weekday==weekday).first()
    if not row:row=TechnicianAvailability(user_id=user_id,weekday=weekday);db.add(row)
    row.start_time=start_time;row.end_time=end_time;row.available=bool(available);db.commit();return RedirectResponse('/team/schedule',303)
