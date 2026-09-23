from __future__ import annotations
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import (
    User, Site, Equipment, Ticket, TicketLink, ServiceCatalog,
    SupportGroup, SupportGroupMember, TicketObserver,
    TicketTemplate, TicketTemplateTask,
)
from app.security import current_user
from app.access import has_permission, can_view_ticket, scope_ticket_query, can_change_ticket_status
from app.routes.web import ctx, templates, forbidden
from app.services.audit import audit
from app.services.maintenance import next_ticket_number
from app.services.notifications import notify_user
from app.services.operations import pick_group_assignee, sync_group_observers
from app.services.ui_styles import sla_hours_for
from app.services.ticket_lifecycle import ensure_initial_history, transition_ticket
from app.services.sla_calendar import apply_service_sla
from app.services.webhooks import enqueue_ticket_event

router = APIRouter()


def _user(request: Request, db: Session):
    return current_user(request, db)


def _visible_ticket(db: Session, u: User, ticket_id: int) -> Ticket | None:
    return scope_ticket_query(db.query(Ticket), u).filter(Ticket.id == ticket_id).first()


# ---------------- Groups / teams ----------------
@router.get('/teams', response_class=HTMLResponse)
def teams_page(request: Request, db: Session = Depends(get_db)):
    u = _user(request, db)
    if not u:
        return RedirectResponse('/login', 303)
    if not (has_permission(u, 'team.manage') or has_permission(u, 'ticket.list_all')):
        return forbidden(request, db, u, 'team.manage')
    groups = db.query(SupportGroup).order_by(SupportGroup.active.desc(), SupportGroup.name).all()
    members = {
        g.id: db.query(User, SupportGroupMember.member_role)
        .join(SupportGroupMember, SupportGroupMember.user_id == User.id)
        .filter(SupportGroupMember.group_id == g.id)
        .order_by(User.full_name)
        .all()
        for g in groups
    }
    return templates.TemplateResponse('teams.html', ctx(
        request, db,
        groups=groups,
        members=members,
        users=db.query(User).filter(User.active == True).order_by(User.full_name).all(),
    ))


@router.post('/teams/new')
def team_new(request: Request, name: str = Form(...), description: str = Form(''), db: Session = Depends(get_db)):
    u = _user(request, db)
    if not u:
        return RedirectResponse('/login', 303)
    if not has_permission(u, 'team.manage'):
        return forbidden(request, db, u, 'team.manage')
    clean = name.strip()
    if clean and not db.query(SupportGroup).filter(func.lower(SupportGroup.name) == clean.lower()).first():
        row = SupportGroup(name=clean, description=description.strip())
        db.add(row); db.commit(); db.refresh(row)
        audit(db, request, u, 'team.create', entity_type='support_group', entity_id=row.id, details=row.name)
    return RedirectResponse('/teams', 303)


@router.post('/teams/{group_id}/members')
def team_member_add(group_id: int, request: Request, user_id: int = Form(...), member_role: str = Form('executor'), db: Session = Depends(get_db)):
    u = _user(request, db)
    if not u:
        return RedirectResponse('/login', 303)
    if not has_permission(u, 'team.manage'):
        return forbidden(request, db, u, 'team.manage')
    group = db.get(SupportGroup, group_id); user = db.get(User, user_id)
    if group and user and user.active:
        row = db.query(SupportGroupMember).filter(SupportGroupMember.group_id == group_id, SupportGroupMember.user_id == user_id).first()
        role = member_role if member_role in {'executor', 'observer'} else 'executor'
        if row:
            row.member_role = role
        else:
            db.add(SupportGroupMember(group_id=group_id, user_id=user_id, member_role=role))
        db.commit()
    return RedirectResponse('/teams', 303)


@router.post('/teams/{group_id}/members/{user_id}/remove')
def team_member_remove(group_id: int, user_id: int, request: Request, db: Session = Depends(get_db)):
    u = _user(request, db)
    if not u:
        return RedirectResponse('/login', 303)
    if not has_permission(u, 'team.manage'):
        return forbidden(request, db, u, 'team.manage')
    db.query(SupportGroupMember).filter(SupportGroupMember.group_id == group_id, SupportGroupMember.user_id == user_id).delete()
    db.commit()
    return RedirectResponse('/teams', 303)


