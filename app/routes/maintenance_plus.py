from __future__ import annotations
from datetime import datetime
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import MaintenancePlan, MaintenanceChecklistItem, Ticket, TicketChecklistItem
from app.security import current_user
from app.access import has_permission, can_view_ticket
from app.routes.web import forbidden
from app.services.audit import audit
from app.services.maintenance_checklist import plan_checklist_rows, ticket_checklist

router=APIRouter()


def _user(request:Request,db:Session): return current_user(request,db)


def _descendants(db:Session, item:MaintenanceChecklistItem)->list[MaintenanceChecklistItem]:
    out=[]; queue=[item.id]
    while queue:
        parent=queue.pop(0)
        children=db.query(MaintenanceChecklistItem).filter(MaintenanceChecklistItem.parent_id==parent).all()
        out.extend(children); queue.extend(x.id for x in children)
    return out

@router.post('/maintenance/{plan_id}/checklist/items')
def checklist_add(plan_id:int,request:Request,title:str=Form(...),parent_id:str=Form(''),instructions:str=Form(''),sort_order:int=Form(0),required:str=Form('1'),db:Session=Depends(get_db)):
    u=_user(request,db)
    if not u:return RedirectResponse('/login',303)
    if not has_permission(u,'maintenance.manage'):return forbidden(request,db,u,'maintenance.manage')
    plan=db.get(MaintenancePlan,plan_id)
    if not plan:return RedirectResponse('/maintenance',303)
    parent=None
    if parent_id:
        parent=db.get(MaintenanceChecklistItem,int(parent_id))
        if not parent or parent.plan_id!=plan.id: parent=None
    clean=title.strip()
    if clean:
        parent_key=parent.id if parent else None
        if not sort_order or sort_order <= 0:
            siblings=(db.query(MaintenanceChecklistItem)
                      .filter(MaintenanceChecklistItem.plan_id==plan.id,MaintenanceChecklistItem.parent_id==parent_key,MaintenanceChecklistItem.active==True)
                      .order_by(MaintenanceChecklistItem.sort_order.desc(),MaintenanceChecklistItem.id.desc()).all())
            sort_order=(siblings[0].sort_order+10) if siblings else 10
        row=MaintenanceChecklistItem(plan_id=plan.id,parent_id=parent_key,title=clean,instructions=instructions.strip(),sort_order=sort_order,required=(required=='1'),active=True)
        db.add(row);db.commit();db.refresh(row)
        audit(db,request,u,'maintenance.checklist.add',entity_type='maintenance',entity_id=plan.id,details=f'item={row.id}; title={clean}')
    return RedirectResponse(f'/maintenance#plan-{plan.id}',303)

@router.post('/maintenance/{plan_id}/checklist/{item_id}/update')
def checklist_update(plan_id:int,item_id:int,request:Request,title:str=Form(...),parent_id:str=Form(''),instructions:str=Form(''),sort_order:int=Form(100),required:str=Form(''),db:Session=Depends(get_db)):
    u=_user(request,db)
    if not u:return RedirectResponse('/login',303)
    if not has_permission(u,'maintenance.manage'):return forbidden(request,db,u,'maintenance.manage')
    item=db.get(MaintenanceChecklistItem,item_id)
    if not item or item.plan_id!=plan_id:return RedirectResponse('/maintenance',303)
    requested=int(parent_id) if parent_id else None
    # Prevent self/cycle parent assignments.
    descendants={x.id for x in _descendants(db,item)}
    if requested in descendants or requested==item.id: requested=None
    parent=db.get(MaintenanceChecklistItem,requested) if requested else None
    if parent and parent.plan_id!=plan_id: parent=None
    item.title=title.strip() or item.title; item.instructions=instructions.strip(); item.sort_order=sort_order; item.required=(required=='1'); item.parent_id=parent.id if parent else None
    db.commit();audit(db,request,u,'maintenance.checklist.update',entity_type='maintenance',entity_id=plan_id,details=f'item={item.id}')
    return RedirectResponse(f'/maintenance#plan-{plan_id}',303)

