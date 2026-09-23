from __future__ import annotations
import email, imaplib, re
from datetime import datetime, timedelta
from email.header import decode_header
from email.utils import parseaddr, getaddresses
from sqlalchemy.orm import Session
from app.config import get_settings
from app.models import Site, Ticket, User, TicketComment, TicketObserver, EmailRule
from app.services.maintenance import next_ticket_number
from app.services.automation import apply_ticket_rules
from app.services.ticket_lifecycle import ensure_initial_history, transition_ticket
from app.services.sla_calendar import mark_first_response
from app.services.webhooks import enqueue_ticket_event
from app.services.operations import pick_group_assignee
from app.access import can_change_ticket_status
settings=get_settings()

STATUS_ALIASES={
    'new':'new','новая':'new','назначена':'assigned','assigned':'assigned',
    'в работе':'in_progress','работа':'in_progress','in_progress':'in_progress','working':'in_progress',
    'ожидание':'waiting','ожидание материалов':'waiting','waiting':'waiting',
    'выполнена':'resolved','resolved':'resolved','готово':'resolved',
    'закрыта':'closed','closed':'closed','отменена':'cancelled','cancelled':'cancelled',
}

def _decode(value:str)->str:
    parts=[]
    for chunk,enc in decode_header(value or ''):
        if isinstance(chunk,bytes): parts.append(chunk.decode(enc or 'utf-8',errors='replace'))
        else: parts.append(chunk)
    return ''.join(parts).strip()

def _body(msg)->str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type()=='text/plain' and 'attachment' not in str(part.get('Content-Disposition','')):
                data=part.get_payload(decode=True) or b''; return data.decode(part.get_content_charset() or 'utf-8',errors='replace')[:12000]
        return ''
    data=msg.get_payload(decode=True) or b''; return data.decode(msg.get_content_charset() or 'utf-8',errors='replace')[:12000]

def _recipients(msg)->list[str]:
    raw=[]
    for h in ('To','Cc'):
        raw.extend(msg.get_all(h,[]) or [])
    return sorted({addr.lower() for _,addr in getaddresses(raw) if addr})

def _add_known_observers(db:Session,ticket:Ticket,emails:list[str],created_by_id:int|None=None)->int:
    added=0
    if not settings.email_add_recipients_as_observers: return added
    for addr in emails:
        user=db.query(User).filter(User.email==addr,User.active==True).first()
        if not user or user.id in {ticket.requester_id,ticket.assignee_id}: continue
        exists=db.query(TicketObserver.id).filter(TicketObserver.ticket_id==ticket.id,TicketObserver.user_id==user.id).first()
        if not exists:
            db.add(TicketObserver(ticket_id=ticket.id,user_id=user.id,created_by_id=created_by_id)); added+=1
    return added

def _extract_status_command(subject:str,body:str)->str|None:
    if not settings.email_status_commands_enabled: return None
    text=f'{subject}\n{body}'
    patterns=[r'\[\s*status\s*:\s*([^\]]+)\]',r'\[\s*статус\s*:\s*([^\]]+)\]',r'^\s*#?статус\s*:\s*(.+)$',r'^\s*#?status\s*:\s*(.+)$']
    for pat in patterns:
        m=re.search(pat,text,re.I|re.M)
        if m:
            key=m.group(1).strip().lower()
            return STATUS_ALIASES.get(key)
    return None

def _rule_schedule_matches(rule:EmailRule, now:datetime|None=None)->bool:
    now=now or datetime.now()
    try:
        days={int(x) for x in (rule.active_days or "0,1,2,3,4,5,6").split(",") if x.strip()}
    except Exception:
        days=set(range(7))
    if now.weekday() not in days: return False
    current=now.strftime("%H:%M"); start=rule.time_from or "00:00"; end=rule.time_to or "23:59"
    if start <= end: return start <= current <= end
    return current >= start or current <= end

