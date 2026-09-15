STATUS_LABELS = {
    "new": "Новая",
    "assigned": "Назначена",
    "in_progress": "В работе",
    "waiting": "Ожидание материалов",
    "resolved": "Выполнена",
    "closed": "Закрыта",
    "cancelled": "Отменена",
}

PRIORITY_LABELS = {
    "low": "Низкий",
    "normal": "Обычный",
    "high": "Высокий",
    "critical": "Срочный",
}

ROLE_LABELS = {
    "requester": "Заявитель",
    "technician": "Техник",
    "dispatcher": "Диспетчер",
    "manager": "Руководитель",
    "admin": "Администратор",
}

EQUIPMENT_STATUS_LABELS = {
    "working": "Работает",
    "broken": "Неисправно",
    "repair": "В ремонте",
    "decommissioned": "Списано",
}

def label(mapping: dict[str, str], value: str | None) -> str:
    if value is None:
        return "—"
    return mapping.get(value, value)
