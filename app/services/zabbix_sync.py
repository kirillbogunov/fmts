from __future__ import annotations
import json, ssl
from urllib import request as urlrequest
from sqlalchemy.orm import Session
from app.config import get_settings
from app.models import Equipment, Site

settings = get_settings()

def _rpc(method: str, params: dict, auth: str | None = None, req_id: int = 1):
    if not settings.zabbix_url:
        raise RuntimeError('ZABBIX_URL не настроен')
    payload = {'jsonrpc':'2.0','method':method,'params':params,'id':req_id}
    if auth:
        payload['auth'] = auth
    data = json.dumps(payload).encode('utf-8')
    req = urlrequest.Request(settings.zabbix_url, data=data, headers={'Content-Type':'application/json-rpc'}, method='POST')
    context = None
    if settings.zabbix_url.startswith('https://') and not settings.zabbix_verify_ssl:
        context = ssl._create_unverified_context()
    with urlrequest.urlopen(req, timeout=20, context=context) as resp:
        result = json.loads(resp.read().decode('utf-8'))
    if result.get('error'):
        raise RuntimeError(f"Zabbix API: {result['error'].get('data') or result['error'].get('message')}")
    return result.get('result')

def _auth_token() -> str:
    if settings.zabbix_token:
        return settings.zabbix_token
    if not (settings.zabbix_username and settings.zabbix_password):
        raise RuntimeError('Укажите ZABBIX_TOKEN либо ZABBIX_USERNAME/ZABBIX_PASSWORD')
    return _rpc('user.login', {'username': settings.zabbix_username, 'password': settings.zabbix_password})

def sync_zabbix(db: Session, site_id: int | None = None) -> dict:
    if not settings.zabbix_enabled:
        return {'enabled': False, 'created': 0, 'updated': 0, 'seen': 0}
    site = db.get(Site, site_id or settings.zabbix_default_site_id)
    if not site:
        raise RuntimeError('ZABBIX_DEFAULT_SITE_ID не указывает на существующий объект')
    auth = _auth_token()
    hosts = _rpc('host.get', {
        'output':['hostid','host','name','status'],
        'selectInventory':['model','serialno_a','asset_tag','location'],
        'selectInterfaces':['ip','dns','available'],
        'sortfield':'name'
    }, auth=auth, req_id=2) or []
    created = updated = 0
    for host in hosts:
        hostid = str(host.get('hostid') or '').strip()
        if not hostid:
            continue
        row = db.query(Equipment).filter(Equipment.external_source=='zabbix', Equipment.external_key==hostid).first()
        inv = host.get('inventory') or {}
        iface = (host.get('interfaces') or [{}])[0] or {}
        name = (host.get('name') or host.get('host') or f'Zabbix host {hostid}')[:200]
        model = (inv.get('model') or iface.get('dns') or iface.get('ip') or '')[:120]
        serial = (inv.get('serialno_a') or '')[:120]
        category = 'IT / Zabbix'
        available = str(iface.get('available') or '0')
        status = 'broken' if available == '2' else 'working'
        if not row:
            inventory_no = (inv.get('asset_tag') or f'ZBX-{hostid}')[:100]
            base = inventory_no
            n = 2
            while db.query(Equipment.id).filter(Equipment.inventory_no==inventory_no).first():
                inventory_no = f'{base}-{n}'; n += 1
            import secrets
            row = Equipment(site_id=site.id, name=name, inventory_no=inventory_no, qr_token=secrets.token_urlsafe(24), external_source='zabbix', external_key=hostid)
            db.add(row); created += 1
        else:
            updated += 1
        row.site_id = site.id
        row.name = name
        row.category = category
        row.model = model
        row.serial_no = serial
        row.status = status
        row.external_source = 'zabbix'
        row.external_key = hostid
    db.commit()
    return {'enabled': True, 'created': created, 'updated': updated, 'seen': len(hosts)}
