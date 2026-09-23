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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    sla_due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    labor_cost: Mapped[Decimal] = mapped_column(Numeric(12,2), default=0)
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
    assignee: Mapped[User | None] = relationship(foreign_keys=[assignee_id])
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
    active: Mapped[bool] = mapped_column(Boolean, default=True)

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
