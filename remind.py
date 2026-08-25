from __future__ import annotations

import asyncio
import logging

from aiogram import Bot

import db
import scheduler
from config import BOT_TOKEN

logging.basicConfig(level=logging.INFO)


async def main() -> None:
    """Разовая проверка и рассылка напоминаний.

    Запускается по расписанию GitHub Actions (cron раз в час). Идемпотентна:
    повторный запуск в тот же час не дублирует отправки (защита в sent_reminders).
    """
    db.init_db()
    bot = Bot(token=BOT_TOKEN)
    try:
        await scheduler.check_and_send(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())