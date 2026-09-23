from __future__ import annotations
from sqlalchemy.orm import Session
from app.config import get_settings
from app.models import User
from app.security import hash_password
settings=get_settings()

def authenticate_ldap(db:Session, username:str, password:str)->User|None:
    if not (settings.ldap_enabled and settings.ldap_server and username and password): return None
    try:
        from ldap3 import Server, Connection, ALL, SUBTREE
        server=Server(settings.ldap_server,port=settings.ldap_port,use_ssl=settings.ldap_use_ssl,get_info=ALL)
        if settings.ldap_bind_dn:
            admin=Connection(server,user=settings.ldap_bind_dn,password=settings.ldap_bind_password,auto_bind=True)
            filt=f'({settings.ldap_username_attr}={username})'
            admin.search(settings.ldap_user_base_dn,filt,search_scope=SUBTREE,attributes=['displayName','mail','telephoneNumber'])
            if not admin.entries: return None
            entry=admin.entries[0]; user_dn=entry.entry_dn
            Connection(server,user=user_dn,password=password,auto_bind=True).unbind()
            full=str(getattr(entry,'displayName',username) or username); email=str(getattr(entry,'mail','') or ''); phone=str(getattr(entry,'telephoneNumber','') or '')
        else:
            Connection(server,user=username,password=password,auto_bind=True).unbind(); full=username; email=''; phone=''
        u=db.query(User).filter(User.username==username).first()
        if not u:
            u=User(username=username,full_name=full,password_hash=hash_password(password),role='requester',active=True,email=email,phone=phone); db.add(u)
        else:
            u.full_name=full or u.full_name; u.email=email or u.email; u.phone=phone or u.phone
        db.commit(); db.refresh(u); return u
    except Exception as exc:
        print('ldap auth error:',exc); return None
