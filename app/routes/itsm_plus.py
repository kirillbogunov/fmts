from __future__ import annotations
import json, secrets
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import (
    BusinessCalendar, Equipment, EquipmentRelation, ServiceCatalog, Ticket,
    WebhookDelivery, WebhookEndpoint,
)
from app.security import current_user
from app.access import has_permission, scope_ticket_query, can_view_ticket
from app.routes.web import templates, ctx, forbidden
from app.services.audit import audit
from app.services.itsm import TICKET_TYPES, RELATION_LABELS
from app.services.sla_calendar import apply_service_sla
from app.services.localization import normalize_timezone_name
from app.services.webhooks import enqueue_event, enqueue_ticket_event, process_webhook_deliveries

router=APIRouter()


def _user(request:Request,db:Session):
    return current_user(request,db)


def _parse_local(value:str,tz_name:str)->datetime|None:
    if not value: return None
    try:
        dt=datetime.fromisoformat(value)
        zone=ZoneInfo(tz_name or 'Asia/Almaty')
        if dt.tzinfo is None: dt=dt.replace(tzinfo=zone)
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:
        return None


@router.get('/itsm',response_class=HTMLResponse)
def itsm_dashboard(request:Request,days:int=30,db:Session=Depends(get_db)):
    u=_user(request,db)
    if not u:return RedirectResponse('/login',303)
    if not has_permission(u,'itsm.view'):return forbidden(request,db,u,'itsm.view')
    days=max(1,min(int(days or 30),365))
    since=datetime.utcnow()-timedelta(days=days); now=datetime.utcnow()
    rows=scope_ticket_query(db.query(Ticket),u).filter(Ticket.created_at>=since).all()
    type_counts={k:0 for k in TICKET_TYPES}
    status_counts={}
    response_overdue=resolution_overdue=0
    for t in rows:
        type_counts[t.ticket_type if t.ticket_type in TICKET_TYPES else 'incident']+=1
        status_counts[t.status]=status_counts.get(t.status,0)+1
        if t.response_due_at and not t.first_response_at and t.response_due_at<now and t.status not in {'closed','cancelled'}: response_overdue+=1
        if t.sla_due_at and t.sla_due_at<now and t.status not in {'resolved','closed','cancelled','waiting'}: resolution_overdue+=1
    changes=(scope_ticket_query(db.query(Ticket),u)
             .filter(Ticket.ticket_type=='change',Ticket.status.notin_(['closed','cancelled']),Ticket.planned_start_at.is_not(None))
             .order_by(Ticket.planned_start_at).limit(100).all())
    problems=(scope_ticket_query(db.query(Ticket),u)
              .filter(Ticket.ticket_type=='problem',Ticket.status.notin_(['closed','cancelled']))
              .order_by(Ticket.priority.desc(),Ticket.id.desc()).limit(50).all())
    return templates.TemplateResponse('itsm_dashboard.html',ctx(request,db,days=days,type_counts=type_counts,status_counts=status_counts,changes=changes,problems=problems,response_overdue=response_overdue,resolution_overdue=resolution_overdue,ticket_types=TICKET_TYPES))


@router.post('/tickets/{ticket_id}/itsm')
def ticket_itsm_update(ticket_id:int,request:Request,ticket_type:str=Form('incident'),planned_start_at:str=Form(''),planned_end_at:str=Form(''),db:Session=Depends(get_db)):
    u=_user(request,db); ticket=db.get(Ticket,ticket_id)
    if not u:return RedirectResponse('/login',303)
    if not has_permission(u,'itsm.view') or not ticket or not can_view_ticket(u,ticket,db):return forbidden(request,db,u,'itsm.view')
    if ticket_type not in TICKET_TYPES: ticket_type='incident'
    start=_parse_local(planned_start_at,u.timezone); end=_parse_local(planned_end_at,u.timezone)
    if start and end and end<=start:
        return RedirectResponse(f'/tickets/{ticket.id}?itsm_error=time#enterprise-ticket',303)
    old=ticket.ticket_type
    ticket.ticket_type=ticket_type; ticket.planned_start_at=start; ticket.planned_end_at=end; ticket.edit_version=int(ticket.edit_version or 1)+1; ticket.updated_at=datetime.utcnow()
    enqueue_ticket_event(db,'ticket.updated',ticket,{'previous_ticket_type':old,'itsm_plan_changed':True})
    db.commit();audit(db,request,u,'ticket.itsm.update',entity_type='ticket',entity_id=ticket.id,details=f'{old}->{ticket_type}')
    return RedirectResponse(f'/tickets/{ticket.id}#enterprise-ticket',303)


@router.get('/sla-calendars',response_class=HTMLResponse)
def sla_calendars_page(request:Request,db:Session=Depends(get_db)):
    u=_user(request,db)
    if not u:return RedirectResponse('/login',303)
    if not has_permission(u,'sla.manage'):return forbidden(request,db,u,'sla.manage')
    rows=db.query(BusinessCalendar).order_by(BusinessCalendar.active.desc(),BusinessCalendar.name).all()
    services=db.query(ServiceCatalog).order_by(ServiceCatalog.name).all()
    calendar_holidays={}
    for c in rows:
        try: calendar_holidays[c.id]='\n'.join(json.loads(c.holidays_json or '[]'))
        except Exception: calendar_holidays[c.id]=''
    return templates.TemplateResponse('sla_calendars.html',ctx(request,db,rows=rows,services=services,calendar_holidays=calendar_holidays))


