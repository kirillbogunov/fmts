from __future__ import annotations
import base64, json, os, smtplib, tempfile
from datetime import datetime
from email.message import EmailMessage
from urllib import request as urlrequest
from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session
from app.config import get_settings
from app.models import Notification, PushSubscription, User

settings=get_settings()

PUSH_PREF_FIELDS={
    'assignment':'push_assignments',
    'comment':'push_comments',
    'status':'push_status',
    'sla':'push_sla',
    'maintenance':'push_maintenance',
    'reminder':'push_reminders',
    'inventory':'push_inventory',
    'general':'push_general',
}

def _post_json(url:str, payload:dict, headers:dict|None=None, timeout:int=8):
    data=json.dumps(payload).encode('utf-8')
    req=urlrequest.Request(url,data=data,headers={'Content-Type':'application/json',**(headers or {})},method='POST')
    with urlrequest.urlopen(req,timeout=timeout) as resp:
        return resp.read()

def send_email(to:str, subject:str, body:str)->bool:
    if not (settings.smtp_enabled and settings.smtp_host and to): return False
    msg=EmailMessage(); msg['Subject']=subject; msg['From']=settings.smtp_from or settings.smtp_username; msg['To']=to; msg.set_content(body)
    try:
        smtp=smtplib.SMTP(settings.smtp_host,settings.smtp_port,timeout=10)
        if settings.smtp_use_tls: smtp.starttls()
        if settings.smtp_username: smtp.login(settings.smtp_username,settings.smtp_password)
        smtp.send_message(msg); smtp.quit(); return True
    except Exception as exc:
        print('smtp notification error:',exc); return False

def send_telegram(chat_id:str, text:str)->bool:
    if not (settings.telegram_bot_token and chat_id): return False
    try:
        _post_json(f'https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage',{'chat_id':chat_id,'text':text})
        return True
    except Exception as exc:
        print('telegram notification error:',exc); return False

def send_whatsapp(phone:str, text:str)->bool:
    if not (settings.whatsapp_webhook_url and phone): return False
    headers={}
    if settings.whatsapp_webhook_token: headers['Authorization']=f'Bearer {settings.whatsapp_webhook_token}'
    try:
        _post_json(settings.whatsapp_webhook_url,{'to':phone,'message':text},headers=headers)
        return True
    except Exception as exc:
        print('whatsapp notification error:',exc); return False

def _vapid_private_value():
    """Return a pywebpush-compatible private key value and cleanup callback.

    `base64:<...>` is supported for Render-friendly one-line environment variables.
    Plain values remain backward compatible with earlier FMTS installations.
    """
    value=(settings.push_vapid_private_key or '').strip()
    if not value.startswith('base64:'):
        return value, None
    try:
        raw=base64.b64decode(value.split(':',1)[1])
        tmp=tempfile.NamedTemporaryFile(prefix='fmts-vapid-',suffix='.pem',delete=False)
        tmp.write(raw); tmp.flush(); tmp.close()
        return tmp.name, lambda: os.path.exists(tmp.name) and os.unlink(tmp.name)
    except Exception:
        return value, None

def send_webpush(subscription:PushSubscription, title:str, body:str, link:str='', level:str='info')->bool:
    if not (settings.push_vapid_private_key and settings.push_vapid_public_key and subscription.active): return False
    private_key,cleanup=_vapid_private_value()
    try:
        from pywebpush import webpush
        info={'endpoint':subscription.endpoint,'keys':{'p256dh':subscription.p256dh,'auth':subscription.auth}}
        payload={
            'title':title,
            'body':body,
            'link':link or '/notifications',
            'level':level,
            'tag':f'fmts-{subscription.user_id}-{abs(hash((title,link))) % 1000000}',
        }
        webpush(info,data=json.dumps(payload,ensure_ascii=False),vapid_private_key=private_key,
                vapid_claims={'sub':settings.push_vapid_subject})
        subscription.updated_at=datetime.utcnow()
        return True
    except Exception as exc:
        response=getattr(exc,'response',None)
        status=getattr(response,'status_code',None)
        if status in {404,410}:
            subscription.active=False
        print('webpush error:',exc)
        return False
    finally:
        if cleanup:
            try: cleanup()
            except Exception: pass

def _in_quiet_hours(user:User, now:datetime|None=None)->bool:
    start=(user.push_quiet_start or '').strip(); end=(user.push_quiet_end or '').strip()
    if not (start and end): return False
    try:
        zone=ZoneInfo(user.timezone or settings.default_timezone or 'UTC')
        current=(now or datetime.utcnow()).replace(tzinfo=ZoneInfo('UTC')).astimezone(zone).strftime('%H:%M')
        if start==end: return False
        if start<end: return start <= current < end
        return current >= start or current < end
    except Exception:
        return False

def push_allowed(user:User, event_type:str='general', now:datetime|None=None)->bool:
    if not user.active or not getattr(user,'push_enabled',True): return False
    field=PUSH_PREF_FIELDS.get(event_type,'push_general')
    if not bool(getattr(user,field,True)): return False
    return not _in_quiet_hours(user,now)

def notify_user(db:Session, user:User|None, title:str, body:str='', link:str='', level:str='info', dedup_key:str|None=None,
                external:bool=True, event_type:str='general'):
    if not user or not user.active: return None
    if dedup_key:
        existing=db.query(Notification).filter(Notification.dedup_key==dedup_key).first()
        if existing: return existing
    row=Notification(user_id=user.id,title=title[:220],body=body,link=link,level=level,dedup_key=dedup_key)
    db.add(row); db.flush()
    if external:
        text=f'{title}\n{body}'.strip()
        send_email(user.email,title,text)
        send_telegram(user.telegram_chat_id,text)
        send_whatsapp(user.phone,text)
        if push_allowed(user,event_type):
            for sub in db.query(PushSubscription).filter(PushSubscription.user_id==user.id,PushSubscription.active==True).all():
                send_webpush(sub,title,body,link,level)
    return row

def notify_role(db:Session, roles:set[str], title:str, body:str='', link:str='', level:str='info', dedup_prefix:str='', event_type:str='general'):
    for u in db.query(User).filter(User.active==True,User.role.in_(roles)).all():
        key=f'{dedup_prefix}:{u.id}' if dedup_prefix else None
        notify_user(db,u,title,body,link,level,key,event_type=event_type)
