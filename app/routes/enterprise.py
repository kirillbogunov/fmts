from __future__ import annotations
import json, qrcode, mimetypes, secrets, csv, io
from collections import defaultdict
from datetime import datetime, timedelta, date
from io import BytesIO
from pathlib import Path
from urllib.parse import urlencode
from fastapi import APIRouter, Depends, Request, Form, HTTPException, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse, Response, JSONResponse, FileResponse
from sqlalchemy.orm import Session
from app.db import get_db
from app.config import get_settings
from app.models import (User, Site, Equipment, Ticket, ServiceCatalog, CustomField, TicketCustomValue,
    KnowledgeArticle, KnowledgeAttachment, AutomationRule, Notification, PushSubscription, TicketLink, ApprovalRequest,
    TicketFeedback, SavedFilter, ReportSubscription, TechnicianAvailability, TechnicianAvailabilityException, BusinessCalendar, SupportGroup)
from app.security import current_user, generate_totp_secret, verify_totp, totp_uri
from app.access import has_permission, can_view_ticket, scope_ticket_query
from app.routes.web import ctx, templates, forbidden
from app.services.audit import audit
from app.services.notifications import notify_user, send_webpush
from app.services.smart_search import rank_search
from app.services.categories import category_options
from app.labels import STATUS_LABELS

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
    return templates.TemplateResponse('notifications.html',ctx(request,db,rows=rows,push_enabled=bool(settings.push_vapid_public_key and settings.push_vapid_private_key)))

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
def push_public_key():
    return {'public_key':settings.push_vapid_public_key if settings.push_vapid_private_key else ''}