@router.post('/maintenance/{plan_id}/checklist/{item_id}/move')
def checklist_move(plan_id:int,item_id:int,request:Request,direction:str=Form(...),db:Session=Depends(get_db)):
    u=_user(request,db)
    if not u:return RedirectResponse('/login',303)
    if not has_permission(u,'maintenance.manage'):return forbidden(request,db,u,'maintenance.manage')
    item=db.get(MaintenanceChecklistItem,item_id)
    if not item or item.plan_id!=plan_id:return RedirectResponse('/maintenance',303)
    siblings=(db.query(MaintenanceChecklistItem)
              .filter(MaintenanceChecklistItem.plan_id==plan_id,MaintenanceChecklistItem.parent_id==item.parent_id,MaintenanceChecklistItem.active==True)
              .order_by(MaintenanceChecklistItem.sort_order,MaintenanceChecklistItem.id).all())
    try: idx=next(i for i,x in enumerate(siblings) if x.id==item.id)
    except StopIteration:return RedirectResponse(f'/maintenance#plan-{plan_id}',303)
    target_idx=idx-1 if direction=='up' else idx+1 if direction=='down' else idx
    if 0<=target_idx<len(siblings) and target_idx!=idx:
        other=siblings[target_idx]
        item.sort_order,other.sort_order=other.sort_order,item.sort_order
        if item.sort_order==other.sort_order:
            item.sort_order=target_idx*10+10; other.sort_order=idx*10+10
        db.commit();audit(db,request,u,'maintenance.checklist.move',entity_type='maintenance',entity_id=plan_id,details=f'item={item.id}; direction={direction}')
    return RedirectResponse(f'/maintenance#plan-{plan_id}',303)

@router.post('/maintenance/{plan_id}/checklist/{item_id}/delete')
def checklist_delete(plan_id:int,item_id:int,request:Request,db:Session=Depends(get_db)):
    u=_user(request,db)
    if not u:return RedirectResponse('/login',303)
    if not has_permission(u,'maintenance.manage'):return forbidden(request,db,u,'maintenance.manage')
    item=db.get(MaintenanceChecklistItem,item_id)
    if item and item.plan_id==plan_id:
        rows=[item]+_descendants(db,item)
        for row in rows: row.active=False
        db.commit();audit(db,request,u,'maintenance.checklist.delete',entity_type='maintenance',entity_id=plan_id,details=f'item={item_id}; descendants={len(rows)-1}')
    return RedirectResponse(f'/maintenance#plan-{plan_id}',303)

@router.post('/tickets/{ticket_id}/maintenance-checklist/{item_id}/toggle')
def checklist_toggle(ticket_id:int,item_id:int,request:Request,completed:str=Form(''),note:str=Form(''),db:Session=Depends(get_db)):
    u=_user(request,db); ticket=db.get(Ticket,ticket_id); row=db.get(TicketChecklistItem,item_id)
    if not u:return JSONResponse({'ok':False,'error':'Требуется вход'},status_code=401)
    if not ticket or not row or row.ticket_id!=ticket.id:return JSONResponse({'ok':False,'error':'Пункт не найден'},status_code=404)
    if not can_view_ticket(u,ticket,db) or u.role=='requester':return JSONResponse({'ok':False,'error':'Нет прав'},status_code=403)
    value=str(completed).lower() in {'1','true','on','yes'}
    row.completed=value; row.note=(note or row.note or '')[:500]
    row.completed_by_id=u.id if value else None; row.completed_at=datetime.utcnow() if value else None
    db.commit(); state=ticket_checklist(db,ticket.id)
    audit(db,request,u,'maintenance.checklist.toggle',entity_type='ticket',entity_id=ticket.id,details=f'item={row.id}; completed={value}')
    return JSONResponse({'ok':True,'completed':row.completed,'percent':state['percent'],'done':state['completed'],'total':state['total'],'complete':state['complete']})
