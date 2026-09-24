from __future__ import annotations
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_, func

from app.db import get_db
from app.models import (
    FilterSubscription, Resource, ResourceBooking, SavedFilter, ServiceCatalog, Site,
    SurveyResponse, SurveyTemplate, Ticket, TicketFeedback, User
)
from app.security import current_user
from app.access import can_view_ticket, has_permission, scope_ticket_query
from app.routes.web import ctx, templates, forbidden
from app.services.audit import audit
from app.services.localization import SUPPORTED_LOCALES, SUPPORTED_TIMEZONES
from app.services.zabbix_sync import sync_zabbix

router = APIRouter()


def _user(request: Request, db: Session):
    return current_user(request, db)


def _parse_local(value: str, tz_name: str) -> datetime:
    dt = datetime.fromisoformat(value)
    zone = ZoneInfo(tz_name or 'Asia/Almaty')
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=zone)
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _survey_questions(text: str) -> list[dict]:
    """Parse survey questions from the modern JSON builder or legacy line format.

    JSON is the primary UI format from v0.7.6.11 onward.  The old
    ``rating|Question`` format is still accepted so existing integrations and
    old forms keep working without a migration.
    """
    raw_text = (text or '').strip()
    rows: list[dict] = []
    if raw_text.startswith('['):
        try:
            payload = json.loads(raw_text)
        except Exception:
            payload = []
        if isinstance(payload, list):
            for item in payload:
                if not isinstance(item, dict):
                    continue
                kind = str(item.get('type') or 'rating').strip().lower()
                if kind not in {'rating','yesno','text'}:
                    kind = 'rating'
                label = str(item.get('label') or '').strip()[:500]
                if not label:
                    continue
                required = bool(item.get('required', kind != 'text'))
                rows.append({'type':kind,'label':label,'required':required})
        return rows[:30]

    for raw in raw_text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        if '|' in raw:
            kind, label = raw.split('|', 1)
        else:
            kind, label = 'rating', raw
        kind = kind.strip().lower()
        if kind not in {'rating','yesno','text'}:
            kind = 'rating'
        label = label.strip()[:500]
        if label:
            rows.append({'type':kind,'label':label,'required':kind != 'text'})
    return rows[:30]


@router.get('/subscriptions', response_class=HTMLResponse)
def subscriptions_page(request: Request, db: Session = Depends(get_db)):
    u = _user(request, db)
    if not u:
        return RedirectResponse('/login', 303)
    if not has_permission(u, 'subscription.self'):
        return forbidden(request, db, u, 'subscription.self')
    filters = db.query(SavedFilter).filter(SavedFilter.user_id == u.id).order_by(SavedFilter.name).all()
    rows = db.query(FilterSubscription).filter(FilterSubscription.user_id == u.id).order_by(FilterSubscription.name).all()
    return templates.TemplateResponse('subscriptions.html', ctx(request, db, filters=filters, rows=rows))


@router.post('/subscriptions/filter/new')
def subscription_new(request: Request, saved_filter_id: int = Form(...), name: str = Form(''), periodicity: str = Form('daily'), db: Session = Depends(get_db)):
    u = _user(request, db)
    if not u:
        return RedirectResponse('/login', 303)
    if not has_permission(u, 'subscription.self'):
        return forbidden(request, db, u, 'subscription.self')
    sf = db.get(SavedFilter, saved_filter_id)
    if not sf or sf.user_id != u.id:
        return RedirectResponse('/subscriptions', 303)
    periodicity = periodicity if periodicity in {'daily','weekly','monthly'} else 'daily'
    row = FilterSubscription(user_id=u.id, saved_filter_id=sf.id, name=(name.strip() or sf.name), periodicity=periodicity, active=True)
    db.add(row); db.commit(); db.refresh(row)
    audit(db, request, u, 'filter_subscription.create', entity_type='filter_subscription', entity_id=row.id, details=sf.name)
    return RedirectResponse('/subscriptions', 303)


@router.post('/subscriptions/filter/{sub_id}/toggle')
def subscription_toggle(sub_id: int, request: Request, db: Session = Depends(get_db)):
    u = _user(request, db)
    if not u:
        return RedirectResponse('/login', 303)
    row = db.get(FilterSubscription, sub_id)
    if row and row.user_id == u.id:
        row.active = not row.active; db.commit()
        audit(db, request, u, 'filter_subscription.toggle', entity_type='filter_subscription', entity_id=row.id, details=f'active={row.active}')
    return RedirectResponse('/subscriptions', 303)


@router.post('/subscriptions/filter/{sub_id}/delete')
def subscription_delete(sub_id: int, request: Request, db: Session = Depends(get_db)):
    u = _user(request, db)
    if not u:
        return RedirectResponse('/login', 303)
    row = db.get(FilterSubscription, sub_id)
    if row and row.user_id == u.id:
        db.delete(row); db.commit()
        audit(db, request, u, 'filter_subscription.delete', entity_type='filter_subscription', entity_id=sub_id)
    return RedirectResponse('/subscriptions', 303)


