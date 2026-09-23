from __future__ import annotations
import json, smtplib
from email.message import EmailMessage
from urllib import request as urlrequest
from sqlalchemy.orm import Session
from app.config import get_settings
from app.models import Notification, PushSubscription, User

settings=get_settings()

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

def send_webpush(subscription:PushSubscription, title:str, body:str, link:str='')->bool:
    if not (settings.push_vapid_private_key and settings.push_vapid_public_key): return False
    try:
        from pywebpush import webpush
        info={'endpoint':subscription.endpoint,'keys':{'p256dh':subscription.p256dh,'auth':subscription.auth}}
        webpush(info,data=json.dumps({'title':title,'body':body,'link':link}),vapid_private_key=settings.push_vapid_private_key,
                vapid_claims={'sub':settings.push_vapid_subject})
        return True
    except Exception as exc:
        print('webpush error:',exc); return False

def notify_user(db:Session, user:User|None, title:str, body:str='', link:str='', level:str='info', dedup_key:str|None=None, external:bool=True):
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
        for sub in db.query(PushSubscription).filter(PushSubscription.user_id==user.id).all():
            send_webpush(sub,title,body,link)
    return row

def notify_role(db:Session, roles:set[str], title:str, body:str='', link:str='', level:str='info', dedup_prefix:str=''):
    for u in db.query(User).filter(User.active==True,User.role.in_(roles)).all():
        key=f'{dedup_prefix}:{u.id}' if dedup_prefix else None
        notify_user(db,u,title,body,link,level,key)
