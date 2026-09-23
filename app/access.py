from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Query

from app.models import Ticket, User, SupportGroupMember, TicketObserver

# Stable role codes used across UI, web routes and REST API.
ROLE_REQUESTER = "requester"
ROLE_TECHNICIAN = "technician"
ROLE_DISPATCHER = "dispatcher"
ROLE_MANAGER = "manager"
ROLE_ADMIN = "admin"

ALL_ROLES = {ROLE_REQUESTER, ROLE_TECHNICIAN, ROLE_DISPATCHER, ROLE_MANAGER, ROLE_ADMIN}

# Permission matrix is intentionally explicit.  UI hiding is only cosmetic;
# every protected web/API action must check these permissions server-side too.
ROLE_PERMISSIONS: dict[str, set[str]] = {
    ROLE_REQUESTER: {
        "dashboard.view",
        "ticket.list", "ticket.create", "ticket.comment",
        "site.lookup", "equipment.lookup",
        "profile.self", "knowledge.view", "service.view", "notifications.view", "feedback.create", "resource.view", "resource.book", "survey.respond", "subscription.self",
    },
    ROLE_TECHNICIAN: {
        "dashboard.view",
        "ticket.list", "ticket.create", "ticket.comment", "ticket.work_status", "ticket.master_comment",
        "ticket.time.track", "ticket.time.manual_self", "ticket.stock.issue", "ticket.materials.view",
        "site.view", "equipment.view", "equipment.lookup",
        "maintenance.view_assigned", "inventory.view",
        "kpi.self",
        "profile.self", "knowledge.view", "service.view", "notifications.view", "ticket.link", "approval.request", "resource.view", "resource.book", "survey.respond", "subscription.self",
    },
    ROLE_DISPATCHER: {
        "dashboard.view",
        "ticket.list_all", "ticket.list", "ticket.create", "ticket.comment",
        "ticket.assign", "ticket.dispatch_status", "ticket.set_priority",
        "ticket.contractor", "ticket.stock.issue", "ticket.materials.view",
        "site.view", "site.manage",
        "equipment.view", "equipment.manage", "equipment.lookup",
        "maintenance.view_all", "maintenance.manage",
        "inventory.view",
        "contractor.view", "contractor.manage",
        "profile.self", "knowledge.view", "service.view", "notifications.view", "ticket.link", "approval.request", "resource.view", "resource.book", "survey.respond", "subscription.self", "report.builder",
        "ticket.bulk", "ticket.observe", "ticket.template", "team.manage", "ticket.set_requester", "data.import", "resource.view", "resource.book", "resource.manage", "survey.manage", "subscription.self", "itsm.view", "cmdb.relation.manage",
    },
    ROLE_MANAGER: {
        "dashboard.view",
        "ticket.list_all", "ticket.list", "ticket.create", "ticket.comment",
        "ticket.assign", "ticket.dispatch_status", "ticket.set_priority",
        "ticket.contractor", "ticket.cost", "ticket.materials.view", "ticket.close", "ticket.cancel",
        "site.view", "equipment.view", "maintenance.view_all", "inventory.view",
        "contractor.view", "kpi.all", "audit.view",
        "profile.self", "knowledge.view", "service.view", "notifications.view", "ticket.link", "approval.request", "resource.view", "resource.book", "survey.respond", "subscription.self", "approval.decide", "report.builder",
        "ticket.bulk", "ticket.observe", "ticket.template", "team.manage", "ticket.set_requester",
        "labor.report", "labor.rate.manage", "resource.view", "resource.book", "resource.manage", "survey.manage", "subscription.self", "itsm.view", "sla.manage", "cmdb.relation.manage",
    },
    ROLE_ADMIN: {
        "*",
    },
}

# Technician has a deliberately narrow state machine.  Dispatcher controls
# assignment and operational routing.  Manager controls final close/reopen.
TECHNICIAN_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "assigned": {"in_progress"},
    "in_progress": {"waiting", "resolved"},
    "waiting": {"in_progress", "resolved"},
}

DISPATCHER_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "new": {"assigned", "cancelled"},
    "assigned": {"new", "in_progress", "waiting", "cancelled"},
    "in_progress": {"waiting", "resolved", "cancelled"},
    "waiting": {"assigned", "in_progress", "resolved", "cancelled"},
    "resolved": {"assigned", "in_progress"},
}

MANAGER_STATUS_TRANSITIONS: dict[str, set[str]] = {
    **DISPATCHER_STATUS_TRANSITIONS,
    "resolved": {"closed", "assigned", "in_progress"},
    "closed": {"assigned", "in_progress"},
    "cancelled": {"new", "assigned"},
}


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    reason: str = ""


def has_permission(user: User | None, permission: str) -> bool:
    if user is None or not user.active:
        return False
    perms = ROLE_PERMISSIONS.get(user.role, set())
    return "*" in perms or permission in perms


def require_permission(user: User | None, permission: str, detail: str = "Недостаточно прав") -> User:
    if not has_permission(user, permission):
        raise HTTPException(status_code=403, detail=detail)
    return user  # type: ignore[return-value]


def scope_ticket_query(query: Query, user: User) -> Query:
    """Apply row-level security, including group assignments and observers."""
    if has_permission(user, "ticket.list_all"):
        return query
    observed = select(TicketObserver.ticket_id).where(TicketObserver.user_id == user.id)
    if user.role == ROLE_REQUESTER:
        return query.filter(or_(Ticket.requester_id == user.id, Ticket.creator_id == user.id, Ticket.id.in_(observed)))
    if user.role == ROLE_TECHNICIAN:
        groups = select(SupportGroupMember.group_id).where(SupportGroupMember.user_id == user.id)
        return query.filter(or_(Ticket.assignee_id == user.id, Ticket.group_id.in_(groups), Ticket.id.in_(observed)))
    return query.filter(Ticket.id.in_(observed))