@router.get('/surveys', response_class=HTMLResponse)
def surveys_page(request: Request, db: Session = Depends(get_db)):
    u = _user(request, db)
    if not u:
        return RedirectResponse('/login', 303)
    if not (has_permission(u, 'survey.manage') or has_permission(u, 'survey.respond')):
        return forbidden(request, db, u, 'survey.respond')
    rows = db.query(SurveyTemplate).order_by(SurveyTemplate.name).all() if has_permission(u, 'survey.manage') else []
    responses = []
    survey_items = []
    stats = {'active': 0, 'responses': 0, 'avg_score': 0.0}
    if has_permission(u, 'survey.manage'):
        responses = db.query(SurveyResponse).order_by(SurveyResponse.id.desc()).limit(200).all()
        aggregates = {
            sid: (count or 0, float(avg or 0))
            for sid, count, avg in db.query(
                SurveyResponse.survey_id,
                func.count(SurveyResponse.id),
                func.avg(SurveyResponse.score),
            ).group_by(SurveyResponse.survey_id).all()
        }
        total_count = sum(v[0] for v in aggregates.values())
        weighted = sum(v[0] * v[1] for v in aggregates.values())
        stats = {
            'active': sum(1 for row in rows if row.active),
            'responses': total_count,
            'avg_score': round(weighted / total_count, 2) if total_count else 0.0,
        }
        for row in rows:
            count, avg = aggregates.get(row.id, (0, 0.0))
            try:
                questions = json.loads(row.questions_json or '[]')
            except Exception:
                questions = []
            normalized = []
            for q in questions if isinstance(questions, list) else []:
                if not isinstance(q, dict):
                    continue
                kind = str(q.get('type') or 'rating')
                label = str(q.get('label') or '').strip()
                if label:
                    normalized.append({'type': kind, 'label': label, 'required': bool(q.get('required', kind != 'text'))})
            survey_items.append({'row': row, 'questions': normalized, 'response_count': count, 'avg_score': round(avg, 2) if count else 0})
    services = db.query(ServiceCatalog).filter(ServiceCatalog.active == True).order_by(ServiceCatalog.name).all()
    return templates.TemplateResponse('surveys.html', ctx(request, db, rows=rows, survey_items=survey_items, responses=responses, services=services, stats=stats))


@router.post('/surveys/new')
def survey_new(request: Request, name: str = Form(...), service_id: str = Form(''), questions: str = Form(...), db: Session = Depends(get_db)):
    u = _user(request, db)
    if not u:
        return RedirectResponse('/login', 303)
    if not has_permission(u, 'survey.manage'):
        return forbidden(request, db, u, 'survey.manage')
    qs = _survey_questions(questions)
    if not qs:
        return RedirectResponse('/surveys', 303)
    row = SurveyTemplate(name=name.strip()[:180], service_id=int(service_id) if service_id else None, questions_json=json.dumps(qs, ensure_ascii=False), active=True)
    db.add(row); db.commit(); db.refresh(row)
    audit(db, request, u, 'survey.create', entity_type='survey', entity_id=row.id, details=row.name)
    return RedirectResponse('/surveys', 303)


@router.post('/surveys/{survey_id}/update')
def survey_update(survey_id: int, request: Request, name: str = Form(...), service_id: str = Form(''), questions: str = Form(...), db: Session = Depends(get_db)):
    u = _user(request, db)
    if not u:
        return RedirectResponse('/login', 303)
    if not has_permission(u, 'survey.manage'):
        return forbidden(request, db, u, 'survey.manage')
    row = db.get(SurveyTemplate, survey_id)
    if not row:
        return RedirectResponse('/surveys', 303)
    qs = _survey_questions(questions)
    if not qs:
        return RedirectResponse('/surveys', 303)
    new_name = name.strip()[:180]
    duplicate = db.query(SurveyTemplate.id).filter(SurveyTemplate.name == new_name, SurveyTemplate.id != row.id).first()
    if duplicate:
        return RedirectResponse('/surveys?error=name_exists', 303)
    row.name = new_name
    row.service_id = int(service_id) if service_id else None
    row.questions_json = json.dumps(qs, ensure_ascii=False)
    db.commit()
    audit(db, request, u, 'survey.update', entity_type='survey', entity_id=row.id, details=row.name)
    return RedirectResponse('/surveys', 303)


@router.post('/surveys/{survey_id}/toggle')
def survey_toggle(survey_id: int, request: Request, db: Session = Depends(get_db)):
    u = _user(request, db)
    if not u:
        return RedirectResponse('/login', 303)
    if not has_permission(u, 'survey.manage'):
        return forbidden(request, db, u, 'survey.manage')
    row = db.get(SurveyTemplate, survey_id)
    if row:
        row.active = not row.active; db.commit()
    return RedirectResponse('/surveys', 303)


