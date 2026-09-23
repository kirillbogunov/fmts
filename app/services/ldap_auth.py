from __future__ import annotations
from collections import defaultdict
from sqlalchemy.orm import Session
from app.config import get_settings
from app.models import User, Department
from app.security import hash_password
settings=get_settings()


def _value(entry, name: str, default: str="") -> str:
    try:
        value=getattr(entry,name)
        return str(value.value if hasattr(value,'value') else value or default)
    except Exception:
        return default


def authenticate_ldap(db:Session, username:str, password:str)->User|None:
    if not (settings.ldap_enabled and settings.ldap_server and username and password): return None
    try:
        from ldap3 import Server, Connection, ALL, SUBTREE
        server=Server(settings.ldap_server,port=settings.ldap_port,use_ssl=settings.ldap_use_ssl,get_info=ALL)
        if settings.ldap_bind_dn:
            admin=Connection(server,user=settings.ldap_bind_dn,password=settings.ldap_bind_password,auto_bind=True)
            filt=f'({settings.ldap_username_attr}={username})'
            attrs=[settings.ldap_display_name_attr,settings.ldap_email_attr,settings.ldap_phone_attr,settings.ldap_department_attr,settings.ldap_manager_attr]
            admin.search(settings.ldap_user_base_dn,filt,search_scope=SUBTREE,attributes=attrs)
            if not admin.entries: return None
            entry=admin.entries[0]; user_dn=entry.entry_dn
            Connection(server,user=user_dn,password=password,auto_bind=True).unbind()
            full=_value(entry,settings.ldap_display_name_attr,username) or username
            email=_value(entry,settings.ldap_email_attr); phone=_value(entry,settings.ldap_phone_attr)
        else:
            Connection(server,user=username,password=password,auto_bind=True).unbind(); full=username; email=''; phone=''; user_dn=''
        u=db.query(User).filter(User.username==username).first()
        if not u:
            u=User(username=username,full_name=full,password_hash=hash_password(password),role='requester',active=True,email=email,phone=phone,external_dn=user_dn,directory_source='ldap'); db.add(u)
        else:
            u.full_name=full or u.full_name; u.email=email or u.email; u.phone=phone or u.phone; u.external_dn=user_dn or u.external_dn; u.directory_source='ldap'
        db.commit(); db.refresh(u); return u
    except Exception as exc:
        print('ldap auth error:',exc); return None


def sync_ldap_directory(db: Session) -> dict:
    """Synchronize users, departments and manager links from AD/LDAP."""
    if not (settings.ldap_enabled and settings.ldap_server and settings.ldap_bind_dn and settings.ldap_user_base_dn):
        raise RuntimeError('LDAP/AD не настроен для синхронизации')
    from ldap3 import Server, Connection, ALL, SUBTREE
    server=Server(settings.ldap_server,port=settings.ldap_port,use_ssl=settings.ldap_use_ssl,get_info=ALL)
    conn=Connection(server,user=settings.ldap_bind_dn,password=settings.ldap_bind_password,auto_bind=True)
    attrs=[settings.ldap_username_attr,settings.ldap_display_name_attr,settings.ldap_email_attr,settings.ldap_phone_attr,settings.ldap_department_attr,settings.ldap_manager_attr]
    ok=conn.search(settings.ldap_user_base_dn,settings.ldap_sync_filter,search_scope=SUBTREE,attributes=attrs)
    if not ok:
        raise RuntimeError(f'LDAP search failed: {conn.result}')
    entries=list(conn.entries)
    created=updated=departments_created=0
    by_dn={}
    manager_dn_by_user={}
    for entry in entries:
        username=_value(entry,settings.ldap_username_attr).strip()
        if not username: continue
        full=_value(entry,settings.ldap_display_name_attr,username).strip() or username
        email=_value(entry,settings.ldap_email_attr).strip(); phone=_value(entry,settings.ldap_phone_attr).strip()
        dep_name=_value(entry,settings.ldap_department_attr).strip()
        dep=None
        if dep_name:
            dep=db.query(Department).filter(Department.name==dep_name).first()
            if not dep:
                dep=Department(name=dep_name,external_key=dep_name,active=True); db.add(dep); db.flush(); departments_created+=1
        user=db.query(User).filter(User.username==username).first()
        if not user:
            user=User(username=username,full_name=full,password_hash=hash_password('LDAP-managed-account-disabled-local-login'),role='requester',active=True,email=email,phone=phone,directory_source='ldap',external_dn=entry.entry_dn,department_id=dep.id if dep else None)
            db.add(user); db.flush(); created+=1
        else:
            user.full_name=full; user.email=email or user.email; user.phone=phone or user.phone; user.directory_source='ldap'; user.external_dn=entry.entry_dn; user.department_id=dep.id if dep else user.department_id; updated+=1
        by_dn[entry.entry_dn.lower()]=user
        manager_dn_by_user[user.id]=_value(entry,settings.ldap_manager_attr).strip().lower()
    db.flush()
    # Resolve manager DNs, including managers already present from previous syncs.
    existing={u.external_dn.lower():u for u in db.query(User).filter(User.external_dn!='').all() if u.external_dn}
    existing.update(by_dn)
    linked=0
    for user_id,manager_dn in manager_dn_by_user.items():
        if not manager_dn: continue
        user=db.get(User,user_id); manager=existing.get(manager_dn)
        if user and manager and user.id!=manager.id:
            user.manager_user_id=manager.id; linked+=1
    db.commit(); conn.unbind()
    return {'found':len(entries),'created':created,'updated':updated,'departments_created':departments_created,'manager_links':linked}
