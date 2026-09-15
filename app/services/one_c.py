from __future__ import annotations
from typing import Any
from datetime import datetime
import httpx
from app.config import get_settings

class OneCError(RuntimeError):
    pass

STATUS_WEB_TO_1C = {
    "new": "Новая",
    "assigned": "Назначена",
    "in_progress": "ВРаботе",
    "waiting": "ОжиданиеМатериалов",
    "resolved": "Выполнена",
    "closed": "Закрыта",
    "cancelled": "Отменена",
}
STATUS_1C_TO_WEB = {v.lower(): k for k, v in STATUS_WEB_TO_1C.items()}
# tolerate human-readable variants from 1C forms/JSON
STATUS_1C_TO_WEB.update({
    "в работе": "in_progress", "ожидание материалов": "waiting",
    "выполнена": "resolved", "закрыта": "closed", "отменена": "cancelled",
    "назначена": "assigned", "новая": "new",
})

PRIORITY_WEB_TO_1C = {
    "low": "Низкий", "normal": "Обычный", "high": "Высокий", "critical": "Срочный",
}
PRIORITY_1C_TO_WEB = {v.lower(): k for k, v in PRIORITY_WEB_TO_1C.items()}

OLD_1C_CATEGORIES = {
    "Электрика", "Сантехника", "Мебель", "Отделка", "Кондиционер",
    "Окна", "Двери", "Компьютер", "Другое",
}

def status_to_1c(value: str) -> str:
    return STATUS_WEB_TO_1C.get((value or "").strip(), value or "Новая")

def status_from_1c(value: Any) -> str:
    text = str(value or "").strip()
    return STATUS_1C_TO_WEB.get(text.lower(), text if text in STATUS_WEB_TO_1C else "new")

def priority_to_1c(value: str) -> str:
    return PRIORITY_WEB_TO_1C.get((value or "").strip(), value or "Обычный")

def priority_from_1c(value: Any) -> str:
    text = str(value or "").strip()
    return PRIORITY_1C_TO_WEB.get(text.lower(), text if text in PRIORITY_WEB_TO_1C else "normal")

def category_to_1c(value: str) -> str:
    value = (value or "").strip()
    if value in OLD_1C_CATEGORIES:
        return value
    if value.upper() == "IT":
        return "Компьютер"
    return "Другое"

class OneCClient:
    def __init__(self):
        self.s = get_settings()

    def _url(self, path: str) -> str:
        return self.s.onec_base_url.rstrip("/") + "/" + path.lstrip("/")

    def _client(self):
        auth = (self.s.onec_username, self.s.onec_password) if self.s.onec_username else None
        return httpx.Client(
            auth=auth,
            verify=self.s.onec_verify_ssl,
            timeout=self.s.onec_timeout,
            headers={"Accept":"application/json", "Content-Type":"application/json; charset=utf-8"},
        )

    def enabled(self) -> bool:
        return bool(self.s.onec_enabled and self.s.onec_base_url)

    def health(self) -> dict[str, Any]:
        if not self.enabled():
            return {"ok": False, "message": "Интеграция 1С выключена в .env"}
        try:
            with self._client() as c:
                r = c.get(self._url(self.s.onec_sites_path), params={"$top": 1} if self.s.onec_mode == "odata" else None)
                return {"ok": r.is_success, "status": r.status_code, "message": r.text[:250] if not r.is_success else "Соединение установлено"}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    def get_items(self, path: str) -> list[dict[str, Any]]:
        if not self.enabled():
            raise OneCError("Интеграция 1С выключена")
        with self._client() as c:
            r = c.get(self._url(path))
            if not r.is_success:
                raise OneCError(f"1С HTTP {r.status_code}: {r.text[:500]}")
            data = r.json()
        if isinstance(data, list): return data
        if isinstance(data, dict):
            for key in ("items", "value", "data"):
                if isinstance(data.get(key), list): return data[key]
        raise OneCError("Неожиданный формат ответа 1С")

    def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled():
            raise OneCError("Интеграция 1С выключена")
        with self._client() as c:
            r = c.post(self._url(path), json=payload)
            if not r.is_success:
                raise OneCError(f"1С HTTP {r.status_code}: {r.text[:500]}")
            if not r.content: return {"ok": True}
            try: return r.json()
            except Exception: return {"ok": True, "text": r.text[:500]}

def pick(row: dict, *names, default=None):
    lowered = {str(k).lower(): v for k,v in row.items()}
    for n in names:
        if n in row: return row[n]
        if n.lower() in lowered: return lowered[n.lower()]
    return default

def parse_1c_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).replace(tzinfo=None)
    except Exception:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y"):
            try: return datetime.strptime(text, fmt)
            except Exception: pass
    return None
