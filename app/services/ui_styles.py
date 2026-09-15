from __future__ import annotations
import re
from datetime import datetime
from sqlalchemy.orm import Session
from app.models import UiStyle
from app.labels import STATUS_LABELS, PRIORITY_LABELS, EQUIPMENT_STATUS_LABELS

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")

FALLBACKS = {
    "status": {
        "new": {"name":"Новая","bg":"#e7f0ff","text":"#1b5ebc","border":"#c9dcfb","order":10},
        "assigned": {"name":"Назначена","bg":"#eee9ff","text":"#6540a5","border":"#dbd0fa","order":20},
        "in_progress": {"name":"В работе","bg":"#fff0d9","text":"#a45e00","border":"#f2d6aa","order":30},
        "waiting": {"name":"Ожидание материалов","bg":"#f3edf7","text":"#725280","border":"#e3d6ea","order":40},
        "resolved": {"name":"Выполнена","bg":"#e4f5ec","text":"#23724e","border":"#c8e8d7","order":50},
        "closed": {"name":"Закрыта","bg":"#e4f5ec","text":"#23724e","border":"#c8e8d7","order":60},
        "cancelled": {"name":"Отменена","bg":"#f0f1f3","text":"#687384","border":"#dde1e6","order":70},
    },
    "priority": {
        "low": {"name":"Низкий","bg":"#eef1f5","text":"#536071","border":"#dce2e9","sla":72,"order":10},
        "normal": {"name":"Обычный","bg":"#e7f0ff","text":"#1b5ebc","border":"#c9dcfb","sla":24,"order":20},
        "high": {"name":"Высокий","bg":"#fff0d9","text":"#a45e00","border":"#f2d6aa","sla":8,"order":30},
        "critical": {"name":"Срочный","bg":"#fde2e5","text":"#b12b36","border":"#f3c4c9","sla":2,"order":40},
    },
    "equipment_status": {
        "working": {"name":"Работает","bg":"#e4f5ec","text":"#23724e","border":"#c8e8d7","order":10},
        "broken": {"name":"Неисправно","bg":"#fde9eb","text":"#a72e39","border":"#f3c7cb","order":20},
        "repair": {"name":"В ремонте","bg":"#fff0d9","text":"#a45e00","border":"#f2d6aa","order":30},
        "decommissioned": {"name":"Списано","bg":"#f0f1f3","text":"#687384","border":"#dde1e6","order":40},
    },
}


def _color(value: object) -> str:
    text = str(value or "").strip()
    return text.upper() if HEX.match(text) else ""


def normalize_kind(value: object) -> str:
    s = str(value or "").strip().lower().replace(" ", "_")
    aliases = {
        "статус": "status", "статусы": "status",
        "приоритет": "priority", "приоритеты": "priority",
        "категория": "category", "категории": "category",
        "статус_оборудования": "equipment_status", "оборудование": "equipment_status",
    }
    return aliases.get(s, s)


def _pick(row: dict, *names, default=None):
    low = {str(k).lower(): v for k, v in row.items()}
    for name in names:
        if name in row:
            return row[name]
        if name.lower() in low:
            return low[name.lower()]
    return default


