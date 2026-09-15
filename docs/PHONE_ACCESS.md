# Доступ к TOIR с телефона из любого места

ТОиР v0.3 — самостоятельное приложение. Для удалённой работы ему не нужна 1С.

## Рекомендуемая схема без белого IP

```text
Телефон / ноутбук
      |
    HTTPS
      |
Cloudflare Tunnel
      |
Сервер клиента
  TOIR + PostgreSQL
```

Входящие порты на роутере и белый IP не требуются: `cloudflared` устанавливает исходящее
соединение с Cloudflare.

## Быстрая демонстрация без домена

После запуска TOIR на `http://127.0.0.1:8000` можно использовать Quick Tunnel:

```powershell
cloudflared tunnel --url http://localhost:8000
```

Он выдаст временный HTTPS-адрес вида `https://...trycloudflare.com`. Укажите его в `.env` как
`BASE_URL`, а `COOKIE_HTTPS_ONLY` переключите в `true`, затем перезапустите TOIR.

Quick Tunnel подходит для презентации. Для постоянной эксплуатации используйте именованный Tunnel
и собственный домен.

## Постоянный Cloudflare Tunnel

Пример адреса: `https://toir.company.kz`.

```powershell
cloudflared tunnel login
cloudflared tunnel create toir
cloudflared tunnel route dns toir toir.company.kz
cloudflared tunnel run toir
```

Пример конфигурации находится в `deploy/cloudflare/config.yml.example`.

В `.env`:

```env
BASE_URL=https://toir.company.kz
COOKIE_HTTPS_ONLY=true
```

## Установка как приложение

### Android / Chrome

1. Откройте HTTPS-адрес ТОиР.
2. Авторизуйтесь.
3. Нажмите `Установить` или Chrome → `Установить приложение`.

### iPhone / Safari

1. Откройте ТОиР в Safari.
2. `Поделиться` → `На экран «Домой»`.

QR-коды оборудования используют `BASE_URL`, поэтому перед печатью QR обязательно укажите
постоянный внешний адрес.

## Альтернатива: Tailscale

Если доступ нужен только сотрудникам и публичный hostname не нужен, сервер и телефоны можно
подключить к приватной сети Tailscale. В этом случае приложение будет доступно только участникам VPN.

## Безопасность

- не публикуйте PostgreSQL в Интернет;
- не пробрасывайте порт 8000 напрямую на роутере;
- используйте HTTPS;
- смените пароль администратора;
- задайте длинный `SECRET_KEY`;
- при необходимости поставьте Cloudflare Access перед страницей входа.
---

**Разработчик: Кирилл Вадимович Богунов © 2026**  
Telegram: [@kirill_bogunov](https://t.me/kirill_bogunov)

