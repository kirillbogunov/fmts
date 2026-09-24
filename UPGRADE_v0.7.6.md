# Обновление FMTS до v0.7.6

1. Сделайте резервную копию PostgreSQL / Supabase и каталога `UPLOAD_DIR`.
2. Замените проект содержимым архива v0.7.6.
3. Render → `Manual Deploy` → `Clear build cache & deploy`.
4. Ручной SQL не требуется. При старте добавляется `tickets.maintenance_plan_id`, а новые таблицы чек-листов и файлов базы знаний создаются автоматически.
5. После деплоя откройте `ТО / ППР`: старые текстовые чек-листы будут автоматически преобразованы в новый конструктор.
6. На телефоне полностью закройте PWA и откройте снова, чтобы service worker v0.7.6 заменил старый интерфейс.

Новые таблицы:
- `maintenance_checklist_items`;
- `ticket_checklist_items`;
- `knowledge_attachments`.

Новые вложения базы знаний хранятся внутри `UPLOAD_DIR/knowledge`. Для production желательно использовать постоянное дисковое хранилище Render или другой persistent volume.
