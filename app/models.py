from __future__ import annotations
import uuid
from datetime import datetime, date
from decimal import Decimal
from sqlalchemy import String, Text, DateTime, Date, ForeignKey, Numeric, Integer, Boolean, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db import Base

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(160))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(30), default="requester")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    email: Mapped[str] = mapped_column(String(160), default="")
    phone: Mapped[str] = mapped_column(String(80), default="")
    telegram_chat_id: Mapped[str] = mapped_column(String(80), default="")
    totp_secret: Mapped[str] = mapped_column(String(64), default="")
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True, index=True)
    manager_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    external_dn: Mapped[str] = mapped_column(String(500), default="", index=True)
    directory_source: Mapped[str] = mapped_column(String(30), default="local")
    hourly_rate: Mapped[Decimal] = mapped_column(Numeric(12,2), default=0)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Almaty")
    locale: Mapped[str] = mapped_column(String(10), default="ru")

class Site(Base):
    __tablename__ = "sites"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(180), unique=True)
    address: Mapped[str] = mapped_column(String(255), default="")
    one_c_id: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    equipment: Mapped[list[Equipment]] = relationship(back_populates="site")

class Equipment(Base):
    __tablename__ = "equipment"
    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    inventory_no: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    category: Mapped[str] = mapped_column(String(100), default="Прочее")
    model: Mapped[str] = mapped_column(String(120), default="")
    serial_no: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(30), default="working")
    installed_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    warranty_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_maintenance_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    one_c_id: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    qr_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("equipment.id"), nullable=True, index=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    criticality: Mapped[str] = mapped_column(String(20), default="normal")
    external_source: Mapped[str] = mapped_column(String(30), default="")
    external_key: Mapped[str] = mapped_column(String(120), default="", index=True)
    site: Mapped[Site] = relationship(back_populates="equipment")
    tickets: Mapped[list[Ticket]] = relationship(back_populates="equipment")

