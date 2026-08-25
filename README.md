# Birthday Reminder Bot

Telegram-бот, который напоминает о днях рождения. Вбиваешь людей и их даты —
в день рождения приходит напоминание. Мультитенантный (у каждого свой список и
часовой пояс), год рождения — по желанию (для возраста и юбилеев), есть wishlist
с идеями подарков.

## Архитектура (полностью бесплатно, без банковской карты)

```
Telegram ──вебхук──▶ Vercel Python-функция (api/bot.py) ──▶ aiogram Dispatcher (bot.py)
                          │
GitHub Actions (cron 1/час) ──▶ remind.py ──▶ scheduler.check_and_send ──▶ Bot API
                          │
                          ▼
                    Turso (libSQL по HTTP) — единая БД
```

- **Vercel Hobby** (бесплатно) — принимает входящие сообщения через вебхук.
  Vercel-крон на бесплатном тарифе только раз в сутки, поэтому напоминания
  гоним через GitHub Actions.
- **GitHub Actions** (бесплатно) — cron раз в час запускает `remind.py`.
- **Turso** (бесплатно, без карты) — постоянное хранилище, SQLite-совместимая
  БД по HTTP. Локально/в тестах вместо неё используется stdlib `sqlite3`.

Хранилище переключается одной переменной `TURSO_DATABASE_URL`: локальный путь
или `file:` → `sqlite3`; `libsql://`/`https://` → Turso через `libsql`.

## Файлы

| Файл | Назначение |
|---|---|
| `bot.py` | aiogram: команды, inline-карточки, хендлеры. FSM заменён таблицей `pending_actions` (serverless stateless). |
| `api/bot.py` | Vercel-функция: принимает вебхук, кормит апдейт в `dp`. |
| `db.py` | слой БД (sync; `sqlite3` локально / `libsql` для Turso). |
| `parser.py` | парсер естественного ввода «Мама 15.03.1990». |
| `scheduler.py` | логика рассылки (`check_and_send`), часовые пояса, 29.02. |
| `remind.py` | точка входа для GitHub Actions. |
| `set_webhook.py` | разовая регистрация вебхука. |
| `tests/` | pytest: parser, db, scheduler. |

## Локальная разработка

```bash
python -m venv .venv && . .venv/bin/activate
# libsql нужен только для прод-коннекта к Turso; локально достаточно:
pip install aiogram python-dotenv pytest pytest-asyncio

# .env:
#   BOT_TOKEN=<токен бота>
#   TURSO_DATABASE_URL=file:./dev.db

python bot.py        # polling-режим для отладки
pytest              # 57 тестов
python -m remind    # запустить рассылку вручную (проверка напоминаний)
```

## Деплой

### 1. Turso
```bash
brew install tursodb/tap/turso   # или через скрипт установки Turso CLI
turso auth signup
turso db create birthday
turso db tokens create birthday   # → это TURSO_AUTH_TOKEN
turso db show birthday --url      # → это TURSO_DATABASE_URL (libsql://...)
```

### 2. Vercel
1. Залить репо на GitHub, импортировать проект в Vercel (автодеплой из GitHub).
2. Environment Variables: `BOT_TOKEN`, `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`.
3. После деплоя взять URL функции: `https://<app>.vercel.app/api/bot`.

### 3. Регистрация вебхука (один раз)
```bash
python set_webhook.py https://<app>.vercel.app/api/bot
```

### 4. GitHub Actions (напоминания)
В Secrets репозитория добавить: `BOT_TOKEN`, `TURSO_DATABASE_URL`,
`TURSO_AUTH_TOKEN`. Workflow `.github/workflows/remind.yml` крутится раз в час.
⚠️ GitHub Actions cron срабатывает только на ветке по умолчанию —
сольёт `birthday-bot` в `main`, чтобы крон заработал.

## Проверка
- `pytest` — зелёный.
- Отправить боту «Мама 15.03.1990» → `Мама 15 марта` → `/list` → карточка →
  «＋ Идея подарка» → `/today`/`/upcoming`.
- Напоминания: добавить человека с ДР сегодня, в `/settings` поставить время
  уведомления раньше текущего, запустить `python -m remind` (или дождаться
  крона) — придёт сообщение, повторно не придёт.