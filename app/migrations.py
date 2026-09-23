from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

# Small additive migrations without Alembic. They are deliberately limited to
# nullable/additive fields so existing SQLite/PostgreSQL installations can be
# upgraded automatically at application start.

def _columns(engine: Engine, table: str) -> set[str]:
    inspector = inspect(engine)
    if table not in inspector.get_table_names():
        return set()
    return {c["name"] for c in inspector.get_columns(table)}

def run_lightweight_migrations(engine: Engine) -> None:
    ticket_cols = _columns(engine, "tickets")
    if ticket_cols:
        additions = {
            "web_uid": "VARCHAR(36) NULL",
            "requester_name": "VARCHAR(180) DEFAULT ''",
            "requester_phone": "VARCHAR(80) DEFAULT ''",
            "room": "VARCHAR(80) DEFAULT ''",
            "master_name": "VARCHAR(180) DEFAULT ''",
            "master_comment": "TEXT DEFAULT ''",
            "onec_sync_error": "TEXT DEFAULT ''",
            "onec_synced_at": "DATETIME NULL" if engine.dialect.name == "sqlite" else "TIMESTAMP NULL",
        }
        with engine.begin() as conn:
            for name, ddl in additions.items():
                if name not in ticket_cols:
                    conn.execute(text(f"ALTER TABLE tickets ADD COLUMN {name} {ddl}"))

    attachment_cols = _columns(engine, "attachments")
    if attachment_cols and "comment_id" not in attachment_cols:
        with engine.begin() as conn:
            # The ORM relationship supplies the logical FK. Keeping this migration
            # additive avoids table rebuilds on older SQLite installations.
            conn.execute(text("ALTER TABLE attachments ADD COLUMN comment_id INTEGER NULL"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_attachments_comment_id ON attachments (comment_id)"))

    stock_cols = _columns(engine, "stock_movements")
    if stock_cols:
        additions = {
            "unit_cost_snapshot": "NUMERIC(12,2) NULL",
            "amount": "NUMERIC(12,2) NULL",
            "issued_by_id": "INTEGER NULL",
        }
        with engine.begin() as conn:
            for name, ddl in additions.items():
                if name not in stock_cols:
                    conn.execute(text(f"ALTER TABLE stock_movements ADD COLUMN {name} {ddl}"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_stock_movements_issued_by_id ON stock_movements (issued_by_id)"))

            # Older installations did not save the issue price on each movement.
            # Backfill it from the current catalogue value once so historical
            # rows can be displayed with a meaningful amount after upgrade.
            conn.execute(text("""
                UPDATE stock_movements
                   SET unit_cost_snapshot = (
                       SELECT inventory_items.unit_cost
                         FROM inventory_items
                        WHERE inventory_items.id = stock_movements.item_id
                   )
                 WHERE movement_type = 'issue'
                   AND unit_cost_snapshot IS NULL
            """))
            conn.execute(text("""
                UPDATE stock_movements
                   SET amount = ABS(qty) * COALESCE(unit_cost_snapshot, 0)
                 WHERE movement_type = 'issue'
                   AND amount IS NULL
            """))


    user_cols = _columns(engine, "users")
    if user_cols:
        additions = {
            "email": "VARCHAR(160) DEFAULT ''",
            "phone": "VARCHAR(80) DEFAULT ''",
            "telegram_chat_id": "VARCHAR(80) DEFAULT ''",
            "totp_secret": "VARCHAR(64) DEFAULT ''",
            "totp_enabled": "BOOLEAN DEFAULT FALSE",
        }
        with engine.begin() as conn:
            for name, ddl in additions.items():
                if name not in user_cols:
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {name} {ddl}"))

    equipment_cols = _columns(engine, "equipment")
    if equipment_cols:
        additions = {
            "parent_id": "INTEGER NULL",
            "owner_user_id": "INTEGER NULL",
            "criticality": "VARCHAR(20) DEFAULT 'normal'",
        }
        with engine.begin() as conn:
            for name, ddl in additions.items():
                if name not in equipment_cols:
                    conn.execute(text(f"ALTER TABLE equipment ADD COLUMN {name} {ddl}"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_equipment_parent_id ON equipment (parent_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_equipment_owner_user_id ON equipment (owner_user_id)"))

    ticket_cols2 = _columns(engine, "tickets")
    if ticket_cols2 and "service_id" not in ticket_cols2:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE tickets ADD COLUMN service_id INTEGER NULL"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tickets_service_id ON tickets (service_id)"))

# v0.7 phase 1: additive ticket ownership/group/template fields.
def _run_v070_phase1(engine: Engine) -> None:
    ticket_cols = _columns(engine, "tickets")
    if not ticket_cols:
        return
    additions = {
        "creator_id": "INTEGER NULL",
        "group_id": "INTEGER NULL",
        "template_id": "INTEGER NULL",
    }
    with engine.begin() as conn:
        for name, ddl in additions.items():
            if name not in ticket_cols:
                conn.execute(text(f"ALTER TABLE tickets ADD COLUMN {name} {ddl}"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tickets_creator_id ON tickets (creator_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tickets_group_id ON tickets (group_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tickets_template_id ON tickets (template_id)"))
        # Existing tickets were normally created by their requester, so use that
        # as the safest historical fallback. New tickets keep creator/requester separate.
        conn.execute(text("UPDATE tickets SET creator_id=requester_id WHERE creator_id IS NULL AND requester_id IS NOT NULL"))

_original_run_lightweight_migrations_v065 = run_lightweight_migrations

def run_lightweight_migrations(engine: Engine) -> None:
    _original_run_lightweight_migrations_v065(engine)
    _run_v070_phase1(engine)

# v0.7.1: ticket lifecycle, SLA pause and optimistic edit version.
def _run_v071_lifecycle(engine: Engine) -> None:
    ticket_cols = _columns(engine, "tickets")
    if not ticket_cols:
        return
    dt_type = "DATETIME NULL" if engine.dialect.name == "sqlite" else "TIMESTAMP NULL"
    additions = {
        "sla_paused_at": dt_type,
        "sla_paused_seconds": "INTEGER DEFAULT 0",
        "edit_version": "INTEGER DEFAULT 1",
    }
    with engine.begin() as conn:
        for name, ddl in additions.items():
            if name not in ticket_cols:
                conn.execute(text(f"ALTER TABLE tickets ADD COLUMN {name} {ddl}"))
        conn.execute(text("UPDATE tickets SET sla_paused_seconds=0 WHERE sla_paused_seconds IS NULL"))
        conn.execute(text("UPDATE tickets SET edit_version=1 WHERE edit_version IS NULL OR edit_version < 1"))
        # Existing waiting tickets begin their SLA pause at the last known update.
        conn.execute(text("UPDATE tickets SET sla_paused_at=COALESCE(updated_at, created_at, CURRENT_TIMESTAMP) WHERE status='waiting' AND sla_paused_at IS NULL AND sla_due_at IS NOT NULL"))
        # History tables are already created by Base.metadata.create_all. Backfill one
        # marker per old ticket so future durations are correct without inventing past transitions.
        conn.execute(text("""
            INSERT INTO ticket_status_history (ticket_id, from_status, to_status, changed_by_id, changed_at, previous_duration_seconds, source)
            SELECT t.id, '', t.status, NULL, COALESCE(t.updated_at, t.created_at), 0, 'backfill'
              FROM tickets t
             WHERE NOT EXISTS (SELECT 1 FROM ticket_status_history h WHERE h.ticket_id=t.id)
        """))

_original_run_lightweight_migrations_v070 = run_lightweight_migrations

def run_lightweight_migrations(engine: Engine) -> None:
    _original_run_lightweight_migrations_v070(engine)
    _run_v071_lifecycle(engine)


# v0.7.2: directory fields used by AD/LDAP synchronization.
def _run_v072_integrations(engine: Engine) -> None:
    user_cols = _columns(engine, "users")
    if not user_cols:
        return
    additions = {
        "department_id": "INTEGER NULL",
        "manager_user_id": "INTEGER NULL",
        "external_dn": "VARCHAR(500) DEFAULT ''",
        "directory_source": "VARCHAR(30) DEFAULT 'local'",
    }
    with engine.begin() as conn:
        for name, ddl in additions.items():
            if name not in user_cols:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {name} {ddl}"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_users_department_id ON users (department_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_users_manager_user_id ON users (manager_user_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_users_external_dn ON users (external_dn)"))

_original_run_lightweight_migrations_v071 = run_lightweight_migrations

def run_lightweight_migrations(engine: Engine) -> None:
    _original_run_lightweight_migrations_v071(engine)
    _run_v072_integrations(engine)

# v0.7.3: labor costing and hierarchical classifier fields.
def _run_v073_cmdb_labor(engine: Engine) -> None:
    user_cols = _columns(engine, "users")
    if user_cols and "hourly_rate" not in user_cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE users ADD COLUMN hourly_rate NUMERIC(12,2) DEFAULT 0"))
            conn.execute(text("UPDATE users SET hourly_rate=0 WHERE hourly_rate IS NULL"))

    ticket_cols = _columns(engine, "tickets")
    if ticket_cols and "manual_labor_cost" not in ticket_cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE tickets ADD COLUMN manual_labor_cost NUMERIC(12,2) DEFAULT 0"))
            # Preserve previously entered work/service costs as a manual component.
            conn.execute(text("UPDATE tickets SET manual_labor_cost=COALESCE(labor_cost,0) WHERE manual_labor_cost IS NULL OR manual_labor_cost=0"))

    session_cols = _columns(engine, "ticket_work_sessions")
    if session_cols:
        additions = {
            "hourly_rate_snapshot": "NUMERIC(12,2) NULL",
            "labor_amount": "NUMERIC(12,2) NULL",
        }
        with engine.begin() as conn:
            for name, ddl in additions.items():
                if name not in session_cols:
                    conn.execute(text(f"ALTER TABLE ticket_work_sessions ADD COLUMN {name} {ddl}"))

    # Base.metadata.create_all creates category_nodes before this migration. Seed the
    # old flat ticket categories once so existing installations get a usable tree.
    tables = inspect(engine).get_table_names()
    if "category_nodes" in tables and "ui_styles" in tables:
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO category_nodes (kind, name, code, parent_id, sort_order, active, created_at)
                SELECT 'ticket', u.name, u.code, NULL, u.sort_order, u.active, CURRENT_TIMESTAMP
                  FROM ui_styles u
                 WHERE u.kind='category'
                   AND NOT EXISTS (
                       SELECT 1 FROM category_nodes c
                        WHERE c.kind='ticket' AND c.name=u.name AND c.parent_id IS NULL
                   )
            """))

_original_run_lightweight_migrations_v072 = run_lightweight_migrations

def run_lightweight_migrations(engine: Engine) -> None:
    _original_run_lightweight_migrations_v072(engine)
    _run_v073_cmdb_labor(engine)

# v0.7.4: localization preferences and external CMDB identity.
def _run_v074_experience(engine: Engine) -> None:
    user_cols = _columns(engine, "users")
    if user_cols:
        additions = {
            "timezone": "VARCHAR(64) DEFAULT 'Asia/Almaty'",
            "locale": "VARCHAR(10) DEFAULT 'ru'",
        }
        with engine.begin() as conn:
            for name, ddl in additions.items():
                if name not in user_cols:
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {name} {ddl}"))
            conn.execute(text("UPDATE users SET timezone='Asia/Almaty' WHERE timezone IS NULL OR timezone=''"))
            conn.execute(text("UPDATE users SET locale='ru' WHERE locale IS NULL OR locale=''"))

    equipment_cols = _columns(engine, "equipment")
    if equipment_cols:
        additions = {
            "external_source": "VARCHAR(30) DEFAULT ''",
            "external_key": "VARCHAR(120) DEFAULT ''",
        }
        with engine.begin() as conn:
            for name, ddl in additions.items():
                if name not in equipment_cols:
                    conn.execute(text(f"ALTER TABLE equipment ADD COLUMN {name} {ddl}"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_equipment_external_key ON equipment (external_key)"))

_original_run_lightweight_migrations_v073 = run_lightweight_migrations

def run_lightweight_migrations(engine: Engine) -> None:
    _original_run_lightweight_migrations_v073(engine)
    _run_v074_experience(engine)
