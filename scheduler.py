from __future__ import annotations

import logging
from calendar import isleap
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError

import db

logger = logging.getLogger(__name__)


def event_date_for(person: dict, today: date) -> date:
    """Дата дня рождения в текущем году.

    Для 29.02 в невисокосный год — 28.02 (по спецификации).
    """
    day, month = person["birth_day"], person["birth_month"]
    if month == 2 and day == 29 and not isleap(today.year):
        return date(today.year, 2, 28)
    return date(today.year, month, day)


def next_birthday(person: dict, today: date) -> date:
    """Ближайшая дата дня рождения (сегодня или в будущем)."""
    ed = event_date_for(person, today)
    if ed >= today:
        return ed
    nxt = today.year + 1
    if person["birth_month"] == 2 and person["birth_day"] == 29 and not isleap(nxt):
        return date(nxt, 2, 28)
    return date(nxt, person["birth_month"], person["birth_day"])


def format_message(person: dict, event_date: date, wishes: list[dict]) -> str:
    """Текст напоминания (plain text — без Markdown, т.к. имя/wishlist от пользователя)."""
    name = person["name"]
    birth_year = person["birth_year"]

    if birth_year is None:
        line = f"🎂 Сегодня день рождения: {name}"
    else:
        age = event_date.year - birth_year
        if age > 0 and age % 10 == 0:
            line = f"🎂 Сегодня у {name} юбилей — исполняется {age}! 🎉"
        else:
            line = f"🎂 Сегодня у {name} день рождения — исполняется {age}!"

    if wishes:
        items = "\n".join(f" • {w['text']}" for w in wishes)
        line += f"\n\n💡 Идеи подарков:\n{items}"
    return line


def _birthday_candidates(today: date) -> list[tuple[int, int]]:
    """Хранимые (day, month), которые сегодня считаются днём рождения.

    В невисокосный год 28.02 — ещё и день рождения для людей 29.02.
    """
    candidates = [(today.day, today.month)]
    if today.month == 2 and today.day == 28 and not isleap(today.year):
        candidates.append((29, 2))
    return candidates


async def check_and_send(bot, now_utc: datetime | None = None) -> None:
    """Проходит по всем пользователям и рассылает напоминания о ДР сегодня.

    `now_utc` — точка отсчёта (для тестов); по умолчанию текущее UTC-время.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    for u in await db.all_users():
        tz = ZoneInfo(u["tz"])
        now_local = now_utc.astimezone(tz)
        today_local = now_local.date()

        # Рано — местное время ещё не дошло до времени уведомления.
        notify_at = now_local.replace(
            hour=u["notify_hour"], minute=u["notify_minute"], second=0, microsecond=0
        )
        if now_local < notify_at:
            continue

        people: list[dict] = []
        for day, month in _birthday_candidates(today_local):
            people.extend(
                await db.get_people_with_birthday_on(u["chat_id"], day, month)
            )

        for person in people:
            event_date = event_date_for(person, today_local)
            event_key = event_date.isoformat()
            if await db.already_sent(person["id"], event_key):
                continue

            wishes = await db.list_wishes(person["id"])
            text = format_message(person, event_date, wishes)

            try:
                await bot.send_message(u["chat_id"], text)
            except TelegramForbiddenError:
                # Пользователь заблокировал бота — помечаем отправленным,
                # чтобы не пытаться снова каждый час. В мёртвый чат не спамим.
                logger.warning("send_message forbidden for chat_id=%s", u["chat_id"])
                await _mark_sent_safe(person["id"], event_key)
            except TelegramAPIError:
                # Другая ошибка Telegram — не отмечаем, попробуем на следующем запуске.
                logger.warning("send_message failed for chat_id=%s", u["chat_id"], exc_info=True)
                continue
            else:
                await _mark_sent_safe(person["id"], event_key)


async def _mark_sent_safe(person_id: int, event_key: str) -> None:
    """Помечает отправленным; гонка (дубль) тихо игнорируется."""
    import sqlite3

    try:
        await db.mark_sent(person_id, event_key)
    except sqlite3.IntegrityError:
        pass


def start_scheduler(bot) -> AsyncIOScheduler:
    """Запускает APScheduler с ежечасной проверкой (в :05)."""
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        check_and_send,
        "cron",
        minute=5,
        args=[bot],
        id="birthday_check",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    return scheduler