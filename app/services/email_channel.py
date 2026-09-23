from __future__ import annotations
import email, imaplib, re
from datetime import datetime, timedelta
from email.header import decode_header
from email.utils import parseaddr
from sqlalchemy.orm import Session
from app.config import get_settings
from app.models import Site, Ticket, User, TicketComment
from app.services.maintenance import next_ticket_number
from app.services.automation import apply_ticket_rules
settings=get_settings()

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

def poll_mailbox(db:Session)->int:
    if not (settings.imap_enabled and settings.imap_host and settings.imap_username and settings.imap_default_site_id): return 0
    site=db.get(Site,settings.imap_default_site_id)
    if not site: return 0
    client=None; created=0
    try:
        cls=imaplib.IMAP4_SSL if settings.imap_use_ssl else imaplib.IMAP4
        client=cls(settings.imap_host,settings.imap_port); client.login(settings.imap_username,settings.imap_password); client.select(settings.imap_folder)
        typ,data=client.search(None,'UNSEEN')
        if typ!='OK': return 0
        for num in data[0].split()[-25:]:
            typ,msgdata=client.fetch(num,'(RFC822)')
            if typ!='OK': continue
            msg=email.message_from_bytes(msgdata[0][1]); sender_name,sender_email=parseaddr(msg.get('From',''))
            subject=_decode(msg.get('Subject','')) or 'Заявка из e-mail'; body=_body(msg)
            u=db.query(User).filter(User.email==sender_email,User.active==True).first() if sender_email else None
            match=re.search(r'\bSR-\d{6}-\d{3}\b',subject,re.I)
            existing=db.query(Ticket).filter(Ticket.number==match.group(0).upper()).first() if match else None
            if existing:
                db.add(TicketComment(ticket_id=existing.id,user_id=u.id if u else None,body=(body or f'E-mail от {sender_email}')[:12000])); created+=1; continue
            t=Ticket(number=next_ticket_number(db),title=subject[:220],description=body,category='Другое',priority='normal',status='new',site_id=site.id,
                     requester_id=u.id if u else None,requester_name=(u.full_name if u else sender_name or sender_email or 'E-mail'),requester_phone='',room='',
                     sla_due_at=datetime.utcnow()+timedelta(hours=24))
            db.add(t); db.flush(); apply_ticket_rules(db,t); created+=1
        db.commit(); return created
    except Exception as exc:
        db.rollback(); print('imap poll error:',exc); return 0
    finally:
        if client:
            try: client.logout()
            except Exception: pass