@router.get('/tickets/{ticket_id}/survey', response_class=HTMLResponse)
def ticket_survey(ticket_id: int, request: Request, db: Session = Depends(get_db)):
    u = _user(request, db); ticket = db.get(Ticket, ticket_id)
    if not u:
        return RedirectResponse('/login', 303)
    if not ticket or not can_view_ticket(u, ticket, db):
        return forbidden(request, db, u, 'ticket.view')
    if ticket.status not in {'resolved','closed'}:
        return templates.TemplateResponse('survey_response.html', ctx(request, db, ticket=ticket, survey=None, questions=[], existing=None, message='Анкета доступна после выполнения заявки.'))
    survey = db.query(SurveyTemplate).filter(SurveyTemplate.active == True, or_(SurveyTemplate.service_id == ticket.service_id, SurveyTemplate.service_id.is_(None))).order_by(SurveyTemplate.service_id.desc()).first()
    existing = db.query(SurveyResponse).filter(SurveyResponse.ticket_id == ticket.id, SurveyResponse.user_id == u.id).first()
    questions = json.loads(survey.questions_json or '[]') if survey else []
    return templates.TemplateResponse('survey_response.html', ctx(request, db, ticket=ticket, survey=survey, questions=questions, existing=existing, message=None))


@router.post('/tickets/{ticket_id}/survey')
async def ticket_survey_submit(ticket_id: int, request: Request, db: Session = Depends(get_db)):
    u = _user(request, db); ticket = db.get(Ticket, ticket_id)
    if not u:
        return RedirectResponse('/login', 303)
    if not ticket or not can_view_ticket(u, ticket, db) or ticket.status not in {'resolved','closed'}:
        return forbidden(request, db, u, 'survey.respond')
    survey = db.query(SurveyTemplate).filter(SurveyTemplate.active == True, or_(SurveyTemplate.service_id == ticket.service_id, SurveyTemplate.service_id.is_(None))).order_by(SurveyTemplate.service_id.desc()).first()
    if not survey:
        return RedirectResponse(f'/tickets/{ticket.id}', 303)
    exists = db.query(SurveyResponse).filter(SurveyResponse.ticket_id == ticket.id, SurveyResponse.user_id == u.id).first()
    if exists:
        return RedirectResponse(f'/tickets/{ticket.id}/survey', 303)
    form = await request.form(); questions = json.loads(survey.questions_json or '[]')
    answers = {}; ratings = []
    for idx, q in enumerate(questions):
        value = str(form.get(f'q_{idx}', '')).strip()
        if q.get('required', q.get('type') != 'text') and not value:
            return RedirectResponse(f'/tickets/{ticket.id}/survey?error=required', 303)
        answers[str(idx)] = value
        if q.get('type') == 'rating':
            try:
                n = max(1, min(5, int(value))); ratings.append(n)
            except Exception:
                pass
    score = round(sum(ratings)/len(ratings), 2) if ratings else 0
    row = SurveyResponse(survey_id=survey.id, ticket_id=ticket.id, user_id=u.id, answers_json=json.dumps(answers, ensure_ascii=False), score=score)
    db.add(row)
    if ratings and not db.query(TicketFeedback.id).filter(TicketFeedback.ticket_id==ticket.id, TicketFeedback.user_id==u.id).first():
        db.add(TicketFeedback(ticket_id=ticket.id, user_id=u.id, rating=round(score), comment='Анкета качества'))
    db.commit(); audit(db, request, u, 'survey.respond', entity_type='ticket', entity_id=ticket.id, details=f'score={score}')
    return RedirectResponse(f'/tickets/{ticket.id}/survey', 303)


@router.get('/resources', response_class=HTMLResponse)
def resources_page(request: Request, db: Session = Depends(get_db)):
    u = _user(request, db)
    if not u:
        return RedirectResponse('/login', 303)
    if not has_permission(u, 'resource.view'):
        return forbidden(request, db, u, 'resource.view')
    resources = db.query(Resource).filter(Resource.active == True).order_by(Resource.resource_type, Resource.name).all()
    bookings = db.query(ResourceBooking).filter(ResourceBooking.end_at >= datetime.utcnow(), ResourceBooking.status == 'active').order_by(ResourceBooking.start_at).limit(500).all()
    sites = db.query(Site).order_by(Site.name).all()
    return templates.TemplateResponse('resources.html', ctx(request, db, resources=resources, bookings=bookings, sites=sites))


