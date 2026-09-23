# Обновление FMTS до v0.7.5

1. Сделайте резервную копию PostgreSQL / Supabase и папки вложений.
2. Замените файлы проекта содержимым архива v0.7.5.
3. На Render выполните `Manual Deploy → Clear build cache & deploy`.
4. Ручной SQL не требуется: миграция выполняется автоматически.
5. После запуска откройте `Service Desk → SLA-календари` и проверьте основной рабочий календарь.
6. В `Каталог сервисов` задайте SLA реакции/решения и календарь для нужных сервисов.
7. Для интеграций откройте `Управление → Интеграции → Исходящие Webhooks`.
8. Полностью перезапустите установленное PWA, чтобы обновить service worker.

## Новые поля tickets

- `ticket_type`
- `planned_start_at`
- `planned_end_at`
- `response_due_at`
- `first_response_at`
- `business_calendar_id`

## Новые поля service_catalog

- `response_sla_minutes`
- `resolution_sla_minutes`
- `business_calendar_id`

## Новые таблицы

- `business_calendars`
- `equipment_relations`
- `webhook_endpoints`
- `webhook_deliveries`

Существующий `default_sla_hours` не удаляется и остаётся fallback-полем для обратной совместимости.