# ---------------- Ticket observers ----------------
@router.post('/tickets/{ticket_id}/observers')
def ticket_observer_add(ticket_id: int, request: Request, user_id: int = Form(...), db: Session = Depends(get_db)):
    u = _user(request, db); t = db.get(Ticket, ticket_id)
    if not u:
        return RedirectResponse('/login', 303)
    if not t or not can_view_ticket(u, t, db) or not has_permission(u, 'ticket.observe'):
        return forbidden(request, db, u, 'ticket.observe')
    target = db.get(User, user_id)
    if target and target.active and not db.query(TicketObserver).filter(TicketObserver.ticket_id == t.id, TicketObserver.user_id == target.id).first():
        db.add(TicketObserver(ticket_id=t.id, user_id=target.id, created_by_id=u.id)); db.commit()
        notify_user(db, target, f'Вы добавлены наблюдателем в {t.number}', t.title, f'/tickets/{t.id}', dedup_key=f'observer:{t.id}:{target.id}')
        db.commit()
    return RedirectResponse(f'/tickets/{t.id}#participants', 303)


@router.post('/tickets/{ticket_id}/observers/{user_id}/remove')
def ticket_observer_remove(ticket_id: int, user_id: int, request: Request, db: Session = Depends(get_db)):
    u = _user(request, db); t = db.get(Ticket, ticket_id)
    if not u:
        return RedirectResponse('/login', 303)
    if not t or not can_view_ticket(u, t, db) or not has_permission(u, 'ticket.observe'):
        return forbidden(request, db, u, 'ticket.observe')
    db.query(TicketObserver).filter(TicketObserver.ticket_id == t.id, TicketObserver.user_id == user_id).delete(); db.commit()
    return RedirectResponse(f'/tickets/{t.id}#participants', 303)


# ---------------- Bulk operations ----------------
@router.post('/tickets/bulk')
def ticket_bulk(
    request: Request,
    ticket_ids: list[int] = Form([]),
    action: str = Form(...),
    assignee_id: str = Form(''),
    group_id: str = Form(''),
    priority: str = Form(''),
    status: str = Form(''),
    db: Session = Depends(get_db),
):
    u = _user(request, db)
    if not u:
        return RedirectResponse('/login', 303)
    if not has_permission(u, 'ticket.bulk'):
        return forbidden(request, db, u, 'ticket.bulk')
    ids = sorted(set(int(x) for x in ticket_ids if int(x) > 0))
    rows = scope_ticket_query(db.query(Ticket), u).filter(Ticket.id.in_(ids)).all() if ids else []
    changed = 0
    for t in rows:
        old_status = t.status
        if action == 'assign' and assignee_id:
            target = db.get(User, int(assignee_id))
            if target and target.active and target.role == 'technician':
                t.assignee_id = target.id; t.master_name = target.full_name
                if t.status == 'new': transition_ticket(db,t,'assigned',user_id=u.id,source='bulk')
                else: t.edit_version=int(t.edit_version or 1)+1
                changed += 1
        elif action == 'group' and group_id:
            group = db.get(SupportGroup, int(group_id))
            if group and group.active:
                t.group_id = group.id
                if not t.assignee_id:
                    picked = pick_group_assignee(db, group.id)
                    if picked:
                        t.assignee_id = picked.id; t.master_name = picked.full_name
                if t.status == 'new': transition_ticket(db,t,'assigned',user_id=u.id,source='bulk')
                else: t.edit_version=int(t.edit_version or 1)+1
                sync_group_observers(db, t); changed += 1
        elif action == 'priority' and priority in {'low', 'normal', 'high', 'critical'}:
            t.priority = priority; t.edit_version=int(t.edit_version or 1)+1; changed += 1
        elif action == 'status' and status:
            decision = can_change_ticket_status(u, t, status)
            if decision.allowed:
                # Bulk completion is intentionally conservative: final states keep
                # the same documentation/time invariants as the normal ticket form.
                if status in {'resolved', 'closed'}:
                    continue
                if status in {'assigned', 'in_progress', 'waiting'} and not (t.assignee_id or t.group_id or t.contractor_id):
                    continue
                transition_ticket(db,t,status,user_id=u.id,source='bulk'); changed += 1
        elif action == 'duplicate':
            copy = Ticket(
                number=next_ticket_number(db), title=f'{t.title} — копия', description=t.description,
                category=t.category, priority=t.priority, status='new', site_id=t.site_id,
                equipment_id=t.equipment_id, requester_id=t.requester_id, creator_id=u.id,
                requester_name=t.requester_name, requester_phone=t.requester_phone, room=t.room,
                service_id=t.service_id, group_id=t.group_id, template_id=t.template_id,ticket_type=t.ticket_type,
            )
            apply_service_sla(db,copy,db.get(ServiceCatalog,t.service_id) if t.service_id else None,fallback_resolution_minutes=sla_hours_for(db,t.priority)*60)
            db.add(copy); db.flush(); ensure_initial_history(db,copy,user_id=u.id,source='duplicate'); enqueue_ticket_event(db,'ticket.created',copy,{'source':'duplicate','copied_from':t.id})
            db.add(TicketLink(ticket_id=t.id, linked_ticket_id=copy.id, link_type='duplicate', created_by_id=u.id))
            db.add(TicketLink(ticket_id=copy.id, linked_ticket_id=t.id, link_type='duplicate', created_by_id=u.id))
            sync_group_observers(db, copy); changed += 1
        if t.status != old_status:
            t.updated_at = datetime.utcnow()
    db.commit()
    audit(db, request, u, 'ticket.bulk', entity_type='ticket', entity_id=','.join(map(str, ids)), details=f'action={action}; changed={changed}')
    return RedirectResponse('/tickets', 303)