class Ticket(Base):
    __tablename__ = "tickets"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(220))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(100), default="Ремонт")
    priority: Mapped[str] = mapped_column(String(20), default="normal")
    status: Mapped[str] = mapped_column(String(30), default="new")
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), index=True)
    equipment_id: Mapped[int | None] = mapped_column(ForeignKey("equipment.id"), nullable=True, index=True)
    requester_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    contractor_id: Mapped[int | None] = mapped_column(ForeignKey("contractors.id"), nullable=True)
    service_id: Mapped[int | None] = mapped_column(ForeignKey("service_catalog.id"), nullable=True, index=True)
    creator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("support_groups.id"), nullable=True, index=True)
    template_id: Mapped[int | None] = mapped_column(ForeignKey("ticket_templates.id"), nullable=True, index=True)
    sla_paused_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sla_paused_seconds: Mapped[int] = mapped_column(Integer, default=0)
    edit_version: Mapped[int] = mapped_column(Integer, default=1)
    ticket_type: Mapped[str] = mapped_column(String(30), default="incident", index=True)
    planned_start_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    planned_end_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    response_due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    first_response_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    business_calendar_id: Mapped[int | None] = mapped_column(ForeignKey("business_calendars.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    sla_due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    labor_cost: Mapped[Decimal] = mapped_column(Numeric(12,2), default=0)
    manual_labor_cost: Mapped[Decimal] = mapped_column(Numeric(12,2), default=0)
    parts_cost: Mapped[Decimal] = mapped_column(Numeric(12,2), default=0)
    one_c_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    web_uid: Mapped[str | None] = mapped_column(String(36), default=lambda: str(uuid.uuid4()), unique=True, nullable=True, index=True)
    # Compatibility with the existing 1C document ЗаявкаХозОтдела
    requester_name: Mapped[str] = mapped_column(String(180), default="")
    requester_phone: Mapped[str] = mapped_column(String(80), default="")
    room: Mapped[str] = mapped_column(String(80), default="")
    master_name: Mapped[str] = mapped_column(String(180), default="")
    master_comment: Mapped[str] = mapped_column(Text, default="")
    onec_sync_error: Mapped[str] = mapped_column(Text, default="")
    onec_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    site: Mapped[Site] = relationship()
    equipment: Mapped[Equipment | None] = relationship(back_populates="tickets")
    requester: Mapped[User | None] = relationship(foreign_keys=[requester_id])
    creator: Mapped[User | None] = relationship(foreign_keys=[creator_id])
    assignee: Mapped[User | None] = relationship(foreign_keys=[assignee_id])
    group: Mapped[SupportGroup | None] = relationship(foreign_keys=[group_id])
    template: Mapped[TicketTemplate | None] = relationship(foreign_keys=[template_id])
    business_calendar: Mapped[BusinessCalendar | None] = relationship(foreign_keys=[business_calendar_id])
    contractor: Mapped[Contractor | None] = relationship()
    comments: Mapped[list[TicketComment]] = relationship(back_populates="ticket", cascade="all, delete-orphan")
    attachments: Mapped[list[Attachment]] = relationship(back_populates="ticket", cascade="all, delete-orphan")
    work_sessions: Mapped[list[TicketWorkSession]] = relationship(back_populates="ticket", cascade="all, delete-orphan")

class TicketComment(Base):
    __tablename__ = "ticket_comments"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ticket: Mapped[Ticket] = relationship(back_populates="comments")
    user: Mapped[User | None] = relationship()
    attachments: Mapped[list[Attachment]] = relationship(back_populates="comment")

class Attachment(Base):
    __tablename__ = "attachments"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    comment_id: Mapped[int | None] = mapped_column(ForeignKey("ticket_comments.id"), nullable=True, index=True)
    filename: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(255))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ticket: Mapped[Ticket] = relationship(back_populates="attachments")
    comment: Mapped[TicketComment | None] = relationship(back_populates="attachments")

class TicketWorkSession(Base):
    __tablename__ = "ticket_work_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str] = mapped_column(String(255), default="")
    source: Mapped[str] = mapped_column(String(20), default="timer")
    hourly_rate_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(12,2), nullable=True)
    labor_amount: Mapped[Decimal | None] = mapped_column(Numeric(12,2), nullable=True)
    ticket: Mapped[Ticket] = relationship(back_populates="work_sessions")
    user: Mapped[User] = relationship()

class MaintenancePlan(Base):
    __tablename__ = "maintenance_plans"
    id: Mapped[int] = mapped_column(primary_key=True)
    equipment_id: Mapped[int] = mapped_column(ForeignKey("equipment.id"), index=True)
    name: Mapped[str] = mapped_column(String(180))
    interval_days: Mapped[int] = mapped_column(Integer, default=30)
    checklist: Mapped[str] = mapped_column(Text, default="[]")
    last_run: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_run: Mapped[date] = mapped_column(Date)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    equipment: Mapped[Equipment] = relationship()
    assignee: Mapped[User | None] = relationship()

class InventoryItem(Base):
    __tablename__ = "inventory_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    qty: Mapped[float] = mapped_column(Float, default=0)
    min_qty: Mapped[float] = mapped_column(Float, default=0)
    unit: Mapped[str] = mapped_column(String(30), default="шт")
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(12,2), default=0)
    one_c_id: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)

class StockMovement(Base):
    __tablename__ = "stock_movements"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id"), index=True)
    ticket_id: Mapped[int | None] = mapped_column(ForeignKey("tickets.id"), nullable=True)
    movement_type: Mapped[str] = mapped_column(String(20))
    qty: Mapped[float] = mapped_column(Float)
    # Price snapshots are stored on the movement itself so the historical
    # value of materials used in a ticket does not change when the warehouse
    # catalogue price is edited later.
    unit_cost_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(12,2), nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12,2), nullable=True)
    issued_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    comment: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    item: Mapped[InventoryItem] = relationship()
    ticket: Mapped[Ticket | None] = relationship()
    issued_by: Mapped[User | None] = relationship()

