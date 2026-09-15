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

class Attachment(Base):
    __tablename__ = "attachments"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(255))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ticket: Mapped[Ticket] = relationship(back_populates="attachments")

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
    comment: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    item: Mapped[InventoryItem] = relationship()
    ticket: Mapped[Ticket | None] = relationship()

class Contractor(Base):
    __tablename__ = "contractors"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    phone: Mapped[str] = mapped_column(String(80), default="")
    email: Mapped[str] = mapped_column(String(120), default="")
    specialization: Mapped[str] = mapped_column(String(180), default="")
    rating: Mapped[float] = mapped_column(Float, default=5.0)

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
