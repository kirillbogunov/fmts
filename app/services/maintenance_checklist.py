from __future__ import annotations
import json
import re
from collections import defaultdict
from sqlalchemy.orm import Session
from app.models import MaintenancePlan, MaintenanceChecklistItem, TicketChecklistItem, Ticket

_NUM_PREFIX = re.compile(r'^\s*(?:\d+(?:\.\d+)*[.)]?|[-–—•*])\s*')


def plan_checklist_rows(db: Session, plan_id: int, include_inactive: bool=False) -> list[dict]:
    q=db.query(MaintenanceChecklistItem).filter(MaintenanceChecklistItem.plan_id==plan_id)
    if not include_inactive:
        q=q.filter(MaintenanceChecklistItem.active==True)
    items=q.order_by(MaintenanceChecklistItem.sort_order,MaintenanceChecklistItem.id).all()
    by_parent: dict[int|None,list[MaintenanceChecklistItem]]=defaultdict(list)
    ids={x.id for x in items}
    for item in items:
        parent=item.parent_id if item.parent_id in ids else None
        by_parent[parent].append(item)
    rows=[]; visited=set()
    def walk(parent_id, prefix: list[int], depth: int):
        for idx,item in enumerate(by_parent.get(parent_id,[]),1):
            if item.id in visited: continue
            visited.add(item.id)
            number='.'.join(map(str,prefix+[idx]))
            rows.append({'item':item,'number':number,'depth':depth})
            walk(item.id,prefix+[idx],depth+1)
    walk(None,[],0)
    for item in items:
        if item.id not in visited:
            rows.append({'item':item,'number':str(len(rows)+1),'depth':0})
    return rows


def legacy_lines(plan: MaintenancePlan) -> list[str]:
    raw=(plan.checklist or '').strip()
    if not raw or raw=='[]': return []
    try:
        data=json.loads(raw)
        if isinstance(data,list):
            values=[]
            for x in data:
                if isinstance(x,str): values.append(x)
                elif isinstance(x,dict): values.append(str(x.get('title') or x.get('name') or '').strip())
            return [v for v in values if v]
    except Exception:
        pass
    return [line.strip() for line in raw.splitlines() if line.strip()]


def snapshot_checklist(db: Session, plan: MaintenancePlan, ticket: Ticket) -> int:
    if db.query(TicketChecklistItem.id).filter(TicketChecklistItem.ticket_id==ticket.id).first():
        return 0
    rows=plan_checklist_rows(db,plan.id)
    created=0
    source_to_snapshot={}
    if rows:
        snapshots=[]
        for row in rows:
            item=row['item']
            snap=TicketChecklistItem(
                ticket_id=ticket.id,source_item_id=item.id,number=row['number'],title=item.title,
                instructions=item.instructions or '',depth=row['depth'],sort_order=item.sort_order,
                required=item.required,completed=False,
            )
            db.add(snap); db.flush(); source_to_snapshot[item.id]=snap.id; snapshots.append((snap,item))
            created+=1
        for snap,item in snapshots:
            if item.parent_id:
                snap.parent_snapshot_id=source_to_snapshot.get(item.parent_id)
    else:
        for idx,line in enumerate(legacy_lines(plan),1):
            title=_NUM_PREFIX.sub('',line).strip() or line
            db.add(TicketChecklistItem(ticket_id=ticket.id,number=str(idx),title=title,depth=0,sort_order=idx*10,required=True))
            created+=1
    return created


def ticket_checklist(db: Session, ticket_id: int) -> dict:
    rows=(db.query(TicketChecklistItem)
          .filter(TicketChecklistItem.ticket_id==ticket_id)
          .order_by(TicketChecklistItem.sort_order,TicketChecklistItem.id).all())
    total=len(rows); completed=sum(1 for x in rows if x.completed)
    required=[x for x in rows if x.required]
    required_completed=sum(1 for x in required if x.completed)
    return {
        'rows':rows,'total':total,'completed':completed,
        'required_total':len(required),'required_completed':required_completed,
        'percent':round(completed*100/total) if total else 0,
        'complete':(required_completed==len(required)) if rows else True,
    }

def ensure_plan_items_from_legacy(db: Session, plan: MaintenancePlan) -> int:
    if db.query(MaintenanceChecklistItem.id).filter(MaintenanceChecklistItem.plan_id==plan.id).first():
        return 0
    lines=legacy_lines(plan); created=0
    for idx,line in enumerate(lines,1):
        title=_NUM_PREFIX.sub('',line).strip() or line
        db.add(MaintenanceChecklistItem(plan_id=plan.id,title=title,sort_order=idx*10,required=True,active=True)); created+=1
    if created: db.flush()
    return created
