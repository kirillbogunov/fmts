from app.db import normalize_database_url


def test_supabase_postgresql_url_uses_psycopg_v3():
    raw = "postgresql://postgres.ref:secret@pooler.example.com:5432/postgres?sslmode=require"
    assert normalize_database_url(raw).startswith("postgresql+psycopg://")
    assert "?sslmode=require" in normalize_database_url(raw)


def test_legacy_postgres_scheme_is_supported():
    raw = "postgres://user:secret@example.com/db"
    assert normalize_database_url(raw) == "postgresql+psycopg://user:secret@example.com/db"


def test_psycopg2_scheme_is_upgraded():
    raw = "postgresql+psycopg2://user:secret@example.com/db"
    assert normalize_database_url(raw) == "postgresql+psycopg://user:secret@example.com/db"


def test_sqlite_url_is_unchanged():
    raw = "sqlite:///./toir.db"
    assert normalize_database_url(raw) == raw