@router.get('/api/push/status')
def push_status(request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: raise HTTPException(401,'Требуется авторизация')
    rows=db.query(PushSubscription).filter(PushSubscription.user_id==u.id,PushSubscription.active==True).all()
    return {
        'configured':bool(settings.push_vapid_public_key and settings.push_vapid_private_key),
        'enabled':bool(u.push_enabled),
        'devices':len(rows),
        'subscriptions':[{'id':x.id,'device_name':x.device_name or 'Устройство','updated_at':x.updated_at.isoformat() if x.updated_at else None} for x in rows],
    }

@router.post('/api/push/subscribe')
async def push_subscribe(request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: raise HTTPException(401,'Требуется авторизация')
    if not (settings.push_vapid_public_key and settings.push_vapid_private_key):
        raise HTTPException(503,'Web Push не настроен администратором')
    payload=await request.json(); endpoint=str(payload.get('endpoint') or '').strip()
    keys=payload.get('keys') or {}
    if not endpoint: raise HTTPException(400,'Нет endpoint')
    p256dh=str(keys.get('p256dh') or '').strip(); auth=str(keys.get('auth') or '').strip()
    if not (p256dh and auth): raise HTTPException(400,'Нет ключей push-подписки')
    row=db.query(PushSubscription).filter(PushSubscription.user_id==u.id,PushSubscription.endpoint==endpoint).first()
    if not row: row=PushSubscription(user_id=u.id,endpoint=endpoint); db.add(row)
    row.p256dh=p256dh; row.auth=auth
    row.device_name=str(payload.get('device_name') or 'Телефон / браузер')[:160]
    row.user_agent=str(request.headers.get('user-agent') or '')[:1000]
    row.active=True; row.updated_at=datetime.utcnow(); u.push_enabled=True
    db.commit(); db.refresh(row)
    audit(db,request,u,'push.subscribe',entity_type='push_subscription',entity_id=row.id,details=row.device_name)
    return {'ok':True,'id':row.id,'device_name':row.device_name}

@router.post('/api/push/unsubscribe')
async def push_unsubscribe(request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: raise HTTPException(401,'Требуется авторизация')
    payload=await request.json(); endpoint=str(payload.get('endpoint') or '').strip()
    if endpoint:
        rows=db.query(PushSubscription).filter(PushSubscription.user_id==u.id,PushSubscription.endpoint==endpoint).all()
        for row in rows: db.delete(row)
        db.commit()
    return {'ok':True}

@router.post('/api/push/subscriptions/{subscription_id}/delete')
def push_subscription_delete(subscription_id:int,request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: raise HTTPException(401,'Требуется авторизация')
    row=db.get(PushSubscription,subscription_id)
    if row and row.user_id==u.id:
        db.delete(row); db.commit(); audit(db,request,u,'push.unsubscribe',entity_type='push_subscription',entity_id=subscription_id)
    return RedirectResponse('/profile#push-settings',303)

@router.post('/api/push/test')
def push_test(request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u: raise HTTPException(401,'Требуется авторизация')
    rows=db.query(PushSubscription).filter(PushSubscription.user_id==u.id,PushSubscription.active==True).all()
    if not rows: raise HTTPException(400,'Сначала включите push на этом устройстве')
    sent=0
    for row in rows:
        if send_webpush(row,'FMTS · тест push','Уведомления на телефон работают.','/notifications','info'): sent+=1
    db.commit()
    if not sent: raise HTTPException(502,'Не удалось доставить тестовый push. Проверьте VAPID и разрешение браузера.')
    return {'ok':True,'sent':sent}

@router.post('/profile/push-preferences')
def profile_push_preferences(
    request:Request,
    push_enabled:str=Form(''),push_assignments:str=Form(''),push_comments:str=Form(''),push_status:str=Form(''),
    push_sla:str=Form(''),push_maintenance:str=Form(''),push_reminders:str=Form(''),push_inventory:str=Form(''),
    push_general:str=Form(''),push_quiet_start:str=Form(''),push_quiet_end:str=Form(''),db:Session=Depends(get_db)
):
    u=user_or_login(request,db)
    if not u:return RedirectResponse('/login',303)
    u.push_enabled=push_enabled=='1'; u.push_assignments=push_assignments=='1'; u.push_comments=push_comments=='1'; u.push_status=push_status=='1'
    u.push_sla=push_sla=='1'; u.push_maintenance=push_maintenance=='1'; u.push_reminders=push_reminders=='1'; u.push_inventory=push_inventory=='1'; u.push_general=push_general=='1'
    def clean_time(value:str)->str:
        value=(value or '').strip();
        if not value:return ''
        try: datetime.strptime(value,'%H:%M'); return value
        except Exception:return ''
    u.push_quiet_start=clean_time(push_quiet_start); u.push_quiet_end=clean_time(push_quiet_end)
    db.commit(); audit(db,request,u,'push.preferences',entity_type='user',entity_id=u.id)
    return RedirectResponse('/profile#push-settings',303)

# ---------- Knowledge base ----------
KNOWLEDGE_EXTENSIONS={'.docx','.pdf','.png','.jpg','.jpeg','.webp','.gif'}
KNOWLEDGE_MAX_BYTES=20*1024*1024

def _save_knowledge_file(upload:UploadFile) -> tuple[str,str,str,int]:
    filename=Path(upload.filename or 'file').name[:255]; ext=Path(filename).suffix.lower()
    if ext not in KNOWLEDGE_EXTENSIONS: raise ValueError('Разрешены DOCX, PDF, PNG, JPG, WEBP и GIF')
    data=upload.file.read(KNOWLEDGE_MAX_BYTES+1)
    if not data: raise ValueError('Пустой файл')
    if len(data)>KNOWLEDGE_MAX_BYTES: raise ValueError('Файл превышает 20 МБ')
    folder=Path(settings.upload_dir)/'knowledge'; folder.mkdir(parents=True,exist_ok=True)
    stored=f"{secrets.token_hex(18)}{ext}"; (folder/stored).write_bytes(data)
    mime=mimetypes.guess_type(filename)[0] or 'application/octet-stream'
    return filename,f'knowledge/{stored}',mime,len(data)

def _knowledge_path(row:KnowledgeAttachment)->Path|None:
    root=Path(settings.upload_dir).resolve(); path=(root/row.stored_name).resolve()
    if root not in path.parents or not path.exists(): return None
    return path

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
    return templates.TemplateResponse('knowledge_detail.html',ctx(request,db,article=row,knowledge_files=db.query(KnowledgeAttachment).filter(KnowledgeAttachment.article_id==row.id).order_by(KnowledgeAttachment.created_at.desc()).all()))

@router.post('/knowledge/new')
def knowledge_new(request:Request,title:str=Form(...),body:str=Form(''),tags:str=Form(''),equipment_category:str=Form(''),service_id:str=Form(''),files:list[UploadFile]|None=File(None),db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u:return RedirectResponse('/login',303)
    if not has_permission(u,'knowledge.manage'): return forbidden(request,db,u,'knowledge.manage')
    row=KnowledgeArticle(title=title,body=body,tags=tags,equipment_category=equipment_category,service_id=int(service_id) if service_id else None,created_by_id=u.id)
    db.add(row);db.flush()
    errors=[]
    for upload in (files or []):
        if not upload or not upload.filename: continue
        try:
            filename,stored,mime,size=_save_knowledge_file(upload); db.add(KnowledgeAttachment(article_id=row.id,filename=filename,stored_name=stored,content_type=mime,size_bytes=size,uploaded_by_id=u.id))
        except ValueError as exc: errors.append(str(exc))
    db.commit();audit(db,request,u,'knowledge.create','knowledge',row.id,details=f'{title}; files={len(files or [])}; errors={len(errors)}')
    return RedirectResponse(f'/knowledge/{row.id}',303)

@router.post('/knowledge/{article_id}/attachments')
def knowledge_attachment_add(article_id:int,request:Request,files:list[UploadFile]|None=File(None),db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u:return RedirectResponse('/login',303)
    if not has_permission(u,'knowledge.manage'): return forbidden(request,db,u,'knowledge.manage')
    article=db.get(KnowledgeArticle,article_id)
    if not article:return RedirectResponse('/knowledge',303)
    for upload in (files or []):
        if not upload or not upload.filename: continue
        try:
            filename,stored,mime,size=_save_knowledge_file(upload); db.add(KnowledgeAttachment(article_id=article.id,filename=filename,stored_name=stored,content_type=mime,size_bytes=size,uploaded_by_id=u.id))
        except ValueError: continue
    article.updated_at=datetime.utcnow();db.commit();audit(db,request,u,'knowledge.attachment.add','knowledge',article.id)
    return RedirectResponse(f'/knowledge/{article.id}#knowledge-files',303)

@router.get('/knowledge/attachments/{attachment_id}/raw')
def knowledge_attachment_raw(attachment_id:int,request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u:return Response(status_code=401)
    if not has_permission(u,'knowledge.view'):return Response(status_code=403)
    row=db.get(KnowledgeAttachment,attachment_id); path=_knowledge_path(row) if row else None
    if not row or not path:return Response(status_code=404)
    mime=row.content_type or 'application/octet-stream'
    inline=mime if (mime.startswith('image/') or mime=='application/pdf') else 'application/octet-stream'
    return FileResponse(str(path),filename=row.filename,media_type=inline,content_disposition_type='inline')

@router.get('/knowledge/attachments/{attachment_id}/download')
def knowledge_attachment_download(attachment_id:int,request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u:return Response(status_code=401)
    if not has_permission(u,'knowledge.view'):return Response(status_code=403)
    row=db.get(KnowledgeAttachment,attachment_id); path=_knowledge_path(row) if row else None
    if not row or not path:return Response(status_code=404)
    return FileResponse(str(path),filename=row.filename,media_type=row.content_type or 'application/octet-stream',content_disposition_type='attachment')

@router.post('/knowledge/{article_id}/attachments/{attachment_id}/delete')
def knowledge_attachment_delete(article_id:int,attachment_id:int,request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u:return RedirectResponse('/login',303)
    if not has_permission(u,'knowledge.manage'):return forbidden(request,db,u,'knowledge.manage')
    row=db.get(KnowledgeAttachment,attachment_id)
    if row and row.article_id==article_id:
        path=_knowledge_path(row); db.delete(row);db.commit()
        if path:
            try:path.unlink()
            except OSError:pass
        audit(db,request,u,'knowledge.attachment.delete','knowledge',article_id,details=f'attachment={attachment_id}')
    return RedirectResponse(f'/knowledge/{article_id}#knowledge-files',303)

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
    cards=[{'row':r,'conditions':_json(r.conditions_json,{}),'actions':_json(r.actions_json,{})} for r in rows]
    sites=db.query(Site).order_by(Site.name).all()
    technicians=db.query(User).filter(User.role=='technician',User.active==True).order_by(User.full_name).all()
    services=db.query(ServiceCatalog).filter(ServiceCatalog.active==True).order_by(ServiceCatalog.name).all()
    groups=db.query(SupportGroup).filter(SupportGroup.active==True).order_by(SupportGroup.name).all()
    equipment_categories=[x[0] for x in db.query(Equipment.category).filter(Equipment.category!='').distinct().order_by(Equipment.category).all() if x[0]]
    return templates.TemplateResponse('automation.html',ctx(request,db,cards=cards,rows=rows,sites=sites,technicians=technicians,services=services,groups=groups,equipment_categories=equipment_categories,ticket_categories=category_options(db,'ticket'),site_map={x.id:x.name for x in sites},tech_map={x.id:x.full_name for x in technicians},service_map={x.id:x.name for x in services},group_map={x.id:x.name for x in groups}))

@router.post('/automation/new')
def automation_new(request:Request,name:str=Form(...),category:str=Form(''),priority:str=Form(''),site_id:str=Form(''),service_id:str=Form(''),equipment_category:str=Form(''),equipment_criticality:str=Form(''),title_contains:str=Form(''),set_priority:str=Form(''),set_category:str=Form(''),apply_service_id:str=Form(''),assign_group_id:str=Form(''),assign_user_id:str=Form(''),assign_least_loaded:str=Form(''),notify_manager:str=Form(''),sla_hours:str=Form(''),db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u:return RedirectResponse('/login',303)
    if not has_permission(u,'automation.manage'):return forbidden(request,db,u,'automation.manage')
    cond={k:v for k,v in {
        'category':category,
        'priority':priority,
        'site_id':int(site_id) if site_id else None,
        'service_id':int(service_id) if service_id else None,
        'equipment_category':equipment_category,
        'equipment_criticality':equipment_criticality,
        'title_contains':title_contains.strip(),
    }.items() if v not in ('',None)}
    act={k:v for k,v in {
        'set_priority':set_priority,
        'set_category':set_category,
        'apply_service_id':int(apply_service_id) if apply_service_id else None,
        'assign_group_id':int(assign_group_id) if assign_group_id else None,
        'assign_user_id':int(assign_user_id) if assign_user_id else None,
        'assign_least_loaded':bool(assign_least_loaded),
        'notify_manager':bool(notify_manager),
        # Legacy fallback. Kept for old installations and advanced compatibility.
        'sla_hours':float(sla_hours) if sla_hours else None,
    }.items() if v not in ('',None,False)}
    if not cond or not act:
        return RedirectResponse('/automation?error=Укажите+хотя+бы+одно+условие+и+одно+действие',303)
    row=AutomationRule(name=name.strip(),conditions_json=json.dumps(cond,ensure_ascii=False),actions_json=json.dumps(act,ensure_ascii=False))
    db.add(row);db.commit();audit(db,request,u,'automation.create',entity_type='automation_rule',entity_id=row.id,details=row.name)
    return RedirectResponse('/automation?created=1',303)

@router.post('/automation/{rule_id}/toggle')
def automation_toggle(rule_id:int,request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u:return RedirectResponse('/login',303)
    if not has_permission(u,'automation.manage'):return forbidden(request,db,u,'automation.manage')
    row=db.get(AutomationRule,rule_id)
    if row:
        row.active=not row.active;db.commit();audit(db,request,u,'automation.toggle',entity_type='automation_rule',entity_id=row.id,details=f'active={row.active}')
    return RedirectResponse('/automation',303)

@router.post('/automation/{rule_id}/delete')
def automation_delete(rule_id:int,request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u:return RedirectResponse('/login',303)
    if not has_permission(u,'automation.manage'):return forbidden(request,db,u,'automation.manage')
    row=db.get(AutomationRule,rule_id)
    if row:
        name=row.name;db.delete(row);db.commit();audit(db,request,u,'automation.delete',entity_type='automation_rule',entity_id=rule_id,details=name)
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
REPORT_GROUP_LABELS = {
    'site': 'По объектам',
    'category': 'По категориям',
    'status': 'По статусам',
    'assignee': 'По исполнителям',
    'equipment_category': 'По типам оборудования',
}


def _report_group_key(t: Ticket, group_by: str) -> str:
    if group_by == 'category':
        return t.category or 'Без категории'
    if group_by == 'status':
        return STATUS_LABELS.get(t.status, t.status or '—')
    if group_by == 'assignee':
        return t.assignee.full_name if t.assignee else 'Не назначен'
    if group_by == 'equipment_category':
        return t.equipment.category if t.equipment else 'Без оборудования'
    return t.site.name if t.site else 'Без объекта'


def _report_bucket(dt: datetime, days: int):
    if days <= 60:
        key = dt.date()
        return key, key.strftime('%d.%m')
    if days <= 730:
        day = dt.date()
        monday = day - timedelta(days=day.weekday())
        return monday, monday.strftime('%d.%m')
    month = date(dt.year, dt.month, 1)
    return month, month.strftime('%m.%Y')


def _build_report_data(db: Session, u: User, group_by: str, days: int):
    group_by = group_by if group_by in REPORT_GROUP_LABELS else 'site'
    days = max(1, min(int(days or 30), 3650))
    now = datetime.utcnow()
    since = now - timedelta(days=days)
    tickets = scope_ticket_query(db.query(Ticket), u).filter(Ticket.created_at >= since).all()
    can_cost = has_permission(u, 'ticket.cost')

    agg = {}
    status_counts = defaultdict(int)
    buckets = {}
    total_hours = 0.0
    total_labor = 0.0
    total_parts = 0.0
    closed_total = 0
    overdue_total = 0
    open_total = 0
    sla_total = 0
    sla_ok = 0
    resolution_seconds = 0.0
    resolution_count = 0

    closed_statuses = {'resolved', 'closed'}
    open_statuses = {'new', 'assigned', 'in_progress', 'waiting'}

    for t in tickets:
        status_counts[STATUS_LABELS.get(t.status, t.status or '—')] += 1
        is_closed = t.status in closed_statuses
        is_open = t.status in open_statuses
        is_overdue = bool(t.sla_due_at and t.sla_due_at < now and t.status not in {'resolved', 'closed', 'cancelled', 'waiting'})
        closed_total += int(is_closed)
        open_total += int(is_open)
        overdue_total += int(is_overdue)

        hours = sum(float(ws.duration_seconds or 0) for ws in t.work_sessions) / 3600
        labor = float(t.labor_cost or 0) if can_cost else 0.0
        parts = float(t.parts_cost or 0) if can_cost else 0.0
        total_hours += hours
        total_labor += labor
        total_parts += parts

        if t.resolved_at and t.created_at and t.resolved_at >= t.created_at:
            resolution_seconds += (t.resolved_at - t.created_at).total_seconds()
            resolution_count += 1

        ticket_sla_ok = None
        if t.sla_due_at and t.status != 'cancelled':
            sla_total += 1
            if is_closed and t.resolved_at:
                ticket_sla_ok = t.resolved_at <= t.sla_due_at
            elif not is_overdue:
                ticket_sla_ok = True
            else:
                ticket_sla_ok = False
            sla_ok += int(bool(ticket_sla_ok))

        key = _report_group_key(t, group_by)
        x = agg.setdefault(key, {
            'name': key, 'count': 0, 'closed': 0, 'open': 0, 'overdue': 0,
            'labor': 0.0, 'parts': 0.0, 'hours': 0.0,
            'sla_total': 0, 'sla_ok': 0, 'resolution_seconds': 0.0, 'resolution_count': 0,
        })
        x['count'] += 1
        x['closed'] += int(is_closed)
        x['open'] += int(is_open)
        x['overdue'] += int(is_overdue)
        x['hours'] += hours
        x['labor'] += labor
        x['parts'] += parts
        if ticket_sla_ok is not None:
            x['sla_total'] += 1
            x['sla_ok'] += int(bool(ticket_sla_ok))
        if t.resolved_at and t.created_at and t.resolved_at >= t.created_at:
            x['resolution_seconds'] += (t.resolved_at - t.created_at).total_seconds()
            x['resolution_count'] += 1

        bucket_key, bucket_label = _report_bucket(t.created_at, days)
        b = buckets.setdefault(bucket_key, {'label': bucket_label, 'created': 0, 'closed': 0})
        b['created'] += 1
        if is_closed:
            b['closed'] += 1

    data = []
    for x in agg.values():
        x['completion_pct'] = round((x['closed'] / x['count'] * 100), 1) if x['count'] else 0
        x['sla_pct'] = round((x['sla_ok'] / x['sla_total'] * 100), 1) if x['sla_total'] else 0
        x['avg_resolution_h'] = round((x['resolution_seconds'] / x['resolution_count'] / 3600), 1) if x['resolution_count'] else 0
        x['total_cost'] = x['labor'] + x['parts']
        data.append(x)
    data.sort(key=lambda x: (-x['count'], x['name']))

    trend = [buckets[k] for k in sorted(buckets)]
    status_chart = [{'name': name, 'value': count} for name, count in sorted(status_counts.items(), key=lambda kv: (-kv[1], kv[0]))]
    top_groups = data[:10]
    summary = {
        'total': len(tickets),
        'open': open_total,
        'closed': closed_total,
        'overdue': overdue_total,
        'completion_pct': round((closed_total / len(tickets) * 100), 1) if tickets else 0,
        'sla_pct': round((sla_ok / sla_total * 100), 1) if sla_total else 0,
        'hours': round(total_hours, 1),
        'labor': round(total_labor, 2),
        'parts': round(total_parts, 2),
        'total_cost': round(total_labor + total_parts, 2),
        'avg_resolution_h': round((resolution_seconds / resolution_count / 3600), 1) if resolution_count else 0,
        'top_group': data[0]['name'] if data else '—',
    }
    return {
        'rows': data,
        'summary': summary,
        'trend': trend,
        'status_chart': status_chart,
        'top_groups': top_groups,
        'days': days,
        'group_by': group_by,
        'group_label': REPORT_GROUP_LABELS[group_by],
        'can_cost': can_cost,
    }


@router.get('/reports/builder', response_class=HTMLResponse)
def report_builder(request: Request, group_by: str = 'site', days: int = 30, db: Session = Depends(get_db)):
    u = user_or_login(request, db)
    if not u:
        return RedirectResponse('/login', 303)
    denied = _require(request, db, u, 'report.builder')
    if denied:
        return denied
    report = _build_report_data(db, u, group_by, days)
    subscriptions = db.query(ReportSubscription).filter(ReportSubscription.user_id == u.id).order_by(ReportSubscription.id.desc()).limit(20).all()
    return templates.TemplateResponse('report_builder.html', ctx(request, db, report=report, rows=report['rows'], group_by=report['group_by'], days=report['days'], subscriptions=subscriptions))


@router.get('/reports/builder.csv')
def report_builder_csv(request: Request, group_by: str = 'site', days: int = 30, db: Session = Depends(get_db)):
    u = user_or_login(request, db)
    if not u:
        return RedirectResponse('/login', 303)
    denied = _require(request, db, u, 'report.builder')
    if denied:
        return denied
    report = _build_report_data(db, u, group_by, days)
    out = io.StringIO()
    writer = csv.writer(out, delimiter=';', lineterminator='\n')
    header = ['Группа', 'Заявок', 'Выполнено', 'Выполнение %', 'Открыто', 'Просрочено', 'SLA %', 'Среднее решение, ч', 'Трудозатраты, ч']
    if report['can_cost']:
        header += ['Работы, ₸', 'Материалы, ₸', 'Итого, ₸']
    writer.writerow(header)
    for row in report['rows']:
        values = [row['name'], row['count'], row['closed'], row['completion_pct'], row['open'], row['overdue'], row['sla_pct'], row['avg_resolution_h'], round(row['hours'], 1)]
        if report['can_cost']:
            values += [round(row['labor'], 2), round(row['parts'], 2), round(row['total_cost'], 2)]
        writer.writerow(values)
    payload = '\ufeff' + out.getvalue()
    filename = f'FMTS_report_{report["group_by"]}_{report["days"]}d.csv'
    return Response(payload, media_type='text/csv; charset=utf-8', headers={'Content-Disposition': f'attachment; filename="{filename}"'})


@router.post('/reports/subscriptions/new')
def report_subscription_new(request: Request, name: str = Form(...), group_by: str = Form('site'), periodicity: str = Form('monthly'), days: int = Form(30), db: Session = Depends(get_db)):
    u = user_or_login(request, db)
    if not u:
        return RedirectResponse('/login', 303)
    if not has_permission(u, 'report.builder'):
        return forbidden(request, db, u, 'report.builder')
    group_by = group_by if group_by in REPORT_GROUP_LABELS else 'site'
    days = max(1, min(int(days or 30), 3650))
    if periodicity not in {'daily', 'weekly', 'monthly'}:
        periodicity = 'monthly'
    db.add(ReportSubscription(user_id=u.id, name=name.strip(), config_json=json.dumps({'group_by': group_by, 'days': days}, ensure_ascii=False), periodicity=periodicity))
    db.commit()
    return RedirectResponse(f'/reports/builder?group_by={group_by}&days={days}#report-subscriptions', 303)

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
_WEEKDAY_LABELS=['Пн','Вт','Ср','Чт','Пт','Сб','Вс']
_EXCEPTION_LABELS={
    'day_off':'Выходной',
    'vacation':'Отпуск',
    'sick':'Больничный',
    'duty':'Дежурство',
    'temporary_shift':'Временная смена',
}

def _default_technician_day(weekday:int)->dict:
    return {'weekday':weekday,'label':_WEEKDAY_LABELS[weekday],'available':weekday<5,'start_time':'09:00','end_time':'18:00','custom':False}

def _schedule_day_dict(row:TechnicianAvailability|None, weekday:int)->dict:
    if not row:
        return _default_technician_day(weekday)
    return {'weekday':weekday,'label':_WEEKDAY_LABELS[weekday],'available':bool(row.available),'start_time':row.start_time or '09:00','end_time':row.end_time or '18:00','custom':True}

def _minutes_between(start_time:str,end_time:str)->int:
    try:
        sh,sm=[int(x) for x in start_time.split(':',1)]; eh,em=[int(x) for x in end_time.split(':',1)]
        return max(0,(eh*60+em)-(sh*60+sm))
    except Exception:
        return 0

@router.get('/team/schedule',response_class=HTMLResponse)
def team_schedule(request:Request,user_id:int|None=None,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u:return RedirectResponse('/login',303)
    if u.role not in {'dispatcher','manager','admin'}:return forbidden(request,db,u,'schedule.view')
    techs=db.query(User).filter(User.role=='technician',User.active==True).order_by(User.full_name).all()
    selected=None
    if techs:
        selected=next((x for x in techs if x.id==user_id),techs[0])
    weekly=[]; exceptions=[]; weekly_minutes=0
    if selected:
        rows=db.query(TechnicianAvailability).filter(TechnicianAvailability.user_id==selected.id).all()
        by_day={r.weekday:r for r in rows}
        weekly=[_schedule_day_dict(by_day.get(i),i) for i in range(7)]
        weekly_minutes=sum(_minutes_between(d['start_time'],d['end_time']) for d in weekly if d['available'])
        exceptions=(db.query(TechnicianAvailabilityException)
            .filter(TechnicianAvailabilityException.user_id==selected.id)
            .order_by(TechnicianAvailabilityException.exception_date.desc(),TechnicianAvailabilityException.id.desc())
            .limit(80).all())
    today=date.today()
    technician_cards=[]
    for tech in techs:
        exc=(db.query(TechnicianAvailabilityException)
             .filter(TechnicianAvailabilityException.user_id==tech.id,TechnicianAvailabilityException.exception_date==today)
             .order_by(TechnicianAvailabilityException.id.desc()).first())
        if exc:
            available=bool(exc.available); summary=(_EXCEPTION_LABELS.get(exc.kind,exc.kind) if not exc.available else f"{_EXCEPTION_LABELS.get(exc.kind,exc.kind)} · {exc.start_time}–{exc.end_time}")
        else:
            row=(db.query(TechnicianAvailability)
                 .filter(TechnicianAvailability.user_id==tech.id,TechnicianAvailability.weekday==today.weekday()).first())
            day=_schedule_day_dict(row,today.weekday())
            available=day['available']; summary=(f"{day['start_time']}–{day['end_time']}" if available else 'Выходной')
        technician_cards.append({'user':tech,'available':available,'summary':summary})
    return templates.TemplateResponse('team_schedule.html',ctx(request,db,
        technicians=techs,selected_technician=selected,weekly=weekly,exceptions=exceptions,
        exception_labels=_EXCEPTION_LABELS,technician_cards=technician_cards,
        weekly_hours=round(weekly_minutes/60,1),working_days=sum(1 for d in weekly if d['available']),today=today))

@router.post('/team/schedule/week')
async def team_schedule_week_save(request:Request,user_id:int=Form(...),db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u:return RedirectResponse('/login',303)
    if u.role not in {'dispatcher','manager','admin'}:return forbidden(request,db,u,'schedule.manage')
    tech=db.get(User,user_id)
    if not tech or tech.role!='technician':return RedirectResponse('/team/schedule',303)
    form=await request.form()
    for weekday in range(7):
        row=db.query(TechnicianAvailability).filter(TechnicianAvailability.user_id==user_id,TechnicianAvailability.weekday==weekday).first()
        if not row:
            row=TechnicianAvailability(user_id=user_id,weekday=weekday);db.add(row)
        row.available=f'available_{weekday}' in form
        row.start_time=str(form.get(f'start_{weekday}') or '09:00')[:5]
        row.end_time=str(form.get(f'end_{weekday}') or '18:00')[:5]
    db.commit()
    audit(db,request,u,'schedule.week_update',entity_type='user',entity_id=user_id,details=f'Техник: {tech.full_name}')
    return RedirectResponse(f'/team/schedule?user_id={user_id}&saved=1',303)

@router.post('/team/schedule/exception/add')
def team_schedule_exception_add(request:Request,user_id:int=Form(...),exception_date:str=Form(...),kind:str=Form('day_off'),start_time:str=Form('09:00'),end_time:str=Form('18:00'),note:str=Form(''),db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u:return RedirectResponse('/login',303)
    if u.role not in {'dispatcher','manager','admin'}:return forbidden(request,db,u,'schedule.manage')
    tech=db.get(User,user_id)
    if not tech or tech.role!='technician':return RedirectResponse('/team/schedule',303)
    try: ex_date=date.fromisoformat(exception_date)
    except Exception: return RedirectResponse(f'/team/schedule?user_id={user_id}&error=date',303)
    if kind not in _EXCEPTION_LABELS: kind='day_off'
    available=kind in {'duty','temporary_shift'}
    row=(db.query(TechnicianAvailabilityException)
         .filter(TechnicianAvailabilityException.user_id==user_id,TechnicianAvailabilityException.exception_date==ex_date).first())
    if not row:
        row=TechnicianAvailabilityException(user_id=user_id,exception_date=ex_date);db.add(row)
    row.kind=kind; row.available=available; row.start_time=(start_time or '09:00')[:5]; row.end_time=(end_time or '18:00')[:5]; row.note=(note or '').strip()[:300]
    db.commit(); db.refresh(row)
    audit(db,request,u,'schedule.exception_save',entity_type='availability_exception',entity_id=row.id,details=f'{tech.full_name}: {ex_date} {_EXCEPTION_LABELS[kind]}')
    return RedirectResponse(f'/team/schedule?user_id={user_id}&exception_saved=1',303)

@router.post('/team/schedule/exception/{exception_id}/delete')
def team_schedule_exception_delete(exception_id:int,request:Request,db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u:return RedirectResponse('/login',303)
    if u.role not in {'dispatcher','manager','admin'}:return forbidden(request,db,u,'schedule.manage')
    row=db.get(TechnicianAvailabilityException,exception_id)
    if not row:return RedirectResponse('/team/schedule',303)
    user_id=row.user_id
    db.delete(row);db.commit()
    audit(db,request,u,'schedule.exception_delete',entity_type='availability_exception',entity_id=exception_id)
    return RedirectResponse(f'/team/schedule?user_id={user_id}',303)

# Legacy single-day endpoint kept for compatibility with old bookmarks/forms.
@router.post('/team/schedule/save')
def team_schedule_save(request:Request,user_id:int=Form(...),weekday:int=Form(...),start_time:str=Form('09:00'),end_time:str=Form('18:00'),available:str=Form(''),db:Session=Depends(get_db)):
    u=user_or_login(request,db)
    if not u:return RedirectResponse('/login',303)
    if u.role not in {'dispatcher','manager','admin'}:return forbidden(request,db,u,'schedule.manage')
    row=db.query(TechnicianAvailability).filter(TechnicianAvailability.user_id==user_id,TechnicianAvailability.weekday==weekday).first()
    if not row:row=TechnicianAvailability(user_id=user_id,weekday=weekday);db.add(row)
    row.start_time=start_time;row.end_time=end_time;row.available=bool(available);db.commit()
    return RedirectResponse(f'/team/schedule?user_id={user_id}',303)