class Contractor(Base):
    __tablename__ = "contractors"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    phone: Mapped[str] = mapped_column(String(80), default="")
    email: Mapped[str] = mapped_column(String(120), default="")
    specialization: Mapped[str] = mapped_column(String(180), default="")
    rating: Mapped[float] = mapped_column(Float, default=5.0)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str] = mapped_column(String(60), default="")
    entity_id: Mapped[str] = mapped_column(String(80), default="")
    result: Mapped[str] = mapped_column(String(20), default="allowed", index=True)
    details: Mapped[str] = mapped_column(Text, default="")
    ip_address: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    user: Mapped[User | None] = relationship()

class UiStyle(Base):
    """Local reference data and presentation rules owned by the standalone TOIR core.

    kind: status | priority | category | equipment_status
    code: stable internal code; categories may use their human-readable name as a code.
    """
    __tablename__ = "ui_styles"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(30), index=True)
    code: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(160), default="")
    bg_color: Mapped[str] = mapped_column(String(20), default="")
    text_color: Mapped[str] = mapped_column(String(20), default="")
    border_color: Mapped[str] = mapped_column(String(20), default="")
    sla_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=100)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)



# ---- CMDB taxonomy / analytics extension v0.7.3 ----
class CategoryNode(Base):
    __tablename__ = "category_nodes"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(30), default="ticket", index=True)
    name: Mapped[str] = mapped_column(String(180), index=True)
    code: Mapped[str] = mapped_column(String(180), default="", index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("category_nodes.id"), nullable=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=100)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ---- Enterprise ServiceDesk extension v0.6 ----
class ServiceCatalog(Base):
    __tablename__ = "service_catalog"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(180), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(100), default="Другое")
    default_priority: Mapped[str] = mapped_column(String(20), default="normal")
    default_sla_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_sla_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resolution_sla_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    business_calendar_id: Mapped[int | None] = mapped_column(ForeignKey("business_calendars.id"), nullable=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    business_calendar: Mapped[BusinessCalendar | None] = relationship()

class CustomField(Base):
    __tablename__ = "custom_fields"
    id: Mapped[int] = mapped_column(primary_key=True)
    service_id: Mapped[int | None] = mapped_column(ForeignKey("service_catalog.id"), nullable=True, index=True)
    code: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(180))
    field_type: Mapped[str] = mapped_column(String(30), default="text")
    options_json: Mapped[str] = mapped_column(Text, default="[]")
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=100)
    service: Mapped[ServiceCatalog | None] = relationship()

class TicketCustomValue(Base):
    __tablename__ = "ticket_custom_values"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    field_id: Mapped[int] = mapped_column(ForeignKey("custom_fields.id"), index=True)
    value: Mapped[str] = mapped_column(Text, default="")
    field: Mapped[CustomField] = relationship()