def _apply_email_rule(db:Session,ticket:Ticket,sender:str,subject:str,recipients:list[str])->EmailRule|None:
    for rule in db.query(EmailRule).filter(EmailRule.active==True).order_by(EmailRule.sort_order,EmailRule.id).all():
        if not _rule_schedule_matches(rule): continue
        if rule.sender_contains and rule.sender_contains.lower() not in sender.lower(): continue
        if rule.subject_contains and rule.subject_contains.lower() not in subject.lower(): continue
        if rule.recipient_contains and not any(rule.recipient_contains.lower() in r.lower() for r in recipients): continue
        if rule.category: ticket.category=rule.category
        if rule.priority: ticket.priority=rule.priority
        if rule.group_id:
            ticket.group_id=rule.group_id
            assignee=pick_group_assignee(db,rule.group_id)
            if assignee:
                ticket.assignee_id=assignee.id; ticket.master_name=assignee.full_name; ticket.status='assigned'
        if rule.add_recipients_as_observers:
            _add_known_observers(db,ticket,recipients,ticket.creator_id)
        return rule
    return None

def process_message(db:Session,msg)->tuple[str,int|None]:
    sender_name,sender_email=parseaddr(msg.get('From','')); sender_email=sender_email.lower()
    subject=_decode(msg.get('Subject','')) or 'Заявка из e-mail'; body=_body(msg); recipients=_recipients(msg)
    u=db.query(User).filter(User.email==sender_email,User.active==True).first() if sender_email else None
    match=re.search(r'\bSR-\d{6}-\d{3}\b',subject,re.I)
    existing=db.query(Ticket).filter(Ticket.number==match.group(0).upper()).first() if match else None
    if existing:
        db.add(TicketComment(ticket_id=existing.id,user_id=u.id if u else None,body=(body or f'E-mail от {sender_email}')[:12000]))
        if u and u.role!='requester': mark_first_response(db,existing,actor_role=u.role)
        _add_known_observers(db,existing,recipients,u.id if u else None)
        cmd=_extract_status_command(subject,body)
        if cmd and u:
            decision=can_change_ticket_status(u,existing,cmd)
            if decision.allowed:
                transition_ticket(db,existing,cmd,user_id=u.id,source='email')
        enqueue_ticket_event(db,'ticket.comment',existing,{'source':'email','author_id':u.id if u else None,'comment':(body or '')[:1000]})
        return 'comment',existing.id
    site=db.get(Site,settings.imap_default_site_id)
    if not site: raise RuntimeError('IMAP_DEFAULT_SITE_ID не указывает на существующий объект')
    t=Ticket(number=next_ticket_number(db),title=subject[:220],description=body,category='Другое',priority='normal',status='new',site_id=site.id,
             requester_id=u.id if u else None,creator_id=u.id if u else None,requester_name=(u.full_name if u else sender_name or sender_email or 'E-mail'),requester_phone='',room='',
             sla_due_at=datetime.utcnow()+timedelta(hours=24))
    db.add(t); db.flush(); _apply_email_rule(db,t,sender_email,subject,recipients); apply_ticket_rules(db,t); ensure_initial_history(db,t,user_id=(u.id if u else None),source='email'); _add_known_observers(db,t,recipients,u.id if u else None); enqueue_ticket_event(db,'ticket.created',t,{'source':'email'})
    return 'ticket',t.id

def poll_mailbox(db:Session)->int:
    if not (settings.imap_enabled and settings.imap_host and settings.imap_username and settings.imap_default_site_id): return 0
    client=None; processed=0
    try:
        cls=imaplib.IMAP4_SSL if settings.imap_use_ssl else imaplib.IMAP4
        client=cls(settings.imap_host,settings.imap_port); client.login(settings.imap_username,settings.imap_password); client.select(settings.imap_folder)
        typ,data=client.search(None,'UNSEEN')
        if typ!='OK': return 0
        for num in data[0].split()[-25:]:
            typ,msgdata=client.fetch(num,'(RFC822)')
            if typ!='OK': continue
            msg=email.message_from_bytes(msgdata[0][1]); process_message(db,msg); processed+=1
        db.commit(); return processed
    except Exception:
        db.rollback(); raise
    finally:
        if client:
            try: client.logout()
            except Exception: pass
