from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

# Хранилище. Возможные значения:
#   - "libsql://<db>.turso.io" / "https://..." / "http://..."  → Turso через libsql (прод)
#   - "file:./dev.db" или путь к файлу                          → локальная БД (дев/тесты)
#   - None                                                      → локальный bot.db рядом с процессом
TURSO_DATABASE_URL = os.getenv("TURSO_DATABASE_URL")
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN")  # None для локального режима

# Секрет для защиты вебхука/крон-эндпоинта от посторонних вызовов.
CRON_SECRET = os.getenv("CRON_SECRET", "")

# Дефолты для нового пользователя.
DEFAULT_TZ = "Europe/Moscow"
DEFAULT_NOTIFY_HOUR = 9
DEFAULT_NOTIFY_MINUTE = 0

# Популярные часовые пояса для кнопок в /settings.
POPULAR_TZS = [
    "Europe/Moscow",
    "Asia/Yekaterinburg",
    "Asia/Krasnoyarsk",
    "Asia/Vladivostok",
]