class KnowledgeArticle(Base):
    __tablename__ = "knowledge_articles"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(240), index=True)
    body: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[str] = mapped_column(String(300), default="")
    equipment_category: Mapped[str] = mapped_column(String(100), default="")
    service_id: Mapped[int | None] = mapped_column(ForeignKey("service_catalog.id"), nullable=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    service: Mapped[ServiceCatalog | None] = relationship()
    created_by: Mapped[User | None] = relationship()

class AutomationRule(Base):
    __tablename__ = "automation_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(180))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=100)
    conditions_json: Mapped[str] = mapped_column(Text, default="{}")
    actions_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(220))
    body: Mapped[str] = mapped_column(Text, default="")
    level: Mapped[str] = mapped_column(String(20), default="info")
    link: Mapped[str] = mapped_column(String(300), default="")
    dedup_key: Mapped[str | None] = mapped_column(String(180), unique=True, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    user: Mapped[User] = relationship()

class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    endpoint: Mapped[str] = mapped_column(Text)
    p256dh: Mapped[str] = mapped_column(Text, default="")
    auth: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    user: Mapped[User] = relationship()

class TicketLink(Base):
    __tablename__ = "ticket_links"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    linked_ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    link_type: Mapped[str] = mapped_column(String(30), default="related")
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    linked_ticket: Mapped[Ticket] = relationship(foreign_keys=[linked_ticket_id])
    created_by: Mapped[User | None] = relationship()

class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    requested_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approver_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    requested_by: Mapped[User | None] = relationship(foreign_keys=[requested_by_id])
    approver: Mapped[User | None] = relationship(foreign_keys=[approver_id])

class TicketFeedback(Base):
    __tablename__ = "ticket_feedback"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    user: Mapped[User | None] = relationship()

class SavedFilter(Base):
    __tablename__ = "saved_filters"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    filters_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    user: Mapped[User] = relationship()

class ReportSubscription(Base):
    __tablename__ = "report_subscriptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    periodicity: Mapped[str] = mapped_column(String(20), default="monthly")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    user: Mapped[User] = relationship()

class SlaEvent(Base):
    __tablename__ = "sla_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(30), index=True)
    event_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class TechnicianAvailability(Base):
    __tablename__ = "technician_availability"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    weekday: Mapped[int] = mapped_column(Integer)
    start_time: Mapped[str] = mapped_column(String(5), default="09:00")
    end_time: Mapped[str] = mapped_column(String(5), default="18:00")
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    user: Mapped[User] = relationship()


# ---- ServiceDesk operations extension v0.7 (phase 1) ----
class SupportGroup(Base):
    __tablename__ = "support_groups"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class SupportGroupMember(Base):
    __tablename__ = "support_group_members"
    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("support_groups.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    member_role: Mapped[str] = mapped_column(String(30), default="executor")
    user: Mapped[User] = relationship()
    group: Mapped[SupportGroup] = relationship()

class TicketObserver(Base):
    __tablename__ = "ticket_observers"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    user: Mapped[User] = relationship(foreign_keys=[user_id])
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])

class TicketTemplate(Base):
    __tablename__ = "ticket_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    title_template: Mapped[str] = mapped_column(String(220), default="")
    description_template: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(100), default="Другое")
    priority: Mapped[str] = mapped_column(String(20), default="normal")
    service_id: Mapped[int | None] = mapped_column(ForeignKey("service_catalog.id"), nullable=True)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("support_groups.id"), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    service: Mapped[ServiceCatalog | None] = relationship()
    group: Mapped[SupportGroup | None] = relationship()

class TicketTemplateTask(Base):
    __tablename__ = "ticket_template_tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("ticket_templates.id"), index=True)
    title: Mapped[str] = mapped_column(String(220))
    description: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=100)
    template: Mapped[TicketTemplate] = relationship()


# ---- ServiceDesk lifecycle extension v0.7.1 ----
class TicketStatusHistory(Base):
    __tablename__ = "ticket_status_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    from_status: Mapped[str] = mapped_column(String(30), default="")
    to_status: Mapped[str] = mapped_column(String(30), index=True)
    changed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    previous_duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(30), default="web")
    changed_by: Mapped[User | None] = relationship()

class TicketReminder(Base):
    __tablename__ = "ticket_reminders"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    remind_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    note: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    user: Mapped[User] = relationship()
    ticket: Mapped[Ticket] = relationship()


