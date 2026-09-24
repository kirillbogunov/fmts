from __future__ import annotations
import json
from datetime import datetime, timedelta
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.config import get_settings
from app.models import AutomationRule, Ticket, User, SlaEvent, TechnicianAvailability, ServiceCatalog
from app.services.notifications import notify_user, notify_role
from app.services.operations import pick_group_assignee, sync_group_observers
from app.services.sla_calendar import apply_service_sla

settings=get_settings()
OPEN={'new','assigned','in_progress','waiting'}
SLA_RUNNING={'new','assigned','in_progress'}

def _safe_json(value:str, default):
    try: return json.loads(value or '')
    except Exception: return default

def technician_available(db:Session, user_id:int, when:datetime|None=None)->bool:
    when=when or datetime.now(); weekday=when.weekday(); hhmm=when.strftime('%H:%M')
    rows=db.query(TechnicianAvailability).filter(TechnicianAvailability.user_id==user_id,TechnicianAvailability.weekday==weekday).all()
    if not rows: return True
    return any(r.available and r.start_time<=hhmm<=r.end_time for r in rows)

def least_loaded_technician(db:Session)->User|None:
    techs=db.query(User).filter(User.role=='technician',User.active==True).all()
    techs=[u for u in techs if technician_available(db,u.id)] or techs
    if not techs: return None
    counts=dict(db.query(Ticket.assignee_id,func.count(Ticket.id)).filter(Ticket.status.in_(OPEN),Ticket.assignee_id.in_([u.id for u in techs])).group_by(Ticket.assignee_id).all())
    return min(techs,key=lambda u:(counts.get(u.id,0),u.id))

def rule_matches(rule:AutomationRule,ticket:Ticket)->bool:
    c=_safe_json(rule.conditions_json,{})
    if c.get('category') and ticket.category!=c['category']: return False
    if c.get('priority') and ticket.priority!=c['priority']: return False
    if c.get('site_id') and ticket.site_id!=int(c['site_id']): return False
    if c.get('service_id') and ticket.service_id!=int(c['service_id']): return False
    if c.get('title_contains') and c['title_contains'].lower() not in (ticket.title or '').lower(): return False
    if c.get('equipment_category') and (not ticket.equipment or ticket.equipment.category!=c['equipment_category']): return False
    if c.get('equipment_criticality') and (not ticket.equipment or ticket.equipment.criticality!=c['equipment_criticality']): return False
    return True

def apply_ticket_rules(db:Session,ticket:Ticket)->list[str]:
    applied=[]
    for rule in db.query(AutomationRule).filter(AutomationRule.active==True).order_by(AutomationRule.sort_order,AutomationRule.id).all():
        if not rule_matches(rule,ticket): continue
        a=_safe_json(rule.actions_json,{})
        if a.get('set_priority'): ticket.priority=str(a['set_priority'])
        if a.get('set_category'): ticket.category=str(a['set_category'])
        if a.get('apply_service_id'):
            service=db.get(ServiceCatalog,int(a['apply_service_id']))
            if service and service.active:
                ticket.service_id=service.id
                apply_service_sla(db,ticket,service,start_at=ticket.created_at or datetime.utcnow())
        elif a.get('sla_hours'):
            # Legacy rule compatibility: older rules may still store a raw hour value.
            try: ticket.sla_due_at=datetime.utcnow()+timedelta(hours=float(a['sla_hours']))
            except Exception: pass
        if a.get('assign_group_id'):
            try:
                ticket.group_id=int(a['assign_group_id'])
            except Exception:
                ticket.group_id=None
        if a.get('assign_user_id'):
            u=db.get(User,int(a['assign_user_id']))
            if u and u.active and u.role=='technician': ticket.assignee_id=u.id; ticket.master_name=u.full_name; ticket.status='assigned'
        elif a.get('assign_group_id'):
            u=pick_group_assignee(db,int(a['assign_group_id']))
            if u: ticket.assignee_id=u.id; ticket.master_name=u.full_name; ticket.status='assigned'
        elif a.get('assign_least_loaded'):
            u=least_loaded_technician(db)
            if u: ticket.assignee_id=u.id; ticket.master_name=u.full_name; ticket.status='assigned'
        if ticket.group_id:
            sync_group_observers(db,ticket)
        if a.get('notify_manager'):
            notify_role(db,{'manager','admin'},f'Автоматизация: {ticket.number}',rule.name,f'/tickets/{ticket.id}',dedup_prefix=f'rule:{rule.id}:ticket:{ticket.id}',event_type='general')
        applied.append(rule.name)
    if ticket.assignee_id:
        assignee=db.get(User,ticket.assignee_id)
        notify_user(db,assignee,f'Назначена заявка {ticket.number}',ticket.title,f'/tickets/{ticket.id}',dedup_key=f'assigned:{ticket.id}:{ticket.assignee_id}',event_type='assignment')
    return applied

def process_sla_escalations(db:Session)->int:
    now=datetime.utcnow(); warn_at=now+timedelta(minutes=max(1,settings.sla_warning_minutes)); created=0
    rows=db.query(Ticket).filter(Ticket.status.in_(SLA_RUNNING),Ticket.sla_due_at.is_not(None),Ticket.sla_due_at<=warn_at).all()
    for t in rows:
        kind='overdue' if t.sla_due_at and t.sla_due_at<now else 'warning'; key=f'{t.id}:resolution:{kind}'
        if not db.query(SlaEvent).filter(SlaEvent.event_key==key).first():
            db.add(SlaEvent(ticket_id=t.id,event_type=f'resolution_{kind}',event_key=key)); created+=1
            title=(f'Просрочена заявка {t.number}' if kind=='overdue' else f'SLA решения скоро истекает: {t.number}')
            body=f'{t.title} · {t.site.name if t.site else ""}'
            if t.assignee_id: notify_user(db,db.get(User,t.assignee_id),title,body,f'/tickets/{t.id}',level='danger' if kind=='overdue' else 'warning',dedup_key=f'sla:{key}:tech',event_type='sla')
            notify_role(db,{'dispatcher','manager','admin'},title,body,f'/tickets/{t.id}',level='danger' if kind=='overdue' else 'warning',dedup_prefix=f'sla:{key}',event_type='sla')
    response_rows=db.query(Ticket).filter(Ticket.status.notin_({'closed','cancelled'}),Ticket.first_response_at.is_(None),Ticket.response_due_at.is_not(None),Ticket.response_due_at<=warn_at).all()
    for t in response_rows:
        kind='overdue' if t.response_due_at and t.response_due_at<now else 'warning'; key=f'{t.id}:response:{kind}'
        if db.query(SlaEvent).filter(SlaEvent.event_key==key).first(): continue
        db.add(SlaEvent(ticket_id=t.id,event_type=f'response_{kind}',event_key=key)); created+=1
        title=(f'Просрочен SLA реакции: {t.number}' if kind=='overdue' else f'SLA реакции скоро истекает: {t.number}')
        body=f'{t.title} · требуется первая реакция исполнителя'
        notify_role(db,{'dispatcher','manager','admin'},title,body,f'/tickets/{t.id}',level='danger' if kind=='overdue' else 'warning',dedup_prefix=f'sla:{key}',event_type='sla')
    db.commit(); return created