# ---------------- Ticket templates / work orders ----------------
@router.get('/ticket-templates', response_class=HTMLResponse)
def ticket_templates_page(request: Request, db: Session = Depends(get_db)):
    u = _user(request, db)
    if not u:
        return RedirectResponse('/login', 303)
    if not has_permission(u, 'ticket.template'):
        return forbidden(request, db, u, 'ticket.template')
    rows = db.query(TicketTemplate).order_by(TicketTemplate.active.desc(), TicketTemplate.name).all()
    tasks = {r.id: db.query(TicketTemplateTask).filter(TicketTemplateTask.template_id == r.id).order_by(TicketTemplateTask.sort_order, TicketTemplateTask.id).all() for r in rows}
    return templates.TemplateResponse('ticket_templates.html', ctx(
        request, db, rows=rows, tasks=tasks,
        services=db.query(ServiceCatalog).filter(ServiceCatalog.active == True).order_by(ServiceCatalog.name).all(),
        groups=db.query(SupportGroup).filter(SupportGroup.active == True).order_by(SupportGroup.name).all(),
        sites=db.query(Site).order_by(Site.name).all(),
        requesters=db.query(User).filter(User.active == True).order_by(User.full_name).all(),
        equipment=db.query(Equipment).order_by(Equipment.name).all(),
    ))


@router.post('/ticket-templates/new')
def ticket_template_new(
    request: Request, name: str = Form(...), title_template: str = Form(''), description_template: str = Form(''),
    category: str = Form('Другое'), priority: str = Form('normal'), service_id: str = Form(''), group_id: str = Form(''),
    db: Session = Depends(get_db),
):
    u = _user(request, db)
    if not u:
        return RedirectResponse('/login', 303)
    if not has_permission(u, 'ticket.template'):
        return forbidden(request, db, u, 'ticket.template')
    clean = name.strip()
    if clean and not db.query(TicketTemplate).filter(func.lower(TicketTemplate.name) == clean.lower()).first():
        db.add(TicketTemplate(
            name=clean, title_template=title_template.strip(), description_template=description_template,
            category=category, priority=priority if priority in {'low','normal','high','critical'} else 'normal',
            service_id=int(service_id) if service_id else None, group_id=int(group_id) if group_id else None,
        )); db.commit()
    return RedirectResponse('/ticket-templates', 303)