def can_view_ticket(user: User | None, ticket: Ticket | None, db=None) -> bool:
    if user is None or ticket is None or not user.active:
        return False
    if has_permission(user, "ticket.list_all"):
        return True
    if user.role == ROLE_REQUESTER and (ticket.requester_id == user.id or ticket.creator_id == user.id):
        return True
    if user.role == ROLE_TECHNICIAN and ticket.assignee_id == user.id:
        return True
    if db is not None:
        if ticket.group_id and db.query(SupportGroupMember.id).filter(SupportGroupMember.group_id == ticket.group_id, SupportGroupMember.user_id == user.id).first():
            return True
        if db.query(TicketObserver.id).filter(TicketObserver.ticket_id == ticket.id, TicketObserver.user_id == user.id).first():
            return True
    return False


def can_comment_ticket(user: User | None, ticket: Ticket | None, db=None) -> bool:
    return bool(user and has_permission(user, "ticket.comment") and can_view_ticket(user, ticket, db))


def can_issue_stock(user: User | None, ticket: Ticket | None, db=None) -> bool:
    if not user or not ticket or not has_permission(user, "ticket.stock.issue"):
        return False
    if user.role == ROLE_TECHNICIAN:
        return ticket.assignee_id == user.id and ticket.status not in {"resolved", "closed", "cancelled"}
    return can_view_ticket(user, ticket, db)


def can_track_ticket_time(user: User | None, ticket: Ticket | None) -> bool:
    if not user or not ticket or not has_permission(user, "ticket.time.track"):
        return False
    return user.role == ROLE_TECHNICIAN and ticket.assignee_id == user.id and ticket.status not in {"resolved", "closed", "cancelled"}


def allowed_statuses(user: User | None, ticket: Ticket) -> set[str]:
    if user is None or not user.active:
        return {ticket.status}
    if user.role == ROLE_ADMIN:
        return {"new", "assigned", "in_progress", "waiting", "resolved", "closed", "cancelled"}
    if user.role == ROLE_MANAGER:
        return {ticket.status} | MANAGER_STATUS_TRANSITIONS.get(ticket.status, set())
    if user.role == ROLE_DISPATCHER:
        return {ticket.status} | DISPATCHER_STATUS_TRANSITIONS.get(ticket.status, set())
    if user.role == ROLE_TECHNICIAN and ticket.assignee_id == user.id:
        return {ticket.status} | TECHNICIAN_STATUS_TRANSITIONS.get(ticket.status, set())
    return {ticket.status}


def can_change_ticket_status(user: User | None, ticket: Ticket, new_status: str) -> AccessDecision:
    if new_status == ticket.status:
        return AccessDecision(True)
    allowed = allowed_statuses(user, ticket)
    if new_status not in allowed:
        return AccessDecision(False, "Переход статуса запрещён для вашей роли")
    if user and user.role == ROLE_TECHNICIAN and ticket.assignee_id != user.id:
        return AccessDecision(False, "Техник может менять статус только своей назначенной заявки")
    return AccessDecision(True)


def visible_navigation(user: User | None) -> dict[str, bool]:
    """Convenience flags for templates. Security still lives server-side."""
    return {
        "sites": bool(user and has_permission(user, "site.view")),
        "equipment": bool(user and has_permission(user, "equipment.view")),
        "maintenance": bool(user and (has_permission(user, "maintenance.view_all") or has_permission(user, "maintenance.view_assigned"))),
        "inventory": bool(user and has_permission(user, "inventory.view")),
        "contractors": bool(user and has_permission(user, "contractor.view")),
        "kpi": bool(user and (has_permission(user, "kpi.all") or has_permission(user, "kpi.self"))),
        "integration": bool(user and has_permission(user, "integration.manage")),
        "users": bool(user and has_permission(user, "users.manage")),
        "settings": bool(user and has_permission(user, "settings.manage")),
        "audit": bool(user and has_permission(user, "audit.view")),
        "knowledge": bool(user and has_permission(user, "knowledge.view")),
        "services": bool(user and has_permission(user, "service.view")),
        "notifications": bool(user and has_permission(user, "notifications.view")),
        "reports": bool(user and has_permission(user, "report.builder")),
        "automation": bool(user and has_permission(user, "automation.manage")),
        "teams": bool(user and (has_permission(user, "team.manage") or has_permission(user, "ticket.list_all"))),
        "templates": bool(user and has_permission(user, "ticket.template")),
        "system_services": bool(user and has_permission(user, "integration.manage")),
        "data_import": bool(user and has_permission(user, "data.import")),
        "categories": bool(user and has_permission(user, "settings.manage")),
        "labor": bool(user and has_permission(user, "labor.report")),
        "resources": bool(user and has_permission(user, "resource.view")),
        "surveys": bool(user and (has_permission(user, "survey.manage") or has_permission(user, "survey.respond"))),
        "subscriptions": bool(user and has_permission(user, "subscription.self")),
        "itsm": bool(user and has_permission(user, "itsm.view")),
        "sla_calendars": bool(user and has_permission(user, "sla.manage")),
    }


def role_summary(role: str) -> str:
    return {
        ROLE_REQUESTER: "Создаёт заявки и видит только свои заявки.",
        ROLE_TECHNICIAN: "Работает только с назначенными ему заявками, временем и материалами.",
        ROLE_DISPATCHER: "Распределяет заявки, назначает исполнителей и управляет оперативной работой.",
        ROLE_MANAGER: "Контролирует все заявки и KPI, закрывает/возобновляет работы и видит аудит.",
        ROLE_ADMIN: "Полный доступ, пользователи, настройки, интеграции и справочники.",
    }.get(role, "Неизвестная роль")
