from __future__ import annotations
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import EmailRule, BackgroundServiceLog, SupportGroup, Department, User
from app.routes.web import templates, ctx, user_or_login, forbidden
from app.access import has_permission
from app.services.email_channel import poll_mailbox
from app.services.ldap_auth import sync_ldap_directory
from app.services.audit import audit
from app.services.system_jobs import run_logged_job

router=APIRouter()

def _admin(request,db):
    u=user_or_login(request,db)
    if not u: return None, RedirectResponse('/login',303)
    if not has_permission(u,'integration.manage'): return u, forbidden(request,db,u,'integration.manage')
    return u,None

@router.get('/integration/email-rules',response_class=HTMLResponse)
def email_rules_page(request:Request,db:Session=Depends(get_db)):
    u,stop=_admin(request,db)
    if stop:return stop
    return templates.TemplateResponse('email_rules.html',ctx(request,db,rules=db.query(EmailRule).order_by(EmailRule.sort_order,EmailRule.id).all(),groups=db.query(SupportGroup).filter(SupportGroup.active==True).order_by(SupportGroup.name).all()))

@router.post('/integration/email-rules/new')
def email_rule_new(request:Request,name:str=Form(...),sender_contains:str=Form(''),subject_contains:str=Form(''),recipient_contains:str=Form(''),category:str=Form(''),priority:str=Form(''),group_id:int|None=Form(None),add_recipients_as_observers:str=Form(''),active_days:str=Form('0,1,2,3,4,5,6'),time_from:str=Form('00:00'),time_to:str=Form('23:59'),sort_order:int=Form(100),db:Session=Depends(get_db)):
    u,stop=_admin(request,db)
    if stop:return stop
    if not db.query(EmailRule).filter(EmailRule.name==name.strip()).first():
        obj=EmailRule(name=name.strip(),sender_contains=sender_contains.strip(),subject_contains=subject_contains.strip(),recipient_contains=recipient_contains.strip(),category=category.strip(),priority=priority.strip(),group_id=group_id or None,add_recipients_as_observers=(add_recipients_as_observers=='1'),active_days=active_days.strip() or '0,1,2,3,4,5,6',time_from=time_from.strip() or '00:00',time_to=time_to.strip() or '23:59',sort_order=sort_order,active=True)
        db.add(obj);db.commit();audit(db,request,u,'email_rule.create',entity_type='email_rule',entity_id=obj.id,details=obj.name)
    return RedirectResponse('/integration/email-rules',303)

@router.post('/integration/email-rules/{rule_id}/delete')
def email_rule_delete(rule_id:int,request:Request,db:Session=Depends(get_db)):
    u,stop=_admin(request,db)
    if stop:return stop
    obj=db.get(EmailRule,rule_id)
    if obj:
        name=obj.name;db.delete(obj);db.commit();audit(db,request,u,'email_rule.delete',entity_type='email_rule',entity_id=rule_id,details=name)
    return RedirectResponse('/integration/email-rules',303)

@router.post('/integration/email/poll-now')
def email_poll_now(request:Request,db:Session=Depends(get_db)):
    u,stop=_admin(request,db)
    if stop:return stop
    run_logged_job('mailbox',poll_mailbox)
    audit(db,request,u,'integration.email.poll',entity_type='integration')
    return RedirectResponse('/system-services?message=Проверка+почты+запущена',303)

@router.post('/integration/ldap/sync')
def ldap_sync_now(request:Request,db:Session=Depends(get_db)):
    u,stop=_admin(request,db)
    if stop:return stop
    run_logged_job('ldap_sync',sync_ldap_directory)
    audit(db,request,u,'integration.ldap.sync',entity_type='integration')
    return RedirectResponse('/system-services?message=Синхронизация+AD/LDAP+выполнена',303)

@router.get('/system-services',response_class=HTMLResponse)
def system_services(request:Request,service:str='',status:str='',db:Session=Depends(get_db)):
    u,stop=_admin(request,db)
    if stop:return stop
    q=db.query(BackgroundServiceLog)
    if service:q=q.filter(BackgroundServiceLog.service==service)
    if status:q=q.filter(BackgroundServiceLog.status==status)
    rows=q.order_by(BackgroundServiceLog.id.desc()).limit(300).all()
    services=[x[0] for x in db.query(BackgroundServiceLog.service).distinct().order_by(BackgroundServiceLog.service).all()]
    departments=db.query(Department).order_by(Department.name).all()
    directory_users=db.query(User).filter(User.directory_source=='ldap').count()
    return templates.TemplateResponse('system_services.html',ctx(request,db,rows=rows,services=services,service=service,status=status,departments=departments,directory_users=directory_users,message=request.query_params.get('message','')))
