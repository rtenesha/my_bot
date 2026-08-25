from __future__ import annotations

import asyncio
import logging
from calendar import isleap
from datetime import date, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import db
import scheduler
from config import BOT_TOKEN, POPULAR_TZS
from parser import parse_birthday

logging.basicConfig(level=logging.INFO)

# Dispatcher строится на уровне модуля — его переиспользуют и вебхук-функция
# (api/bot.py), и локальный polling-режим для разработки. FSM не используется:
# многошаговые флоу хранятся в таблице pending_actions (serverless stateless).
dp = Dispatcher(storage=MemoryStorage())

MONTHS_RU = [
    "", "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]

EXAMPLE = "Пример: «Мама 15.03.1990» или «Мама 15 марта» (год — по желанию)."


# --- Helpers ---

def fmt_date(day: int, month: int, year: int | None) -> str:
    s = f"{day} {MONTHS_RU[month]}"
    if year:
        s += f" {year} года"
    return s


def age_if_known(person: dict) -> str:
    if person["birth_year"] is None:
        return ""
    today = date.today()
    age = today.year - person["birth_year"]
    if (today.month, today.day) < (person["birth_month"], person["birth_day"]):
        age -= 1
    return f" (сейчас {age})"


def person_card(person: dict) -> str:
    return (
        f"👤 {person['name']}\n"
        f"📅 {fmt_date(person['birth_day'], person['birth_month'], person['birth_year'])}"
        + age_if_known(person)
    )


def person_card_kb(person_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Изменить", callback_data=f"edit:{person_id}"),
         InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete:{person_id}")],
        [InlineKeyboardButton(text="＋ Идея подарка", callback_data=f"addwish:{person_id}"),
         InlineKeyboardButton(text="💡 Идеи", callback_data=f"wishes:{person_id}")],
        [InlineKeyboardButton(text="« Назад", callback_data="back:list")],
    ])


def people_list_kb(people: list[dict]) -> InlineKeyboardMarkup:
    today = date.today()
    people_sorted = sorted(people, key=lambda p: scheduler.next_birthday(p, today))
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{p['name']} — {fmt_date(p['birth_day'], p['birth_month'], None)}",
            callback_data=f"person:{p['id']}",
        )] for p in people_sorted
    ])


# --- /start, /help, /cancel ---

@dp.message(CommandStart())
async def cmd_start(message: Message):
    db.ensure_user(message.chat.id)
    db.clear_pending(message.chat.id)
    await message.answer(
        "Привет! Я напоминаю о днях рождения 🎂\n\n"
        "Как добавить человека:\n"
        "Просто напиши «Мама 15.03.1990» — или без года: «Мама 15 марта»\n\n"
        "Команды:\n"
        "/add — добавить\n"
        "/list — все люди\n"
        "/today — чьи ДР сегодня\n"
        "/upcoming — ближайшие ДР\n"
        "/settings — часовой пояс и время уведомления\n"
        "/help — справка"
    )


@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        f"Напиши «Имя дата» — например «Мама 15.03.1990» или «Папа 20 мая».\n"
        f"Год — по желанию (нужен для возраста и юбилеев).\n\n"
        f"Команды: /add /list /today /upcoming /settings /cancel"
    )


@dp.message(Command("cancel"))
async def cmd_cancel(message: Message):
    db.clear_pending(message.chat.id)
    await message.answer("Отменено.")


# --- Добавление ---

async def _do_add(message: Message, text: str, *, is_command_add: bool):
    parsed = parse_birthday(text)
    if not parsed:
        await message.answer(f"Не понял. {EXAMPLE}")
        return
    name, day, month, year = parsed
    db.ensure_user(message.chat.id)
    db.add_person(message.chat.id, name, day, month, year)
    db.clear_pending(message.chat.id)
    await message.answer(f"✅ Записал: {name} — {fmt_date(day, month, year)}")


@dp.message(Command("add"))
async def cmd_add(message: Message):
    db.ensure_user(message.chat.id)
    db.set_pending(message.chat.id, "add")
    await message.answer(f"Введи «Имя дата». {EXAMPLE}")


@dp.message(F.text & ~F.text.startswith("/"))
async def text_handler(message: Message):
    """Единый текстовый хендлер: диспатчит по pending_action (замена FSM)."""
    chat_id = message.chat.id
    text = message.text.strip()
    pending = db.get_pending(chat_id)
    action = pending["action"] if pending else None

    if action == "edit":
        await _handle_edit(message, pending, text)
    elif action == "addwish":
        await _handle_addwish(message, pending, text)
    elif action == "set_tz":
        await _handle_set_tz(message, text)
    elif action == "set_time":
        await _handle_set_time(message, text)
    else:
        # None или "add" — добавление человека
        await _do_add(message, text, is_command_add=(action == "add"))