def upsert_ui_styles(db: Session, payload: object, *, full_replace: bool = True) -> int:
    if isinstance(payload, dict):
        rows = payload.get("items") or payload.get("value") or payload.get("data") or []
    else:
        rows = payload
    if not isinstance(rows, list):
        raise ValueError("Ожидался массив настроек подсветки")

    count = 0
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        kind = normalize_kind(_pick(row, "kind", "type", "Тип", "ТипОформления", default=""))
        code = str(_pick(row, "code", "Код", "КодВеб", default="") or "").strip()
        if kind not in {"status", "priority", "category", "equipment_status"} or not code:
            continue
        name = str(_pick(row, "name", "Наименование", "Представление", default=code) or code).strip()
        obj = db.query(UiStyle).filter(UiStyle.kind == kind, UiStyle.code == code).first()
        if not obj:
            obj = UiStyle(kind=kind, code=code)
            db.add(obj)
        obj.name = name
        obj.bg_color = _color(_pick(row, "bg_color", "background", "ЦветФона", default=""))
        obj.text_color = _color(_pick(row, "text_color", "color", "ЦветТекста", default=""))
        obj.border_color = _color(_pick(row, "border_color", "border", "ЦветГраницы", default=""))
        try:
            raw_sla = _pick(row, "sla_hours", "SLAЧасов", "СЛАЧасов", default=None)
            obj.sla_hours = int(raw_sla) if raw_sla not in (None, "") else None
        except Exception:
            obj.sla_hours = None
        try:
            obj.sort_order = int(_pick(row, "sort_order", "Порядок", default=100) or 100)
        except Exception:
            obj.sort_order = 100
        active = _pick(row, "active", "Активен", default=True)
        obj.active = str(active).lower() not in {"false", "0", "нет"}
        obj.synced_at = datetime.utcnow()
        seen.add((kind, code))
        count += 1

    # Optional external import may disable absent values only when explicitly requested.
    if rows and full_replace:
        kinds = {k for k, _ in seen}
        for kind in kinds:
            for obj in db.query(UiStyle).filter(UiStyle.kind == kind).all():
                if (obj.kind, obj.code) not in seen:
                    obj.active = False
    db.commit()
    return count


def styles_cache(db: Session) -> dict[str, dict[str, dict]]:
    result: dict[str, dict[str, dict]] = {}
    for obj in db.query(UiStyle).filter(UiStyle.active == True).order_by(UiStyle.kind, UiStyle.sort_order, UiStyle.id).all():
        result.setdefault(obj.kind, {})[obj.code] = {
            "name": obj.name or obj.code,
            "bg": obj.bg_color,
            "text": obj.text_color,
            "border": obj.border_color,
            "sla": obj.sla_hours,
            "order": obj.sort_order,
            "source": "local",
        }
    return result


def style_for(cache: dict, kind: str, code: str) -> dict:
    item = cache.get(kind, {}).get(code)
    if item:
        return item
    return FALLBACKS.get(kind, {}).get(code, {"name": code, "bg":"", "text":"", "border":"", "order":100, "source":"fallback"})


def badge_css(cache: dict, kind: str, code: str) -> str:
    item = style_for(cache, kind, code)
    chunks = []
    if item.get("bg"): chunks.append(f"background-color:{item['bg']}")
    if item.get("text"): chunks.append(f"color:{item['text']}")
    if item.get("border"): chunks.append(f"border:1px solid {item['border']}")
    return ";".join(chunks)


def display_name(cache: dict, kind: str, code: str, fallback: str | None = None) -> str:
    item = cache.get(kind, {}).get(code)
    if item and item.get("name"):
        return item["name"]
    if kind == "status": return STATUS_LABELS.get(code, fallback or code)
    if kind == "priority": return PRIORITY_LABELS.get(code, fallback or code)
    if kind == "equipment_status": return EQUIPMENT_STATUS_LABELS.get(code, fallback or code)
    return fallback or code


def options_for(db: Session, kind: str, fallback: list[tuple[str, str]]) -> list[dict]:
    rows = db.query(UiStyle).filter(UiStyle.kind == kind, UiStyle.active == True).order_by(UiStyle.sort_order, UiStyle.id).all()
    if not rows:
        return [{"code":c, "name":n, "sla":FALLBACKS.get(kind,{}).get(c,{}).get("sla")} for c,n in fallback]
    return [{"code":r.code, "name":r.name or r.code, "sla":r.sla_hours} for r in rows]


def sla_hours_for(db: Session, priority_code: str) -> int:
    row = db.query(UiStyle).filter(UiStyle.kind == "priority", UiStyle.code == priority_code, UiStyle.active == True).first()
    if row and row.sla_hours and row.sla_hours > 0:
        return row.sla_hours
    return int(FALLBACKS["priority"].get(priority_code, FALLBACKS["priority"]["normal"]).get("sla", 24))
