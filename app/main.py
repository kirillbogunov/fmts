import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from app.config import get_settings
from app.db import Base, engine, SessionLocal
from app.migrations import run_lightweight_migrations
from app.routes.web import router as web_router
from app.routes.api import router as api_router
from app.services.maintenance import generate_due_maintenance
from app.services.reference_data import ensure_default_reference_data

settings=get_settings()
Base.metadata.create_all(bind=engine)
run_lightweight_migrations(engine)
Path(settings.upload_dir).mkdir(parents=True,exist_ok=True)

async def maintenance_loop():
    while True:
        db=SessionLocal()
        try:
            generate_due_maintenance(db)
        except Exception as exc:
            print("maintenance job error:", exc)
        finally:
            db.close()
        await asyncio.sleep(3600)

@asynccontextmanager
async def lifespan(app: FastAPI):
    db=SessionLocal()
    try:
        ensure_default_reference_data(db)
    finally:
        db.close()
    task=asyncio.create_task(maintenance_loop())
    yield
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task

app=FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "FMTS — Facility Management & Task System. Система задач и мониторинга работы хозяйственного отдела, ServiceDesk / ТОиР. "
        f"Разработчик: {settings.developer_name} © 2026 · Telegram: {settings.developer_telegram}"
    ),
    contact={"name": settings.developer_name, "url": settings.developer_url},
    lifespan=lifespan,
)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    max_age=60*60*12,
    same_site="lax",
    https_only=settings.cookie_https_only,
)
app.mount("/static",StaticFiles(directory=str(Path(__file__).resolve().parent/"static")),name="static")
app.mount("/uploads",StaticFiles(directory=settings.upload_dir),name="uploads")
app.include_router(api_router)
app.include_router(web_router)
