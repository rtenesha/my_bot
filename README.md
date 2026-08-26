# Birthday Reminder Bot

Telegram-бот, который напоминает о днях рождения. Вбиваешь людей и их даты —
в день рождения приходит напоминание. Мультитенантный (у каждого свой список и
часовой пояс), год рождения — по желанию (для возраста и юбилеев), есть wishlist
с идеями подарков.

## Архитектура (полностью бесплатно, без банковской карты)

```
Telegram ──вебхук──▶ Vercel Python-функция (api/bot.py, ASGI) ──▶ aiogram Dispatcher (bot.py)
                          │
GitHub Actions (cron 1/час) ──▶ remind.py ──▶ scheduler.check_and_send ──▶ Bot API
                          │
                          ▼
                    Turso (libSQL по HTTP) — единая БД
```

- **Vercel Hobby** (бесплатно) — принимает входящие сообщения через вебхук.
  Новый Vercel Python runtime ставит зависимости через `uv` и требует
  `[project]` + `tool.vercel.entrypoint` в `pyproject.toml`; функция —
  ASGI-приложение `app` (см. `api/bot.py`). Vercel-крон на бесплатном тарифе
  только раз в сутки, поэтому напоминания гоним через GitHub Actions.
- **GitHub Actions** (бесплатно) — cron раз в час запускает `remind.py`.
- **Turso** (бесплатно, без карты) — постоянное хранилище, SQLite-совместимая
  БД по HTTP. Локально/в тестах вместо неё используется stdlib `sqlite3`.

Хранилище переключается одной переменной `TURSO_DATABASE_URL`: локальный путь
или `file:` → `sqlite3`; `libsql://`/`https://` → Turso через `libsql`.

## Файлы

| Файл | Назначение |
|---|---|
| `bot.py` | aiogram: команды, inline-карточки, хендлеры. FSM заменён таблицей `pending_actions` (serverless stateless). |
| `api/bot.py` | Vercel-функция: ASGI-приложение `app`, принимает вебхук и кормит апдейт в `dp`. Обрабатывает любой путь. |
| `pyproject.toml` | `[project].dependencies` для `uv` + `tool.vercel.entrypoint = "api.bot:app"`. |
| `requirements.txt` | зависимости для локального `pip install` (дублирует `[project]`, плюс тестовые). |
| `db.py` | слой БД (sync; `sqlite3` локально / `libsql` для Turso). |
| `parser.py` | парсер естественного ввода «Мама 15.03.1990». |
| `scheduler.py` | логика рассылки (`check_and_send`), часовые пояса, 29.02. |
| `remind.py` | точка входа для GitHub Actions. |
| `set_webhook.py` | разовая регистрация вебхука. |
| `tests/` | pytest: parser, db, scheduler, webhook smoke. |

## Локальная разработка

```bash
python3 -m venv .venv && . .venv/bin/activate
# libsql нужен только для прод-коннекта к Turso; локально/в тестах хватает sqlite3:
pip install -r requirements.txt

# .env:
#   BOT_TOKEN=<токен бота>
#   TURSO_DATABASE_URL=file:./dev.db

python bot.py        # polling-режим для отладки
pytest               # 66 тестов
python -m remind     # запустить рассылку вручную (проверка напоминаний)
```

> `libsql` собирается только с prebuilt-колесом (cp310–cp313, manylinux x86_64
> и macOS arm64). На старых macOS/Python 3.9 x86_64 колеса нет — там локально
> используется `sqlite3`, а к Turso подключаются только Vercel/Actions.

## Деплой

### 1. Turso
```bash
curl -sSfL https://get.tur.so/install.sh | bash   # без Homebrew
turso auth signup
turso db create birthday
turso db tokens create birthday   # → это TURSO_AUTH_TOKEN
turso db show birthday --url      # → это TURSO_DATABASE_URL (libsql://...)

# сразу создать схему (без Python, прямо через Turso CLI):
python3 -c "import sys; sys.path.insert(0,'.'); import db; \
print(';\n'.join(db._SCHEMA_STATEMENTS)+';\n', end='')" > /tmp/schema.sql
turso db shell birthday < /tmp/schema.sql
```

### 2. Vercel (через CLI, без карты)
```bash
npm i -g vercel            # или запускать через `npx -y vercel ...`
vercel login               # Continue with GitHub
vercel --prod --yes        # создаёт проект и деплоит; даёт URL

# env-переменные (Production):
printf '%s' "$BOT_TOKEN"           | vercel env add BOT_TOKEN production
printf '%s' "<TURSO_DATABASE_URL>" | vercel env add TURSO_DATABASE_URL production
printf '%s' "<TURSO_AUTH_TOKEN>"   | vercel env add TURSO_AUTH_TOKEN production

vercel --prod --yes        # редеплой с env → функция работает
```
После деплоя взять стабильный alias: `https://<app>.vercel.app`.
Функция (ASGI `app`) обрабатывает любой путь, вебхук живёт на `.../api/bot`.

### 3. Регистрация вебхука (один раз)
```bash
python3 set_webhook.py https://<app>.vercel.app/api/bot
```
Health-check: `curl -s https://<app>.vercel.app/api/bot` → `ok`.
Удалить вебхук (вернуться на polling): `python3 set_webhook.py delete`.

### 4. GitHub Actions (напоминания)
В Secrets репозитория (Settings → Secrets and variables → Actions) добавить:
`BOT_TOKEN`, `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`.
Workflow `.github/workflows/remind.yml` крутится раз в час (`3 * * * *`).
⚠️ GitHub Actions cron срабатывает только на ветке по умолчанию (`main`).
Проверить вручную: Actions → **birthday-remind** → **Run workflow**.

## Использование
- Добавить: `Мама 15.03.1990` (год по желанию: `Мама 15 марта`).
- Команды: `/add` `/list` `/today` `/upcoming` `/settings` `/help` `/cancel`.
- В карточке (`/list` → имя): дата/возраст, «＋ Идея подарка», «Изменить», «Удалить».

## Проверка
- `pytest` — зелёный (66).
- Отправить боту «Мама 15.03.1990» → `/list` → карточка →
  «＋ Идея подарка» → `/today`/`/upcoming`.
- Напоминания: добавить человека с ДР сегодня, в `/settings` поставить время
  уведомления раньше текущего, запустить workflow (или дождаться крона) —
  придёт сообщение, повторно в тот же день не придёт (идемпотентно через
  `sent_reminders`).