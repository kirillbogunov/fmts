from __future__ import annotations
import hashlib, hmac, json
from datetime import datetime, timedelta
import httpx
from sqlalchemy.orm import Session
from app.models import WebhookEndpoint, WebhookDelivery, Ticket


def _subscribed(endpoint: WebhookEndpoint, event_name: str) -> bool:
    events={x.strip() for x in (endpoint.events or '').split(',') if x.strip()}
    return '*' in events or event_name in events


def ticket_payload(ticket: Ticket) -> dict:
    return {
        'id':ticket.id,'number':ticket.number,'title':ticket.title,'description':ticket.description,
        'ticket_type':getattr(ticket,'ticket_type','incident'),'status':ticket.status,'priority':ticket.priority,
        'category':ticket.category,'site_id':ticket.site_id,'equipment_id':ticket.equipment_id,
        'requester_id':ticket.requester_id,'assignee_id':ticket.assignee_id,'group_id':ticket.group_id,
        'service_id':ticket.service_id,'created_at':ticket.created_at.isoformat() if ticket.created_at else None,
        'updated_at':ticket.updated_at.isoformat() if ticket.updated_at else None,
        'sla_due_at':ticket.sla_due_at.isoformat() if ticket.sla_due_at else None,
        'response_due_at':ticket.response_due_at.isoformat() if getattr(ticket,'response_due_at',None) else None,
        'first_response_at':ticket.first_response_at.isoformat() if getattr(ticket,'first_response_at',None) else None,
    }


def enqueue_event(db: Session, event_name: str, payload: dict) -> int:
    body=json.dumps({'event':event_name,'created_at':datetime.utcnow().isoformat()+'Z','data':payload},ensure_ascii=False,separators=(',',':'))
    endpoints=db.query(WebhookEndpoint).filter(WebhookEndpoint.active==True).all()
    created=0
    for ep in endpoints:
        if not _subscribed(ep,event_name): continue
        db.add(WebhookDelivery(endpoint_id=ep.id,event_name=event_name,payload_json=body,status='pending',attempts=0,next_attempt_at=datetime.utcnow()))
        created+=1
    return created


def enqueue_ticket_event(db: Session, event_name: str, ticket: Ticket, extra: dict | None=None) -> int:
    payload=ticket_payload(ticket)
    if extra: payload.update(extra)
    return enqueue_event(db,event_name,payload)


def process_webhook_deliveries(db: Session, limit: int=30) -> int:
    now=datetime.utcnow(); processed=0
    rows=(db.query(WebhookDelivery)
          .filter(WebhookDelivery.status.in_(['pending','retry']),WebhookDelivery.next_attempt_at<=now)
          .order_by(WebhookDelivery.id).limit(limit).all())
    for row in rows:
        ep=row.endpoint
        if not ep or not ep.active:
            row.status='disabled'; continue
        body=row.payload_json.encode('utf-8')
        headers={'Content-Type':'application/json','User-Agent':'FMTS-Webhook/0.7.5','X-FMTS-Event':row.event_name,'X-FMTS-Delivery':str(row.id)}
        if ep.secret:
            headers['X-FMTS-Signature']='sha256='+hmac.new(ep.secret.encode('utf-8'),body,hashlib.sha256).hexdigest()
        try:
            with httpx.Client(timeout=8.0,follow_redirects=False) as client:
                response=client.post(ep.url,content=body,headers=headers)
            row.attempts=int(row.attempts or 0)+1
            if 200<=response.status_code<300:
                row.status='delivered'; row.delivered_at=now; row.last_error=''; processed+=1
            else:
                raise RuntimeError(f'HTTP {response.status_code}: {response.text[:500]}')
        except Exception as exc:
            row.attempts=int(row.attempts or 0)+1
            row.last_error=str(exc)[:2000]
            if row.attempts>=5:
                row.status='failed'
            else:
                row.status='retry'
                row.next_attempt_at=now+timedelta(minutes=min(60,2**row.attempts))
    db.commit()
    return processed
