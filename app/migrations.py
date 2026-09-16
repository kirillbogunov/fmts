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