async def _handle_edit(message: Message, pending: dict, text: str):
    parsed = parse_birthday(text)
    if not parsed:
        await message.answer(f"Не понял. {EXAMPLE}\n/cancel — отмена.")
        return
    name, day, month, year = parsed
    person_id = pending["person_id"]
    db.update_person(person_id, name=name, birth_day=day, birth_month=month, birth_year=year)
    db.clear_pending(message.chat.id)
    await message.answer(f"✅ Обновил: {name} — {fmt_date(day, month, year)}")


async def _handle_addwish(message: Message, pending: dict, text: str):
    if not text:
        await message.answer("Пусто. Попробуй ещё или /cancel.")
        return
    db.add_wish(pending["person_id"], text)
    db.clear_pending(message.chat.id)
    await message.answer("✅ Идея добавлена.")


async def _handle_set_tz(message: Message, text: str):
    tz = text.strip()
    try:
        ZoneInfo(tz)
    except ZoneInfoNotFoundError:
        await message.answer(f"Не знаю такой пояс. Пример: «Europe/Moscow». /cancel — отмена.")
        return
    db.update_tz(message.chat.id, tz)
    db.clear_pending(message.chat.id)
    await message.answer(f"✅ Пояс: {tz}")


async def _handle_set_time(message: Message, text: str):
    parts = text.strip().replace(".", ":").split(":")
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        await message.answer("Не понял. Пример: «09:00». /cancel — отмена.")
        return
    h, m = int(parts[0]), int(parts[1])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        await message.answer("Часы 0–23, минуты 0–59. Попробуй ещё.")
        return
    db.update_notify_time(message.chat.id, h, m)
    db.clear_pending(message.chat.id)
    await message.answer(f"✅ Буду уведомлять в {h:02d}:{m:02d}")


# --- Просмотр ---

@dp.message(Command("list"))
async def cmd_list(message: Message):
    db.clear_pending(message.chat.id)
    people = db.list_people(message.chat.id)
    if not people:
        await message.answer("Список пуст. Добавь: «Мама 15.03.1990»")
        return
    await message.answer("Твои люди (ближайшие сверху):", reply_markup=people_list_kb(people))


@dp.message(Command("today"))
async def cmd_today(message: Message):
    db.clear_pending(message.chat.id)
    today = date.today()
    people = db.list_people(message.chat.id)
    found = [p for p in people
             if (p["birth_day"], p["birth_month"]) == (today.day, today.month)]
    if today.month == 2 and today.day == 28 and not isleap(today.year):
        found = [p for p in people if p["birth_day"] == 29 and p["birth_month"] == 2]
    if not found:
        await message.answer("Сегодня ни у кого нет дня рождения.")
        return
    lines = ["Сегодня день рождения:\n"]
    for p in found:
        lines.append(f"🎂 {p['name']} — {fmt_date(p['birth_day'], p['birth_month'], p['birth_year'])}{age_if_known(p)}")
    await message.answer("\n".join(lines))


@dp.message(Command("upcoming"))
async def cmd_upcoming(message: Message):
    db.clear_pending(message.chat.id)
    people = db.list_people(message.chat.id)
    if not people:
        await message.answer("Список пуст. Добавь: «Мама 15.03.1990»")
        return
    today = date.today()
    horizon = today + timedelta(days=30)
    upcoming = []
    for p in people:
        nb = scheduler.next_birthday(p, today)
        if nb <= horizon:
            upcoming.append((nb, p))
    if not upcoming:
        await message.answer("В ближайшие 30 дней дней рождения нет.")
        return
    upcoming.sort(key=lambda x: x[0])
    lines = ["Ближайшие дни рождения:\n"]
    for nb, p in upcoming:
        days = (nb - today).days
        when = "сегодня" if days == 0 else ("завтра" if days == 1 else f"через {days} дн.")
        lines.append(f"• {p['name']} — {fmt_date(p['birth_day'], p['birth_month'], p['birth_year'])} ({when})")
    await message.answer("\n".join(lines))


# --- Карточка человека ---

@dp.callback_query(F.data.startswith("person:"))
async def cb_person(callback: CallbackQuery):
    person_id = int(callback.data.split(":", 1)[1])
    person = db.get_person(person_id)
    if not person:
        await callback.answer("Не найдено")
        await callback.message.answer("Человек не найден.")
        return
    await callback.message.edit_text(
        person_card(person), reply_markup=person_card_kb(person_id),
    )
    await callback.answer()


@dp.callback_query(F.data == "back:list")
async def cb_back_list(callback: CallbackQuery):
    people = db.list_people(callback.message.chat.id)
    if not people:
        await callback.message.edit_text("Список пуст.")
        await callback.answer()
        return
    await callback.message.edit_text("Твои люди (ближайшие сверху):", reply_markup=people_list_kb(people))
    await callback.answer()


