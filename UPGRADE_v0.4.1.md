# Обновление FMTS до v0.4.1

Для Render добавьте в **Environment**:

```text
PUBLIC_BASE_URL=https://fmts-demo.onrender.com
COOKIE_HTTPS_ONLY=true
```

`Root Directory` оставьте пустым, если `app/` и `requirements.txt` находятся в корне репозитория.

После загрузки файлов в GitHub выполните **Manual Deploy → Deploy latest commit**.

Уже созданные/напечатанные QR-коды можно оставить: изображение QR генерируется динамически по прежнему URL `/equipment/<id>/qr.png`, а закодированная публичная ссылка будет формироваться заново при открытии/печати QR. Если QR-картинка была ранее сохранена как отдельный PNG, её нужно сгенерировать повторно.
