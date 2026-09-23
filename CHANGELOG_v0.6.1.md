# FMTS v0.6.1 — Render hotfix

- исправлена синтаксическая ошибка в `app/routes/web.py`, из-за которой Render завершал запуск с `SyntaxError: unmatched }`;
- проверена компиляция всех Python-модулей (`python -m compileall app`);
- полный набор тестов проходит успешно: 30 passed;
- добавлен `.python-version` с Python 3.12.10 для стабильного окружения Render;
- функциональность Enterprise ServiceDesk v0.6.0 сохранена без изменений.
