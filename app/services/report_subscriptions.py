from __future__ import annotations
import json
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import or_
from app.models import FilterSubscription, ReportSubscription, SavedFilter, Ticket, User
from app.services.notifications import send_email
from app.access import scope_ticket_query

OPEN={'new','assigned','in_progress','waiting'}


def _due(periodicity: str, last_sent_at: datetime | None, now: datetime) -> bool:
    if not last_sent_at:
        return True
    if periodicity == 'daily':
        return last_sent_at.date() != now.date()
    if periodicity == 'weekly':
        return last_sent_at <= now - timedelta(days=7)
    if periodicity == 'monthly':
        return (last_sent_at.year,last_sent_at.month) != (now.year,now.month)
    return False


def _apply_saved_filter(q, payload: dict):
    if payload.get('status'):
        q = q.filter(Ticket.status == payload['status'])
    if payload.get('priority'):
        q = q.filter(Ticket.priority == payload['priority'])
    if payload.get('site_id'):
        try: q = q.filter(Ticket.site_id == int(payload['site_id']))
        except Exception: pass
    if payload.get('assignee_id'):
        try: q = q.filter(Ticket.assignee_id == int(payload['assignee_id']))
        except Exception: pass
    text = str(payload.get('q') or '').strip()
    if text:
        like = f'%{text}%'
        q = q.filter(or_(Ticket.number.ilike(like), Ticket.title.ilike(like), Ticket.description.ilike(like), Ticket.requester_name.ilike(like)))
    return q


def process_report_subscriptions(db:Session)->int:
    now=datetime.utcnow(); sent=0
    rows=db.query(ReportSubscription).filter(ReportSubscription.active==True).all()
    for sub in rows:
        user=db.get(User,sub.user_id)
        if not user or not user.active or not user.email or not _due(sub.periodicity, sub.last_sent_at, now):
            continue
        q=scope_ticket_query(db.query(Ticket), user)
        open_count=q.filter(Ticket.status.in_(OPEN)).count()
        overdue=q.filter(Ticket.status.in_({'new','assigned','in_progress'}),Ticket.sla_due_at<now).count()
        total=q.count()
        cfg={}
        try: cfg=json.loads(sub.config_json or '{}')
        except Exception: pass
        body=(f'Отчёт FMTS: {sub.name}\n'
              f'Всего заявок в области доступа: {total}\n'
              f'Открыто: {open_count}\nПросрочено: {overdue}\n'
              f'Группировка: {cfg.get("group_by","site")}\n')
        if send_email(user.email,f'FMTS — {sub.name}',body):
            sub.last_sent_at=now; sent+=1

    filter_rows=db.query(FilterSubscription).filter(FilterSubscription.active==True).all()
    for sub in filter_rows:
        user=db.get(User,sub.user_id); saved=db.get(SavedFilter,sub.saved_filter_id)
        if not user or not user.active or not user.email or not saved or saved.user_id != user.id or not _due(sub.periodicity, sub.last_sent_at, now):
            continue
        try:
            payload=json.loads(saved.filters_json or '{}')
        except Exception:
            payload={}
        q=_apply_saved_filter(scope_ticket_query(db.query(Ticket), user), payload)
        tickets=q.order_by(Ticket.id.desc()).limit(50).all()
        lines=[f'Подписка FMTS: {sub.name}', f'Сохранённый фильтр: {saved.name}', f'Найдено: {q.count()}', '']
        for t in tickets[:15]:
            lines.append(f'{t.number} · {t.title} · {t.status} · {t.priority}')
        if len(tickets) > 15:
            lines.append(f'…и ещё {len(tickets)-15}')
        if send_email(user.email, f'FMTS — {sub.name}', '\n'.join(lines)):
            sub.last_sent_at=now; sent+=1
    if sent: db.commit()
    return sent
