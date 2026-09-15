from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from sqlalchemy.orm import Session

from app.models import Ticket, User

COMPLETED_STATUSES = {"resolved", "closed"}
CANCELLED_STATUSES = {"cancelled"}
PRIORITY_POINTS = {
    "low": 0.75,
    "normal": 1.0,
    "high": 1.5,
    "critical": 2.0,
}


@dataclass(frozen=True)
class KpiPeriod:
    value: str
    year: int
    month: int
    start: datetime
    end: datetime
    label: str


MONTHS_RU = (
    "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
)


def parse_period(value: str | None, now: datetime | None = None) -> KpiPeriod:
    now = now or datetime.now()
    try:
        year_s, month_s = (value or "").split("-", 1)
        year, month = int(year_s), int(month_s)
        if not 1 <= month <= 12:
            raise ValueError
    except Exception:
        year, month = now.year, now.month

    start = datetime(year, month, 1)
    if month == 12:
        end = datetime(year + 1, 1, 1)
    else:
        end = datetime(year, month + 1, 1)
    return KpiPeriod(
        value=f"{year:04d}-{month:02d}",
        year=year,
        month=month,
        start=start,
        end=end,
        label=f"{MONTHS_RU[month - 1]} {year}",
    )


def shift_month(period: KpiPeriod, delta: int) -> str:
    absolute = period.year * 12 + (period.month - 1) + delta
    year, zero_month = divmod(absolute, 12)
    return f"{year:04d}-{zero_month + 1:02d}"


def _percent(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return round(min(100.0, max(0.0, numerator / denominator * 100.0)), 1)


def _hours(delta_seconds: float) -> float:
    return round(max(0.0, delta_seconds) / 3600.0, 1)


def calculate_monthly_kpi(
    db: Session,
    period: KpiPeriod,
    *,
    target_points: float = 30.0,
    weight_sla: float = 0.40,
    weight_closure: float = 0.25,
    weight_productivity: float = 0.20,
    weight_documentation: float = 0.15,
    technician_ids: Iterable[int] | None = None,
) -> dict:
    technicians_query = db.query(User).filter(User.active.is_(True), User.role == "technician")
    if technician_ids is not None:
        ids = list(technician_ids)
        if not ids:
            technicians = []
        else:
            technicians = technicians_query.filter(User.id.in_(ids)).order_by(User.full_name).all()
    else:
        technicians = technicians_query.order_by(User.full_name).all()

    raw_weights = [weight_sla, weight_closure, weight_productivity, weight_documentation]
    total_weight = sum(max(0.0, float(x)) for x in raw_weights) or 1.0
    weights = {
        "sla": max(0.0, float(weight_sla)) / total_weight,
        "closure": max(0.0, float(weight_closure)) / total_weight,
        "productivity": max(0.0, float(weight_productivity)) / total_weight,
        "documentation": max(0.0, float(weight_documentation)) / total_weight,
    }
    target_points = max(0.1, float(target_points or 30.0))

    rows: list[dict] = []
    for technician in technicians:
        # Tickets that overlapped the selected month for the current assignee.
        handled = (
            db.query(Ticket)
            .filter(
                Ticket.assignee_id == technician.id,
                Ticket.created_at < period.end,
                (Ticket.resolved_at.is_(None)) | (Ticket.resolved_at >= period.start),
                ~Ticket.status.in_(CANCELLED_STATUSES),
            )
            .all()
        )
        completed = (
            db.query(Ticket)
            .filter(
                Ticket.assignee_id == technician.id,
                Ticket.resolved_at.is_not(None),
                Ticket.resolved_at >= period.start,
                Ticket.resolved_at < period.end,
            )
            .all()
        )

        completed_count = len(completed)
        handled_count = len(handled)
        sla_tickets = [t for t in completed if t.sla_due_at is not None]
        on_time = [t for t in sla_tickets if t.resolved_at and t.resolved_at <= t.sla_due_at]
        overdue_completed = len(sla_tickets) - len(on_time)
        documented = [t for t in completed if (t.master_comment or "").strip()]
        points = round(sum(PRIORITY_POINTS.get(t.priority, 1.0) for t in completed), 2)

        sla_rate = _percent(len(on_time), len(sla_tickets)) if completed_count else 0.0
        closure_rate = _percent(completed_count, handled_count) if handled_count else 0.0
        productivity_rate = round(min(100.0, points / target_points * 100.0), 1) if completed_count else 0.0
        documentation_rate = _percent(len(documented), completed_count) if completed_count else 0.0

        score = round(
            sla_rate * weights["sla"]
            + closure_rate * weights["closure"]
            + productivity_rate * weights["productivity"]
            + documentation_rate * weights["documentation"],
            1,
        )
        rating = round(score / 20.0, 1)

        durations = [
            (t.resolved_at - t.created_at).total_seconds()
            for t in completed
            if t.resolved_at and t.created_at
        ]
        avg_resolution_hours = _hours(sum(durations) / len(durations)) if durations else 0.0

        open_backlog = (
            db.query(Ticket)
            .filter(
                Ticket.assignee_id == technician.id,
                Ticket.status.notin_(list(COMPLETED_STATUSES | CANCELLED_STATUSES)),
                Ticket.created_at < period.end,
            )
            .count()
        )
        overdue_open = (
            db.query(Ticket)
            .filter(
                Ticket.assignee_id == technician.id,
                Ticket.status.notin_(list(COMPLETED_STATUSES | CANCELLED_STATUSES)),
                Ticket.sla_due_at.is_not(None),
                Ticket.sla_due_at < datetime.utcnow(),
            )
            .count()
        )

        rows.append(
            {
                "user_id": technician.id,
                "name": technician.full_name,
                "username": technician.username,
                "handled": handled_count,
                "completed": completed_count,
                "points": points,
                "sla_rate": sla_rate,
                "sla_total": len(sla_tickets),
                "sla_ontime": len(on_time),
                "closure_rate": closure_rate,
                "productivity_rate": productivity_rate,
                "documentation_rate": documentation_rate,
                "overdue_completed": overdue_completed,
                "avg_resolution_hours": avg_resolution_hours,
                "open_backlog": open_backlog,
                "overdue_open": overdue_open,
                "score": score,
                "rating": rating,
                "has_activity": bool(handled_count or completed_count),
            }
        )

    rows.sort(key=lambda x: (not x["has_activity"], -x["score"], -x["points"], x["name"].lower()))
    rank = 0
    for row in rows:
        if row["has_activity"]:
            rank += 1
            row["rank"] = rank
        else:
            row["rank"] = None

    active_rows = [r for r in rows if r["has_activity"]]
    total_completed = sum(r["completed"] for r in rows)
    total_sla_ontime = sum(r["sla_ontime"] for r in rows)
    total_sla_tickets = sum(r["sla_total"] for r in rows)
    team_sla = _percent(total_sla_ontime, total_sla_tickets) if total_sla_tickets else 0.0
    avg_kpi = round(sum(r["score"] for r in active_rows) / len(active_rows), 1) if active_rows else 0.0

    return {
        "period": period,
        "rows": rows,
        "weights": weights,
        "target_points": target_points,
        "avg_kpi": avg_kpi,
        "team_sla": team_sla,
        "total_completed": total_completed,
        "total_points": round(sum(r["points"] for r in rows), 2),
        "leader": active_rows[0] if active_rows else None,
        "technicians_count": len(technicians),
        "active_technicians_count": len(active_rows),
    }
