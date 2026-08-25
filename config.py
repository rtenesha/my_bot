from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

DB_PATH = os.getenv("DB_PATH", "bot.db")

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