@router.post('/sla-calendars/new')
def sla_calendar_new(request:Request,name:str=Form(...),timezone_name:str=Form('Asia/Almaty',alias='timezone'),weekdays:str=Form('0,1,2,3,4'),work_start:str=Form('09:00'),work_end:str=Form('18:00'),holidays:str=Form(''),db:Session=Depends(get_db)):
    u=_user(request,db)
    if not u:return RedirectResponse('/login',303)
    if not has_permission(u,'sla.manage'):return forbidden(request,db,u,'sla.manage')
    holiday_rows=[]
    for raw in (holidays or '').replace(',','\n').splitlines():
        value=raw.strip()
        if not value:continue
        try: holiday_rows.append(datetime.fromisoformat(value).date().isoformat())
        except Exception: pass
    row=BusinessCalendar(name=name.strip()[:180],timezone=normalize_timezone_name(timezone_name),weekdays=weekdays.strip()[:30] or '0,1,2,3,4',work_start=work_start or '09:00',work_end=work_end or '18:00',holidays_json=json.dumps(sorted(set(holiday_rows))),active=True)
    db.add(row);db.commit();db.refresh(row)
    audit(db,request,u,'sla.calendar.create',entity_type='business_calendar',entity_id=row.id,details=row.name)
    return RedirectResponse('/sla-calendars',303)


@router.post('/sla-calendars/{calendar_id}/update')
def sla_calendar_update(calendar_id:int,request:Request,name:str=Form(...),timezone_name:str=Form('Asia/Almaty',alias='timezone'),weekdays:str=Form('0,1,2,3,4'),work_start:str=Form('09:00'),work_end:str=Form('18:00'),holidays:str=Form(''),active:str=Form(''),db:Session=Depends(get_db)):
    u=_user(request,db); row=db.get(BusinessCalendar,calendar_id)
    if not u:return RedirectResponse('/login',303)
    if not has_permission(u,'sla.manage'):return forbidden(request,db,u,'sla.manage')
    if not row:return RedirectResponse('/sla-calendars',303)
    hs=[]
    for raw in (holidays or '').replace(',','\n').splitlines():
        value=raw.strip()
        if not value:continue
        try: hs.append(datetime.fromisoformat(value).date().isoformat())
        except Exception: pass
    row.name=name.strip()[:180] or row.name;row.timezone=normalize_timezone_name(timezone_name,row.timezone or 'Asia/Almaty');row.weekdays=weekdays.strip()[:30] or '0,1,2,3,4';row.work_start=work_start or '09:00';row.work_end=work_end or '18:00';row.holidays_json=json.dumps(sorted(set(hs)));row.active=active=='1'
    db.commit();audit(db,request,u,'sla.calendar.update',entity_type='business_calendar',entity_id=row.id,details=row.name)
    return RedirectResponse('/sla-calendars',303)


@router.post('/services/{service_id}/sla')
def service_sla_update(service_id:int,request:Request,business_calendar_id:str=Form(''),response_sla_minutes:str=Form(''),resolution_sla_minutes:str=Form(''),db:Session=Depends(get_db)):
    u=_user(request,db); service=db.get(ServiceCatalog,service_id)
    if not u:return RedirectResponse('/login',303)
    if not has_permission(u,'sla.manage'):return forbidden(request,db,u,'sla.manage')
    if not service:return RedirectResponse('/services',303)
    service.business_calendar_id=int(business_calendar_id) if business_calendar_id else None
    service.response_sla_minutes=max(1,int(response_sla_minutes)) if response_sla_minutes else None
    service.resolution_sla_minutes=max(1,int(resolution_sla_minutes)) if resolution_sla_minutes else None
    if service.resolution_sla_minutes: service.default_sla_hours=max(1,int(round(service.resolution_sla_minutes/60)))
    db.commit();audit(db,request,u,'service.sla.update',entity_type='service',entity_id=service.id,details=f'response={service.response_sla_minutes}; resolution={service.resolution_sla_minutes}')
    return RedirectResponse('/sla-calendars',303)


@router.post('/equipment/{equipment_id}/relations')
def equipment_relation_add(equipment_id:int,request:Request,target_equipment_id:int=Form(...),relation_type:str=Form('depends_on'),note:str=Form(''),db:Session=Depends(get_db)):
    u=_user(request,db); src=db.get(Equipment,equipment_id); target=db.get(Equipment,target_equipment_id)
    if not u:return RedirectResponse('/login',303)
    if not has_permission(u,'cmdb.relation.manage'):return forbidden(request,db,u,'cmdb.relation.manage')
    if not src or not target or src.id==target.id:return RedirectResponse(f'/equipment/{equipment_id}',303)
    relation_type=relation_type if relation_type in RELATION_LABELS else 'related'
    exists=db.query(EquipmentRelation).filter(EquipmentRelation.source_equipment_id==src.id,EquipmentRelation.target_equipment_id==target.id,EquipmentRelation.relation_type==relation_type).first()
    if not exists:
        row=EquipmentRelation(source_equipment_id=src.id,target_equipment_id=target.id,relation_type=relation_type,note=note.strip()[:300],created_by_id=u.id);db.add(row);db.commit();db.refresh(row)
        audit(db,request,u,'cmdb.relation.create',entity_type='equipment_relation',entity_id=row.id,details=f'{src.inventory_no}->{target.inventory_no}:{relation_type}')
    return RedirectResponse(f'/equipment/{equipment_id}#cmdb-relations',303)


