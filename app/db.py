from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.config import get_settings

settings = get_settings()


def normalize_database_url(value: str) -> str:
    """Normalize common PostgreSQL URLs to the psycopg v3 SQLAlchemy driver.

    Supabase/Render commonly provide a URL starting with ``postgresql://``.
    SQLAlchemy treats that legacy form as the psycopg2 dialect, while FMTS
    intentionally ships psycopg v3 (``psycopg[binary]``). Accept the common
    provider formats automatically so DATABASE_URL can be pasted directly.
    """
    url = (value or "").strip()
    if url.startswith("postgresql+psycopg2://"):
        return "postgresql+psycopg://" + url[len("postgresql+psycopg2://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    return url


database_url = normalize_database_url(settings.database_url)
connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
engine_kwargs = {"connect_args": connect_args, "future": True}
if database_url.startswith("postgresql"):
    engine_kwargs["pool_pre_ping"] = True

engine = create_engine(database_url, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
