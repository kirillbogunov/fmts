# Обновление до FMTS v0.7.4

1. Сделайте резервную копию PostgreSQL/Supabase.
2. Замените файлы проекта версией v0.7.4.
3. Выполните Render → Manual Deploy → Clear build cache & deploy.
4. Новые таблицы создаются автоматически; в `users` добавятся `timezone` и `locale`, в `equipment` — `external_source` и `external_key`.
5. Для Zabbix задайте переменные из `.env.example`. Без них интеграция остаётся выключенной.
6. После обновления пользователь может выбрать язык и часовой пояс в Профиле.
