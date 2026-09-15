# Архитектура v0.3 Standalone Core

```text
Browser / PWA
      |
    FastAPI
      |
      +-- Users / roles
      +-- Tickets / SLA / comments / files
      +-- Sites / equipment / QR
      +-- Maintenance / PPR
      +-- Inventory / stock movements
      +-- Contractors / costs
      +-- Local reference data / colors / SLA
      |
  SQLite (demo) or PostgreSQL (production)
      |
  Optional connectors
      +-- 1C
      +-- future Telegram / email / ERP / WMS
```

## Ownership

The TOIR database owns all operational data and reference values. External systems are never
required for core operation.

## 1C boundary

All 1C-specific code is isolated in `app/services/one_c.py`, `app/services/sync.py`, API routes
under `/api/integration/1c/*`, and the package `integrations/1c/`.

When `ONEC_ENABLED=false`:

- no network request to 1C is required for normal work;
- incoming 1C webhooks return 404;
- 1C fields are hidden from the user interface;
- local statuses/colors/SLA remain fully functional.

## Database modes

- Windows quick start: SQLite (`toir.db`).
- Docker/production: PostgreSQL 16.

File attachments are stored in `uploads/`; database metadata stores the attachment references.
---

**Разработчик: Кирилл Вадимович Богунов © 2026**  
Telegram: [@kirill_bogunov](https://t.me/kirill_bogunov)

