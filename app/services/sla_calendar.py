from __future__ import annotations
import json
from datetime import datetime, timedelta, time, timezone
from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session
from app.models import BusinessCalendar, ServiceCatalog, Ticket


def _holiday_set(calendar: BusinessCalendar) -> set[str]:
    try:
        data=json.loads(calendar.holidays_json or '[]')
        return {str(x) for x in data if x}
    except Exception:
        return set()


def _working_days(calendar: BusinessCalendar) -> set[int]:
    try:
        return {int(x) for x in (calendar.weekdays or '0,1,2,3,4').split(',') if str(x).strip()}
    except Exception:
        return {0,1,2,3,4}


def _parse_hhmm(value: str, default: str) -> time:
    try:
        h,m=(value or default).split(':',1)
        return time(int(h),int(m))
    except Exception:
        h,m=default.split(':')
        return time(int(h),int(m))


def _zone(calendar: BusinessCalendar) -> ZoneInfo:
    try: return ZoneInfo(calendar.timezone or 'Asia/Almaty')
    except Exception: return ZoneInfo('Asia/Almaty')


def _is_workday(local_dt: datetime, calendar: BusinessCalendar) -> bool:
    return local_dt.weekday() in _working_days(calendar) and local_dt.date().isoformat() not in _holiday_set(calendar)


def _window(local_dt: datetime, calendar: BusinessCalendar) -> tuple[datetime, datetime]:
    start=_parse_hhmm(calendar.work_start,'09:00')
    end=_parse_hhmm(calendar.work_end,'18:00')
    return (
        local_dt.replace(hour=start.hour,minute=start.minute,second=0,microsecond=0),
        local_dt.replace(hour=end.hour,minute=end.minute,second=0,microsecond=0),
    )


def _next_business_start(local_dt: datetime, calendar: BusinessCalendar) -> datetime:
    cur=local_dt
    for _ in range(370):
        start,end=_window(cur,calendar)
        if _is_workday(cur,calendar):
            if cur < start: return start
            if start <= cur < end: return cur
        cur=(cur+timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0)
    return local_dt


def add_business_minutes(start_utc: datetime, minutes: int, calendar: BusinessCalendar) -> datetime:
    if minutes <= 0: return start_utc
    zone=_zone(calendar)
    aware=start_utc.replace(tzinfo=timezone.utc) if start_utc.tzinfo is None else start_utc.astimezone(timezone.utc)
    cur=_next_business_start(aware.astimezone(zone),calendar)
    remaining=int(minutes)
    guard=0
    while remaining>0 and guard<10000:
        guard+=1
        if not _is_workday(cur,calendar):
            cur=_next_business_start(cur+timedelta(days=1),calendar); continue
        _,end=_window(cur,calendar)
        if cur>=end:
            cur=_next_business_start(cur+timedelta(days=1),calendar); continue
        available=max(0,int((end-cur).total_seconds()//60))
        if remaining<=available:
            cur=cur+timedelta(minutes=remaining); remaining=0; break
        remaining-=available
        cur=_next_business_start((cur+timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0),calendar)
    return cur.astimezone(timezone.utc).replace(tzinfo=None)


def business_minutes_between(start_utc: datetime, end_utc: datetime, calendar: BusinessCalendar) -> int:
    if end_utc<=start_utc: return 0
    zone=_zone(calendar)
    start=(start_utc.replace(tzinfo=timezone.utc) if start_utc.tzinfo is None else start_utc.astimezone(timezone.utc)).astimezone(zone)
    end=(end_utc.replace(tzinfo=timezone.utc) if end_utc.tzinfo is None else end_utc.astimezone(timezone.utc)).astimezone(zone)
    total=0; cur=start.replace(hour=0,minute=0,second=0,microsecond=0)
    while cur.date()<=end.date():
        if _is_workday(cur,calendar):
            ws,we=_window(cur,calendar)
            left=max(start,ws); right=min(end,we)
            if right>left: total+=int((right-left).total_seconds()//60)
        cur+=timedelta(days=1)
    return total


def apply_service_sla(db: Session, ticket: Ticket, service: ServiceCatalog | None, *, start_at: datetime | None=None, fallback_resolution_minutes: int | None=None) -> None:
    start_at=start_at or ticket.created_at or datetime.utcnow()
    calendar=None
    if service and service.business_calendar_id:
        calendar=db.get(BusinessCalendar,service.business_calendar_id)
    if not calendar:
        calendar=db.query(BusinessCalendar).filter(BusinessCalendar.active==True).order_by(BusinessCalendar.id).first()
    ticket.business_calendar_id=calendar.id if calendar else None

    response_minutes=(service.response_sla_minutes if service and service.response_sla_minutes else None)
    resolution_minutes=(service.resolution_sla_minutes if service and service.resolution_sla_minutes else None)
    if resolution_minutes is None and service and service.default_sla_hours:
        resolution_minutes=int(service.default_sla_hours)*60
    if resolution_minutes is None:
        resolution_minutes=fallback_resolution_minutes

    if response_minutes:
        ticket.response_due_at=add_business_minutes(start_at,int(response_minutes),calendar) if calendar else start_at+timedelta(minutes=int(response_minutes))
    if resolution_minutes:
        ticket.sla_due_at=add_business_minutes(start_at,int(resolution_minutes),calendar) if calendar else start_at+timedelta(minutes=int(resolution_minutes))


def mark_first_response(db: Session, ticket: Ticket, *, actor_role: str | None=None, when: datetime | None=None) -> bool:
    if ticket.first_response_at or actor_role=='requester':
        return False
    ticket.first_response_at=when or datetime.utcnow()
    return True

def parse_local_to_utc(value: str, tz_name: str) -> datetime | None:
    if not value:
        return None
    try:
        dt=datetime.fromisoformat(value)
        zone=ZoneInfo(tz_name or 'Asia/Almaty')
        if dt.tzinfo is None:
            dt=dt.replace(tzinfo=zone)
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:
        return None
