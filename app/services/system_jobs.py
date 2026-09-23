from __future__ import annotations
from datetime import datetime
import traceback
from typing import Callable, Any
from app.db import SessionLocal
from app.models import BackgroundServiceLog


def run_logged_job(service: str, fn: Callable[[Any], Any]) -> Any:
    db = SessionLocal()
    started = datetime.utcnow()
    try:
        result = fn(db)
        db.commit()
        finished = datetime.utcnow()
        db.add(BackgroundServiceLog(
            service=service,
            status="ok",
            message=f"Выполнено: {result}" if result is not None else "Выполнено",
            started_at=started,
            finished_at=finished,
            duration_ms=max(0, int((finished-started).total_seconds()*1000)),
        ))
        db.commit()
        return result
    except Exception as exc:
        db.rollback()
        finished = datetime.utcnow()
        db.add(BackgroundServiceLog(
            service=service,
            status="error",
            message=str(exc)[:500],
            details=traceback.format_exc()[-12000:],
            started_at=started,
            finished_at=finished,
            duration_ms=max(0, int((finished-started).total_seconds()*1000)),
        ))
        db.commit()
        return None
    finally:
        db.close()
