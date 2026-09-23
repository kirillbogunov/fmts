from __future__ import annotations
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.models import User, Ticket, SupportGroup, SupportGroupMember, TicketObserver

OPEN_STATUSES = {"new", "assigned", "in_progress", "waiting"}


def group_members(db: Session, group_id: int, member_role: str | None = None) -> list[User]:
    q = db.query(User).join(SupportGroupMember, SupportGroupMember.user_id == User.id).filter(
        SupportGroupMember.group_id == group_id,
        User.active == True,
    )
    if member_role:
        q = q.filter(SupportGroupMember.member_role == member_role)
    return q.order_by(User.full_name).all()


def pick_group_assignee(db: Session, group_id: int) -> User | None:
    """Pick the least loaded active technician from the group's executor members."""
    candidates = (
        db.query(User)
        .join(SupportGroupMember, SupportGroupMember.user_id == User.id)
        .filter(
            SupportGroupMember.group_id == group_id,
            SupportGroupMember.member_role == "executor",
            User.active == True,
            User.role == "technician",
        )
        .all()
    )
    if not candidates:
        return None
    ids = [u.id for u in candidates]
    counts = dict(
        db.query(Ticket.assignee_id, func.count(Ticket.id))
        .filter(Ticket.assignee_id.in_(ids), Ticket.status.in_(OPEN_STATUSES))
        .group_by(Ticket.assignee_id)
        .all()
    )
    candidates.sort(key=lambda u: (int(counts.get(u.id, 0)), (u.full_name or u.username).lower(), u.id))
    return candidates[0]


def sync_group_observers(db: Session, ticket: Ticket) -> int:
    """Add group members marked as observers to the ticket without duplicating rows."""
    if not ticket.group_id:
        return 0
    observer_ids = [
        row.user_id for row in db.query(SupportGroupMember).filter(
            SupportGroupMember.group_id == ticket.group_id,
            SupportGroupMember.member_role == "observer",
        ).all()
    ]
    created = 0
    for user_id in observer_ids:
        if user_id in {ticket.requester_id, ticket.assignee_id}:
            continue
        exists = db.query(TicketObserver.id).filter(
            TicketObserver.ticket_id == ticket.id,
            TicketObserver.user_id == user_id,
        ).first()
        if not exists:
            db.add(TicketObserver(ticket_id=ticket.id, user_id=user_id))
            created += 1
    return created
