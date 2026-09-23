# FMTS v0.6.2 — Render / Supabase database URL hotfix

- FMTS now accepts Supabase/Render PostgreSQL URLs beginning with `postgresql://` or `postgres://` directly.
- Such URLs are normalized automatically to SQLAlchemy's `postgresql+psycopg://` dialect used by the project's installed `psycopg` v3 driver.
- Legacy `postgresql+psycopg2://` URLs are also normalized to psycopg v3.
- Added `pool_pre_ping` for PostgreSQL connections to recover cleanly from stale pooled connections.
- No database schema changes are required.
