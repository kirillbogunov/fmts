from __future__ import annotations
import json
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.models import ReportSubscription, Ticket, User
from app.services.notifications import send_email

OPEN={'new','assigned','in_progress','waiting'}

def process_report_subscriptions(db:Session)->int:
    now=datetime.utcnow(); sent=0
    rows=db.query(ReportSubscription).filter(ReportSubscription.active==True).all()
    for sub in rows:
        user=db.get(User,sub.user_id)
        if not user or not user.active or not user.email: continue
        due=False
        if not sub.last_sent_at: due=True
        elif sub.periodicity=='weekly' and sub.last_sent_at <= now-timedelta(days=7): due=True
        elif sub.periodicity=='monthly' and (sub.last_sent_at.year,sub.last_sent_at.month)!=(now.year,now.month): due=True
        if not due: continue
        q=db.query(Ticket)
        if user.role=='technician': q=q.filter(Ticket.assignee_id==user.id)
        elif user.role=='requester': q=q.filter(Ticket.requester_id==user.id)
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
    if sent: db.commit()
    return sent