@router.post('/equipment/{equipment_id}/relations/{relation_id}/delete')
def equipment_relation_delete(equipment_id:int,relation_id:int,request:Request,db:Session=Depends(get_db)):
    u=_user(request,db); row=db.get(EquipmentRelation,relation_id)
    if not u:return RedirectResponse('/login',303)
    if not has_permission(u,'cmdb.relation.manage'):return forbidden(request,db,u,'cmdb.relation.manage')
    if row and (row.source_equipment_id==equipment_id or row.target_equipment_id==equipment_id):
        db.delete(row);db.commit();audit(db,request,u,'cmdb.relation.delete',entity_type='equipment_relation',entity_id=relation_id)
    return RedirectResponse(f'/equipment/{equipment_id}#cmdb-relations',303)


@router.get('/integration/webhooks',response_class=HTMLResponse)
def webhooks_page(request:Request,db:Session=Depends(get_db)):
    u=_user(request,db)
    if not u:return RedirectResponse('/login',303)
    if not has_permission(u,'integration.manage'):return forbidden(request,db,u,'integration.manage')
    endpoints=db.query(WebhookEndpoint).order_by(WebhookEndpoint.active.desc(),WebhookEndpoint.name).all()
    deliveries=db.query(WebhookDelivery).order_by(WebhookDelivery.id.desc()).limit(200).all()
    return templates.TemplateResponse('webhooks.html',ctx(request,db,endpoints=endpoints,deliveries=deliveries))


@router.post('/integration/webhooks/new')
def webhook_new(request:Request,name:str=Form(...),url:str=Form(...),events:str=Form('ticket.created,ticket.updated,ticket.comment'),secret:str=Form(''),db:Session=Depends(get_db)):
    u=_user(request,db)
    if not u:return RedirectResponse('/login',303)
    if not has_permission(u,'integration.manage'):return forbidden(request,db,u,'integration.manage')
    row=WebhookEndpoint(name=name.strip()[:180],url=url.strip()[:500],events=events.strip()[:500],secret=(secret.strip() or secrets.token_urlsafe(24))[:180],active=True)
    db.add(row);db.commit();db.refresh(row);audit(db,request,u,'webhook.create',entity_type='webhook_endpoint',entity_id=row.id,details=row.name)
    return RedirectResponse('/integration/webhooks',303)


@router.post('/integration/webhooks/{endpoint_id}/toggle')
def webhook_toggle(endpoint_id:int,request:Request,db:Session=Depends(get_db)):
    u=_user(request,db); row=db.get(WebhookEndpoint,endpoint_id)
    if not u:return RedirectResponse('/login',303)
    if not has_permission(u,'integration.manage'):return forbidden(request,db,u,'integration.manage')
    if row: row.active=not row.active;db.commit();audit(db,request,u,'webhook.toggle',entity_type='webhook_endpoint',entity_id=row.id,details=f'active={row.active}')
    return RedirectResponse('/integration/webhooks',303)


@router.post('/integration/webhooks/{endpoint_id}/test')
def webhook_test(endpoint_id:int,request:Request,db:Session=Depends(get_db)):
    u=_user(request,db); row=db.get(WebhookEndpoint,endpoint_id)
    if not u:return RedirectResponse('/login',303)
    if not has_permission(u,'integration.manage'):return forbidden(request,db,u,'integration.manage')
    if row:
        payload=json.dumps({'event':'system.test','created_at':datetime.utcnow().isoformat()+'Z','data':{'message':'FMTS webhook test','endpoint_id':row.id}},ensure_ascii=False,separators=(',',':'))
        db.add(WebhookDelivery(endpoint_id=row.id,event_name='system.test',payload_json=payload,status='pending',attempts=0,next_attempt_at=datetime.utcnow()));db.commit();process_webhook_deliveries(db,10)
    return RedirectResponse('/integration/webhooks',303)


@router.post('/integration/webhooks/deliveries/{delivery_id}/retry')
def webhook_retry(delivery_id:int,request:Request,db:Session=Depends(get_db)):
    u=_user(request,db); row=db.get(WebhookDelivery,delivery_id)
    if not u:return RedirectResponse('/login',303)
    if not has_permission(u,'integration.manage'):return forbidden(request,db,u,'integration.manage')
    if row: row.status='retry';row.next_attempt_at=datetime.utcnow();row.last_error='';db.commit();process_webhook_deliveries(db,10)
    return RedirectResponse('/integration/webhooks',303)
