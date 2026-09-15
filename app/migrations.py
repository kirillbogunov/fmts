from sqlalchemy import text
from sqlalchemy.engine import Engine

# Lightweight SQLite migration so a v0.1 database can be opened by v0.2
# without Alembic. New installations still use Base.metadata.create_all().

def run_lightweight_migrations(engine: Engine) -> None:
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as conn:
        tables = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        if "tickets" not in tables:
            return
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(tickets)"))}
        additions = {
            "web_uid": "VARCHAR(36) NULL",
            "requester_name": "VARCHAR(180) DEFAULT ''",
            "requester_phone": "VARCHAR(80) DEFAULT ''",
            "room": "VARCHAR(80) DEFAULT ''",
            "master_name": "VARCHAR(180) DEFAULT ''",
            "master_comment": "TEXT DEFAULT ''",
            "onec_sync_error": "TEXT DEFAULT ''",
            "onec_synced_at": "DATETIME NULL",
        }
        for name, ddl in additions.items():
            if name not in cols:
                conn.execute(text(f"ALTER TABLE tickets ADD COLUMN {name} {ddl}"))
