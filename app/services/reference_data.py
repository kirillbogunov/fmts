from __future__ import annotations
from datetime import datetime
from sqlalchemy.orm import Session
from app.models import UiStyle

DEFAULT_REFERENCE_DATA = {
    "status": [
        ("new", "Новая", "#e7f0ff", "#1b5ebc", "#c9dcfb", None, 10),
        ("assigned", "Назначена", "#eee9ff", "#6540a5", "#dbd0fa", None, 20),
        ("in_progress", "В работе", "#fff0d9", "#a45e00", "#f2d6aa", None, 30),
        ("waiting", "Ожидание материалов", "#f3edf7", "#725280", "#e3d6ea", None, 40),
        ("resolved", "Выполнена", "#e4f5ec", "#23724e", "#c8e8d7", None, 50),
        ("closed", "Закрыта", "#dff3e8", "#1d6846", "#bddfcf", None, 60),
        ("cancelled", "Отменена", "#f0f1f3", "#687384", "#dde1e6", None, 70),
    ],
    "priority": [
        ("low", "Низкий", "#eef1f5", "#536071", "#dce2e9", 72, 10),
        ("normal", "Обычный", "#e7f0ff", "#1b5ebc", "#c9dcfb", 24, 20),
        ("high", "Высокий", "#fff0d9", "#a45e00", "#f2d6aa", 8, 30),
        ("critical", "Срочный", "#fde2e5", "#b12b36", "#f3c4c9", 2, 40),
    ],
    "category": [
        ("Ремонт", "Ремонт", "#eef3ff", "#345f9b", "#d3e0f6", None, 5),
        ("Электрика", "Электрика", "#fff7d6", "#775d00", "#ecdf9d", None, 10),
        ("Сантехника", "Сантехника", "#e4f5ff", "#18627d", "#bee5f2", None, 20),
        ("Холодильное оборудование", "Холодильное оборудование", "#e8f7ff", "#1b6687", "#c5e9f7", None, 30),
        ("Климат", "Климат", "#eaf2ff", "#2e5f9a", "#ccdff7", None, 40),
        ("Мебель", "Мебель", "#f6efe8", "#7e5a39", "#e6d4c0", None, 50),
        ("Отделка", "Отделка", "#f4effa", "#684b86", "#dfd1ed", None, 60),
        ("Окна", "Окна", "#edf7f4", "#346a5c", "#d1e8e1", None, 70),
        ("Двери", "Двери", "#f8f1ea", "#795b41", "#ead8c8", None, 80),
        ("Компьютер", "Компьютер", "#eef0ff", "#4c57a0", "#d7daf7", None, 90),
        ("ППР/ТО", "ППР / ТО", "#e7f5ec", "#2a704a", "#c9e6d5", None, 100),
        ("Другое", "Другое", "#f0f1f3", "#596475", "#dde1e6", None, 999),
    ],
    "equipment_status": [
        ("working", "Работает", "#e4f5ec", "#23724e", "#c8e8d7", None, 10),
        ("broken", "Неисправно", "#fde9eb", "#a72e39", "#f3c7cb", None, 20),
        ("repair", "В ремонте", "#fff0d9", "#a45e00", "#f2d6aa", None, 30),
        ("decommissioned", "Списано", "#f0f1f3", "#687384", "#dde1e6", None, 40),
    ],
}


def ensure_default_reference_data(db: Session) -> int:
    """Create local reference values if they are missing.

    The TOIR database is the master source. External integrations may import data
    only when an administrator explicitly requests it.
    """
    created = 0
    for kind, rows in DEFAULT_REFERENCE_DATA.items():
        for code, name, bg, text, border, sla, order in rows:
            obj = db.query(UiStyle).filter(UiStyle.kind == kind, UiStyle.code == code).first()
            if obj:
                continue
            db.add(UiStyle(kind=kind, code=code, name=name, bg_color=bg, text_color=text,
                           border_color=border, sla_hours=sla, sort_order=order,
                           active=True, synced_at=datetime.utcnow()))
            created += 1
    if created:
        db.commit()
    return created
