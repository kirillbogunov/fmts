# Обновление FMTS до v0.7.2

1. Сделайте резервную копию Supabase/PostgreSQL.
2. Замените файлы проекта версией v0.7.2.
3. Render → Manual Deploy → Clear build cache & deploy.
4. Новые поля users и новые таблицы создаются автоматически.
5. Для AD/LDAP задайте LDAP_* переменные. Для IMAP/SMTP используйте существующие IMAP_* / SMTP_* переменные.
6. SSO gateway по умолчанию выключен и не должен включаться без доверенного reverse proxy/IdP.
