import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from starlette.middleware.sessions import SessionMiddleware
from app.config import get_settings
from app.db import Base, engine, SessionLocal, get_db
from app.migrations import run_lightweight_migrations
from app.routes.web import router as web_router
from app.routes.api import router as api_router
from app.routes.enterprise import router as enterprise_router
from app.routes.operations import router as operations_router
from app.services.maintenance import generate_due_maintenance
from app.services.reference_data import ensure_default_reference_data
from app.security import current_user
from app.access import has_permission
from app.services.automation import process_sla_escalations
from app.services.email_channel import poll_mailbox
from app.services.report_subscriptions import process_report_subscriptions
from app.services.reminders import process_ticket_reminders

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


async def enterprise_loop():
    while True:
        db=SessionLocal()
        try:
            process_sla_escalations(db)
            poll_mailbox(db)
            process_report_subscriptions(db)
            process_ticket_reminders(db)
        except Exception as exc:
            print("enterprise background error:", exc)
            db.rollback()
        finally:
            db.close()
        await asyncio.sleep(max(30, settings.enterprise_loop_seconds))

@asynccontextmanager
async def lifespan(app: FastAPI):
    db=SessionLocal()
    try:
        ensure_default_reference_data(db)
    finally:
        db.close()
    task=asyncio.create_task(maintenance_loop())
    enterprise_task=asyncio.create_task(enterprise_loop())
    yield
    task.cancel(); enterprise_task.cancel()
    with suppress(asyncio.CancelledError): await task
    with suppress(asyncio.CancelledError): await enterprise_task

app=FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
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
app.include_router(api_router)
app.include_router(enterprise_router)
app.include_router(operations_router)
app.include_router(web_router)


def _admin_for_docs(request: Request, db=Depends(get_db)):
    user=current_user(request,db)
    if not user:
        raise HTTPException(401,"Требуется авторизация")
    if not has_permission(user,"users.manage"):
        raise HTTPException(403,"Документация API доступна только администратору")
    return user

@app.get("/openapi.json", include_in_schema=False)
def protected_openapi(request: Request, db=Depends(get_db)):
    _admin_for_docs(request,db)
    schema=get_openapi(title=app.title,version=app.version,description=app.description,routes=app.routes)
    return JSONResponse(schema)

@app.get("/docs", include_in_schema=False)
def protected_docs(request: Request, db=Depends(get_db)):
    _admin_for_docs(request,db)
    return get_swagger_ui_html(openapi_url="/openapi.json",title=f"{settings.app_name} API")