@router.post('/resources/new')
def resource_new(request: Request, name: str = Form(...), resource_type: str = Form('resource'), site_id: str = Form(''), capacity: int = Form(1), description: str = Form(''), db: Session = Depends(get_db)):
    u = _user(request, db)
    if not u:
        return RedirectResponse('/login', 303)
    if not has_permission(u, 'resource.manage'):
        return forbidden(request, db, u, 'resource.manage')
    row = Resource(name=name.strip()[:180], resource_type=resource_type.strip()[:80] or 'resource', site_id=int(site_id) if site_id else None, capacity=max(1, capacity), description=description.strip())
    db.add(row); db.commit(); db.refresh(row)
    audit(db, request, u, 'resource.create', entity_type='resource', entity_id=row.id, details=row.name)
    return RedirectResponse('/resources', 303)


@router.post('/resources/book')
def resource_book(request: Request, resource_id: int = Form(...), title: str = Form(...), start_at: str = Form(...), end_at: str = Form(...), notes: str = Form(''), db: Session = Depends(get_db)):
    u = _user(request, db)
    if not u:
        return RedirectResponse('/login', 303)
    if not has_permission(u, 'resource.book'):
        return forbidden(request, db, u, 'resource.book')
    resource = db.get(Resource, resource_id)
    if not resource or not resource.active:
        return RedirectResponse('/resources?error=resource', 303)
    start = _parse_local(start_at, u.timezone); end = _parse_local(end_at, u.timezone)
    if end <= start:
        return RedirectResponse('/resources?error=time', 303)
    overlap = db.query(ResourceBooking).filter(ResourceBooking.resource_id==resource.id, ResourceBooking.status=='active', ResourceBooking.start_at < end, ResourceBooking.end_at > start).count()
    if overlap >= max(1, resource.capacity):
        return RedirectResponse('/resources?error=busy', 303)
    row = ResourceBooking(resource_id=resource.id, user_id=u.id, title=title.strip()[:220], start_at=start, end_at=end, notes=notes.strip())
    db.add(row); db.commit(); db.refresh(row)
    audit(db, request, u, 'resource.book', entity_type='resource_booking', entity_id=row.id, details=resource.name)
    return RedirectResponse('/resources', 303)


@router.post('/resources/bookings/{booking_id}/cancel')
def resource_booking_cancel(booking_id: int, request: Request, db: Session = Depends(get_db)):
    u = _user(request, db)
    if not u:
        return RedirectResponse('/login', 303)
    row = db.get(ResourceBooking, booking_id)
    if row and (row.user_id == u.id or has_permission(u, 'resource.manage')):
        row.status = 'cancelled'; db.commit()
        audit(db, request, u, 'resource.booking.cancel', entity_type='resource_booking', entity_id=row.id)
    return RedirectResponse('/resources', 303)


@router.get('/integration/zabbix', response_class=HTMLResponse)
def zabbix_page(request: Request, db: Session = Depends(get_db)):
    u = _user(request, db)
    if not u:
        return RedirectResponse('/login', 303)
    if not has_permission(u, 'integration.manage'):
        return forbidden(request, db, u, 'integration.manage')
    sites = db.query(Site).order_by(Site.name).all()
    count = db.query(Ticket).count()  # cheap DB health marker for the page
    return templates.TemplateResponse('zabbix.html', ctx(request, db, sites=sites, db_marker=count, sync_result=None))


@router.post('/integration/zabbix/sync', response_class=HTMLResponse)
def zabbix_sync_now(request: Request, site_id: str = Form(''), db: Session = Depends(get_db)):
    u = _user(request, db)
    if not u:
        return RedirectResponse('/login', 303)
    if not has_permission(u, 'integration.manage'):
        return forbidden(request, db, u, 'integration.manage')
    try:
        result = sync_zabbix(db, int(site_id) if site_id else None)
        audit(db, request, u, 'zabbix.sync', entity_type='integration', details=json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        db.rollback(); result = {'error': str(exc)}
    sites = db.query(Site).order_by(Site.name).all()
    return templates.TemplateResponse('zabbix.html', ctx(request, db, sites=sites, db_marker=0, sync_result=result))


@router.post('/profile/preferences')
def profile_preferences(request: Request, locale: str = Form('ru'), timezone_name: str = Form('Asia/Almaty', alias='timezone'), db: Session = Depends(get_db)):
    u = _user(request, db)
    if not u:
        return RedirectResponse('/login', 303)
    valid_locales = {x[0] for x in SUPPORTED_LOCALES}
    valid_zones = set(SUPPORTED_TIMEZONES)
    u.locale = locale if locale in valid_locales else 'ru'
    u.timezone = timezone_name if timezone_name in valid_zones else 'Asia/Almaty'
    db.commit(); audit(db, request, u, 'profile.preferences', entity_type='user', entity_id=u.id, details=f'locale={u.locale}; timezone={u.timezone}')
    return RedirectResponse('/profile', 303)