@router.post('/ticket-templates/{template_id}/tasks')
def ticket_template_task_new(template_id: int, request: Request, title: str = Form(...), description: str = Form(''), sort_order: int = Form(100), db: Session = Depends(get_db)):
    u = _user(request, db)
    if not u:
        return RedirectResponse('/login', 303)
    if not has_permission(u, 'ticket.template'):
        return forbidden(request, db, u, 'ticket.template')
    if db.get(TicketTemplate, template_id):
        db.add(TicketTemplateTask(template_id=template_id, title=title.strip(), description=description, sort_order=sort_order)); db.commit()
    return RedirectResponse('/ticket-templates', 303)


@router.post('/ticket-templates/{template_id}/instantiate')
def ticket_template_instantiate(
    template_id: int, request: Request, site_id: int = Form(...), requester_id: str = Form(''), equipment_id: str = Form(''),
    db: Session = Depends(get_db),
):
    u = _user(request, db); tpl = db.get(TicketTemplate, template_id)
    if not u:
        return RedirectResponse('/login', 303)
    if not tpl or not has_permission(u, 'ticket.template'):
        return forbidden(request, db, u, 'ticket.template')
    site = db.get(Site, site_id)
    if not site:
        return RedirectResponse('/ticket-templates', 303)
    requester = db.get(User, int(requester_id)) if requester_id and has_permission(u, 'ticket.set_requester') else u
    if not requester or not requester.active:
        requester = u
    eq_id = int(equipment_id) if equipment_id else None
    if eq_id:
        eq = db.get(Equipment, eq_id)
        if not eq or eq.site_id != site.id:
            eq_id = None
    group_id = tpl.group_id if tpl.group_id and db.get(SupportGroup, tpl.group_id) else None
    assignee = pick_group_assignee(db, group_id) if group_id else None
    sla = sla_hours_for(db, tpl.priority)
    root = Ticket(
        number=next_ticket_number(db), title=tpl.title_template or tpl.name, description=tpl.description_template,
        category=tpl.category, priority=tpl.priority, status='assigned' if (group_id or assignee) else 'new',
        site_id=site.id, equipment_id=eq_id, requester_id=requester.id, creator_id=u.id,
        requester_name=requester.full_name, requester_phone=requester.phone or '', assignee_id=assignee.id if assignee else None,
        master_name=assignee.full_name if assignee else '', group_id=group_id, service_id=tpl.service_id, template_id=tpl.id,
    )
    apply_service_sla(db,root,db.get(ServiceCatalog,tpl.service_id) if tpl.service_id else None,fallback_resolution_minutes=sla*60)
    db.add(root); db.flush(); ensure_initial_history(db,root,user_id=u.id,source='template'); sync_group_observers(db, root); enqueue_ticket_event(db,'ticket.created',root,{'source':'template'})
    for task in db.query(TicketTemplateTask).filter(TicketTemplateTask.template_id == tpl.id).order_by(TicketTemplateTask.sort_order, TicketTemplateTask.id).all():
        child_assignee = pick_group_assignee(db, group_id) if group_id else None
        child = Ticket(
            number=next_ticket_number(db), title=task.title, description=task.description,
            category=tpl.category, priority=tpl.priority, status='assigned' if (group_id or child_assignee) else 'new',
            site_id=site.id, equipment_id=eq_id, requester_id=requester.id, creator_id=u.id,
            requester_name=requester.full_name, requester_phone=requester.phone or '', assignee_id=child_assignee.id if child_assignee else None,
            master_name=child_assignee.full_name if child_assignee else '', group_id=group_id, service_id=tpl.service_id, template_id=tpl.id,
        )
        apply_service_sla(db,child,db.get(ServiceCatalog,tpl.service_id) if tpl.service_id else None,fallback_resolution_minutes=sla*60)
        db.add(child); db.flush(); ensure_initial_history(db,child,user_id=u.id,source='template'); sync_group_observers(db, child); enqueue_ticket_event(db,'ticket.created',child,{'source':'template','parent_ticket_id':root.id})
        db.add(TicketLink(ticket_id=root.id, linked_ticket_id=child.id, link_type='child', created_by_id=u.id))
        db.add(TicketLink(ticket_id=child.id, linked_ticket_id=root.id, link_type='parent', created_by_id=u.id))
    db.commit()
    audit(db, request, u, 'ticket.template.instantiate', entity_type='ticket_template', entity_id=tpl.id, details=f'root={root.id}')
    return RedirectResponse(f'/tickets/{root.id}', 303)