# ---- Integration / directory extension v0.7.2 ----
class Department(Base):
    __tablename__ = "departments"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    external_key: Mapped[str] = mapped_column(String(500), default="", index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class EmailRule(Base):
    __tablename__ = "email_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(180), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sender_contains: Mapped[str] = mapped_column(String(180), default="")
    subject_contains: Mapped[str] = mapped_column(String(180), default="")
    recipient_contains: Mapped[str] = mapped_column(String(180), default="")
    category: Mapped[str] = mapped_column(String(100), default="")
    priority: Mapped[str] = mapped_column(String(20), default="")
    group_id: Mapped[int | None] = mapped_column(ForeignKey("support_groups.id"), nullable=True, index=True)
    add_recipients_as_observers: Mapped[bool] = mapped_column(Boolean, default=True)
    active_days: Mapped[str] = mapped_column(String(30), default="0,1,2,3,4,5,6")
    time_from: Mapped[str] = mapped_column(String(5), default="00:00")
    time_to: Mapped[str] = mapped_column(String(5), default="23:59")
    sort_order: Mapped[int] = mapped_column(Integer, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    group: Mapped[SupportGroup | None] = relationship()

class BackgroundServiceLog(Base):
    __tablename__ = "background_service_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    service: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(20), default="ok", index=True)
    message: Mapped[str] = mapped_column(String(500), default="")
    details: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)

# ---- Experience / subscriptions / resources / Zabbix extension v0.7.4 ----
class FilterSubscription(Base):
    __tablename__ = "filter_subscriptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    saved_filter_id: Mapped[int] = mapped_column(ForeignKey("saved_filters.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    periodicity: Mapped[str] = mapped_column(String(20), default="daily")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    user: Mapped[User] = relationship()
    saved_filter: Mapped[SavedFilter] = relationship()

class SurveyTemplate(Base):
    __tablename__ = "survey_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    service_id: Mapped[int | None] = mapped_column(ForeignKey("service_catalog.id"), nullable=True, index=True)
    questions_json: Mapped[str] = mapped_column(Text, default="[]")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    service: Mapped[ServiceCatalog | None] = relationship()

class SurveyResponse(Base):
    __tablename__ = "survey_responses"
    id: Mapped[int] = mapped_column(primary_key=True)
    survey_id: Mapped[int] = mapped_column(ForeignKey("survey_templates.id"), index=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    answers_json: Mapped[str] = mapped_column(Text, default="{}")
    score: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    survey: Mapped[SurveyTemplate] = relationship()
    ticket: Mapped[Ticket] = relationship()
    user: Mapped[User | None] = relationship()

class Resource(Base):
    __tablename__ = "resources"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    resource_type: Mapped[str] = mapped_column(String(80), default="resource", index=True)
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id"), nullable=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    capacity: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    site: Mapped[Site | None] = relationship()

class ResourceBooking(Base):
    __tablename__ = "resource_bookings"
    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(220))
    start_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    end_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    resource: Mapped[Resource] = relationship()
    user: Mapped[User] = relationship()


# ---- Advanced ITSM / SLA / CMDB / Webhooks extension v0.7.5 ----
class BusinessCalendar(Base):
    __tablename__ = "business_calendars"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Almaty")
    weekdays: Mapped[str] = mapped_column(String(30), default="0,1,2,3,4")
    work_start: Mapped[str] = mapped_column(String(5), default="09:00")
    work_end: Mapped[str] = mapped_column(String(5), default="18:00")
    holidays_json: Mapped[str] = mapped_column(Text, default="[]")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class EquipmentRelation(Base):
    __tablename__ = "equipment_relations"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_equipment_id: Mapped[int] = mapped_column(ForeignKey("equipment.id"), index=True)
    target_equipment_id: Mapped[int] = mapped_column(ForeignKey("equipment.id"), index=True)
    relation_type: Mapped[str] = mapped_column(String(40), default="depends_on", index=True)
    note: Mapped[str] = mapped_column(String(300), default="")
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    source: Mapped[Equipment] = relationship(foreign_keys=[source_equipment_id])
    target: Mapped[Equipment] = relationship(foreign_keys=[target_equipment_id])
    created_by: Mapped[User | None] = relationship()

class WebhookEndpoint(Base):
    __tablename__ = "webhook_endpoints"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    url: Mapped[str] = mapped_column(String(500))
    secret: Mapped[str] = mapped_column(String(180), default="")
    events: Mapped[str] = mapped_column(String(500), default="ticket.created,ticket.updated,ticket.comment")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"
    id: Mapped[int] = mapped_column(primary_key=True)
    endpoint_id: Mapped[int] = mapped_column(ForeignKey("webhook_endpoints.id"), index=True)
    event_name: Mapped[str] = mapped_column(String(80), index=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str] = mapped_column(Text, default="")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    endpoint: Mapped[WebhookEndpoint] = relationship()