# --- Редактирование ---

@dp.callback_query(F.data.startswith("edit:"))
async def cb_edit_start(callback: CallbackQuery):
    person_id = int(callback.data.split(":", 1)[1])
    db.set_pending(callback.message.chat.id, "edit", person_id=person_id)
    await callback.message.answer(f"Введи заново «Имя дата» (старое заменится). {EXAMPLE}")
    await callback.answer()


# --- Удаление ---

@dp.callback_query(F.data.startswith("delete:"))
async def cb_delete_start(callback: CallbackQuery):
    person_id = int(callback.data.split(":", 1)[1])
    person = db.get_person(person_id)
    if not person:
        await callback.answer("Не найдено")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Да, удалить", callback_data=f"delconfirm:{person_id}")],
        [InlineKeyboardButton(text="« Отмена", callback_data=f"person:{person_id}")],
    ])
    await callback.message.edit_text(f"Удалить {person['name']}?", reply_markup=kb)
    await callback.answer()


@dp.callback_query(F.data.startswith("delconfirm:"))
async def cb_delete_confirm(callback: CallbackQuery):
    person_id = int(callback.data.split(":", 1)[1])
    db.delete_person(person_id)
    await callback.message.edit_text("🗑 Удалено.")
    await callback.answer()


# --- Wishlist ---

@dp.callback_query(F.data.startswith("addwish:"))
async def cb_addwish_start(callback: CallbackQuery):
    person_id = int(callback.data.split(":", 1)[1])
    db.set_pending(callback.message.chat.id, "addwish", person_id=person_id)
    await callback.message.answer("Введи идею подарка:")
    await callback.answer()


@dp.callback_query(F.data.startswith("wishes:"))
async def cb_wishes(callback: CallbackQuery):
    person_id = int(callback.data.split(":", 1)[1])
    wishes = db.list_wishes(person_id)
    if not wishes:
        await callback.message.edit_text("Идей пока нет. Нажми «＋ Идея подарка» в карточке.")
        await callback.answer()
        return
    buttons = [
        [InlineKeyboardButton(text=f"🗑 {w['text'][:40]}", callback_data=f"delwish:{w['id']}")]
        for w in wishes
    ]
    buttons.append([InlineKeyboardButton(text="« Назад", callback_data=f"person:{person_id}")])
    await callback.message.edit_text("Идеи подарков:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@dp.callback_query(F.data.startswith("delwish:"))
async def cb_delwish(callback: CallbackQuery):
    wish_id = int(callback.data.split(":", 1)[1])
    db.delete_wish(wish_id)
    await callback.answer("Удалено")
    await callback.message.edit_text("Удалено. Открой «💡 Идеи» снова, чтобы обновить список.")


# --- Настройки ---

@dp.message(Command("settings"))
async def cmd_settings(message: Message):
    db.clear_pending(message.chat.id)
    db.ensure_user(message.chat.id)
    u = db.get_user(message.chat.id)
    buttons = [[InlineKeyboardButton(text=tz, callback_data=f"tz:{tz}")] for tz in POPULAR_TZS]
    buttons.append([InlineKeyboardButton(text="✏️ Свой пояс", callback_data="tz:custom")])
    buttons.append([InlineKeyboardButton(text="🕐 Изменить время", callback_data="time:set")])
    await message.answer(
        f"Текущие настройки:\n"
        f"🌍 Пояс: {u['tz']}\n"
        f"🕐 Уведомление в {u['notify_hour']:02d}:{u['notify_minute']:02d}\n\n"
        f"Часовой пояс:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@dp.callback_query(F.data.startswith("tz:"))
async def cb_tz(callback: CallbackQuery):
    value = callback.data.split(":", 1)[1]
    if value == "custom":
        db.set_pending(callback.message.chat.id, "set_tz")
        await callback.message.answer("Введи свой пояс, например «Europe/Moscow» или «Asia/Almaty». /cancel — отмена.")
        await callback.answer()
        return
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError:
        await callback.answer("Неизвестный пояс")
        return
    db.update_tz(callback.message.chat.id, value)
    await callback.answer("Сохранено")
    await callback.message.answer(f"✅ Пояс: {value}")


@dp.callback_query(F.data == "time:set")
async def cb_time_set(callback: CallbackQuery):
    db.set_pending(callback.message.chat.id, "set_time")
    await callback.message.answer("Введи время уведомления, например «09:00».")
    await callback.answer()


# --- Локальный polling-режим для разработки ---
# В проде бот работает через вебхук (api/bot.py); этот блок — только для
# локальной отладки: TURSO_DATABASE_URL=file:./dev.db python bot.py

if __name__ == "__main__":
    async def _main():
        db.init_db()
        bot = Bot(token=BOT_TOKEN)
        await dp.start_polling(bot)

    asyncio.run(_main())