# JSON-контракт FMTS ↔ 1С

## 1С → TOIR: webhook заявки

`POST /api/1c/webhook/tickets`

Header:

```text
X-TOIR-TOKEN: <ONEC_WEBHOOK_TOKEN>
Content-Type: application/json
```

Пример:

```json
{
  "id": "GUID-документа-1С",
  "web_id": "UUID-веб-заявки",
  "number": "000000123",
  "date": "2026-09-15T15:10:00",
  "requester": "Иванов И.И.",
  "department_id": "GUID-подразделения",
  "department": "Магазин №3",
  "room": "Торговый зал",
  "phone": "+7...",
  "category": "Электрика",
  "priority": "Обычный",
  "description": "Не работает освещение",
  "master": "Петров П.П.",
  "status": "ВРаботе",
  "resolved_at": null,
  "master_comment": ""
}
```

Идемпотентность: для заявок из 1С используется `id` = GUID ссылки `ЗаявкаХозОтдела`; для заявок, созданных в вебе, используется технический `web_id`, который хранится в реквизите `WebID` документа. Это предотвращает дубль при обратном webhook из `ПослеЗаписи`.

## TOIR → 1С: HTTP-сервис

Корень: `/hs/toir/v1`.

- `GET /sites` — список `Справочник.Подразделения`;
- `GET /tickets` — последние `Документ.ЗаявкаХозОтдела`;
- `POST /tickets` — создать/обновить `ЗаявкаХозОтдела`;
- `GET /equipment` — после добавления справочника оборудования;
- `GET /inventory` — после привязки к фактическому складскому регистру.

Ответ `POST /tickets`:

```json
{"ok": true, "id": "GUID", "number": "000000124"}
```

## Карта статусов

| Web | 1С |
|---|---|
| `new` | `Новая` |
| `assigned` | `Назначена` |
| `in_progress` | `ВРаботе` |
| `waiting` | `ОжиданиеМатериалов` |
| `resolved` | `Выполнена` |
| `closed` | `Закрыта` |
| `cancelled` | `Отменена` |

## Карта приоритетов

| Web | 1С |
|---|---|
| `low` | `Низкий` |
| `normal` | `Обычный` |
| `high` | `Высокий` |
| `critical` | `Срочный` |
---

**Разработчик: Кирилл Вадимович Богунов © 2026**  
Telegram: [@kirill_bogunov](https://t.me/kirill_bogunov)

