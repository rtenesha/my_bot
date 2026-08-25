from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup, default_state
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

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

MONTHS_RU = [
    "", "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


# --- FSM States ---

class AddPerson(StatesGroup):
    waiting_input = State()

class EditPerson(StatesGroup):
    waiting_input = State()       # person_id в state data; вводим «Имя дата»

class DeletePerson(StatesGroup):
    pass                          # подтверждение через inline-кнопку

class AddWish(StatesGroup):
    waiting_text = State()        # person_id в state data

class Settings(StatesGroup):
    waiting_tz = State()
    waiting_time = State()


# --- Helpers ---

def fmt_date(day: int, month: int, year: int | None) -> str:
    s = f"{day} {MONTHS_RU[month]}"
    if year:
        s += f" {year} года"
    return s


def age_if_known(person: dict) -> str:
    """Возраст или пусто, если год не указан."""
    if person["birth_year"] is None:
        return ""
    today = date.today()
    age = today.year - person["birth_year"]
    if (today.month, today.day) < (person["birth_month"], person["birth_day"]):
        age -= 1
    return f" (сейчас {age})"


def person_card(person: dict) -> str:
    lines = [
        f"👤 *{person['name']}*",
        f"📅 {fmt_date(person['birth_day'], person['birth_month'], person['birth_year'])}"
        + age_if_known(person),
    ]
    return "\n".join(lines)


def person_card_kb(person_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Изменить", callback_data=f"edit:{person_id}"),
         InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete:{person_id}")],
        [InlineKeyboardButton(text="＋ Идея подарка", callback_data=f"addwish:{person_id}"),
         InlineKeyboardButton(text="💡 Идеи", callback_data=f"wishes:{person_id}")],
        [InlineKeyboardButton(text="« Назад", callback_data="back:list")],
    ])


def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="« К списку", callback_data="back:list")],
    ])


# --- /start, /help, /cancel ---

@dp.message(CommandStart())
async def cmd_start(message: Message):
    await db.ensure_user(message.chat.id)
    text = (
        "Привет! Я напоминаю о днях рождения 🎂\n\n"
        "*Как добавить человека:*\n"
        "Просто напиши `Мама 15.03.1990` — или без года: `Мама 15 марта`\n\n"
        "*Команды:*\n"
        "/add — добавить\n"
        "/list — все люди\n"
        "/today — чьи ДР сегодня\n"
        "/upcoming — ближайшие ДР\n"
        "/settings — часовой пояс и время уведомления\n"
        "/help — справка"
    )
    await message.answer(text, parse_mode="Markdown")


@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "Напиши `Имя дата` — например `Мама 15.03.1990` или `Папа 20 мая`.\n"
        "Год — по желанию (нужен для возраста и юбилеев).\n\n"
        "Команды: /add /list /today /upcoming /settings",
        parse_mode="Markdown",
    )


@dp.message(Command("cancel"))
@dp.message(StateFilter(AddPerson.waiting_input, EditPerson.waiting_input,
                        AddWish.waiting_text, Settings.waiting_tz, Settings.waiting_time))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.")


# --- Добавление человека ---

async def _do_add(message: Message, state: FSMContext, text: str):
    parsed = parse_birthday(text)
    if not parsed:
        await message.answer(
            "Не понял. Пример: `Мама 15.03.1990` или `Мама 15 марта` (год — по желанию).",
            parse_mode="Markdown",
        )
        return
    name, day, month, year = parsed
    await db.ensure_user(message.chat.id)
    await db.add_person(message.chat.id, name, day, month, year)
    await state.clear()
    await message.answer(
        f"✅ Записал: *{name}* — {fmt_date(day, month, year)}",
        parse_mode="Markdown",
    )


@dp.message(Command("add"))
async def cmd_add(message: Message, state: FSMContext):
    await state.set_state(AddPerson.waiting_input)
    await message.answer(
        "Введи `Имя дата`. Например: `Мама 15.03.1990` или `Папа 20 мая`",
        parse_mode="Markdown",
    )


@dp.message(AddPerson.waiting_input)
async def add_person_input(message: Message, state: FSMContext):
    await _do_add(message, state, message.text)


@dp.message(StateFilter(default_state), F.text & ~F.text.startswith("/"))
async def quick_add(message: Message, state: FSMContext):
    await _do_add(message, state, message.text)


# --- Просмотр: /list, /today, /upcoming ---

@dp.message(Command("list"))
async def cmd_list(message: Message):
    people = await db.list_people(message.chat.id)
    if not people:
        await message.answer("Список пуст. Добавь: `Мама 15.03.1990`", parse_mode="Markdown")
        return
    today = date.today()
    people_sorted = sorted(people, key=lambda p: scheduler.next_birthday(p, today))
    buttons = [
        [InlineKeyboardButton(
            text=f"{p['name']} — {fmt_date(p['birth_day'], p['birth_month'], None)}",
            callback_data=f"person:{p['id']}",
        )] for p in people_sorted
    ]
    await message.answer(
        "*Твои люди:* (ближайшие сверху)", parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@dp.message(Command("today"))
async def cmd_today(message: Message):
    people = await db.list_people(message.chat.id)
    today = date.today()
    found = [p for p in people
             if (p["birth_day"], p["birth_month"]) == (today.day, today.month)]
    # 29.02 в невисокосный — 28.02
    from calendar import isleap
    if today.month == 2 and today.day == 28 and not isleap(today.year):
        found = [p for p in people if p["birth_day"] == 29 and p["birth_month"] == 2]
    if not found:
        await message.answer("Сегодня ни у кого нет дня рождения.")
        return
    lines = ["*Сегодня день рождения:*\n"]
    for p in found:
        lines.append(f"🎂 {p['name']} — {fmt_date(p['birth_day'], p['birth_month'], p['birth_year'])}{age_if_known(p)}")
    await message.answer("\n".join(lines), parse_mode="Markdown")


@dp.message(Command("upcoming"))
async def cmd_upcoming(message: Message):
    people = await db.list_people(message.chat.id)
    if not people:
        await message.answer("Список пуст. Добавь: `Мама 15.03.1990`", parse_mode="Markdown")
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
    lines = ["*Ближайшие дни рождения:*\n"]
    for nb, p in upcoming:
        days = (nb - today).days
        when = "сегодня" if days == 0 else ("завтра" if days == 1 else f"через {days} дн.")
        lines.append(f"• {p['name']} — {fmt_date(p['birth_day'], p['birth_month'], p['birth_year'])} ({when})")
    await message.answer("\n".join(lines), parse_mode="Markdown")


# --- Карточка человека ---

@dp.callback_query(F.data.startswith("person:"))
async def cb_person(callback: CallbackQuery):
    person_id = int(callback.data.split(":", 1)[1])
    person = await db.get_person(person_id)
    if not person:
        await callback.answer("Не найдено")
        await callback.message.answer("Человек не найден.")
        return
    await callback.message.edit_text(
        person_card(person), parse_mode="Markdown",
        reply_markup=person_card_kb(person_id),
    )
    await callback.answer()


@dp.callback_query(F.data == "back:list")
async def cb_back_list(callback: CallbackQuery):
    # Перерисуем список там же, где были кнопки.
    people = await db.list_people(callback.message.chat.id)
    if not people:
        await callback.message.edit_text("Список пуст.")
        await callback.answer()
        return
    today = date.today()
    people_sorted = sorted(people, key=lambda p: scheduler.next_birthday(p, today))
    buttons = [
        [InlineKeyboardButton(
            text=f"{p['name']} — {fmt_date(p['birth_day'], p['birth_month'], None)}",
            callback_data=f"person:{p['id']}",
        )] for p in people_sorted
    ]
    await callback.message.edit_text(
        "*Твои люди:* (ближайшие сверху)", parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await callback.answer()


# --- Редактирование ---

@dp.callback_query(F.data.startswith("edit:"))
async def cb_edit_start(callback: CallbackQuery, state: FSMContext):
    person_id = int(callback.data.split(":", 1)[1])
    await state.set_state(EditPerson.waiting_input)
    await state.update_data(person_id=person_id)
    await callback.message.answer(
        "Введи заново в формате `Имя дата` (старое заменится):",
        parse_mode="Markdown",
    )
    await callback.answer()


@dp.message(EditPerson.waiting_input)
async def edit_person_input(message: Message, state: FSMContext):
    parsed = parse_birthday(message.text)
    if not parsed:
        await message.answer(
            "Не понял. Пример: `Мама 15.03.1990` или `Мама 15 марта`.\n/cancel — отмена.",
            parse_mode="Markdown",
        )
        return
    name, day, month, year = parsed
    data = await state.get_data()
    person_id = data["person_id"]
    await db.update_person(
        person_id, name=name, birth_day=day, birth_month=month, birth_year=year
    )
    await state.clear()
    person = await db.get_person(person_id)
    await message.answer(
        f"✅ Обновил: *{name}* — {fmt_date(day, month, year)}",
        parse_mode="Markdown",
        reply_markup=back_kb(),
    )


# --- Удаление ---

@dp.callback_query(F.data.startswith("delete:"))
async def cb_delete_start(callback: CallbackQuery, state: FSMContext):
    person_id = int(callback.data.split(":", 1)[1])
    person = await db.get_person(person_id)
    if not person:
        await callback.answer("Не найдено")
        return
    await state.update_data(person_id=person_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Да, удалить", callback_data=f"delconfirm:{person_id}")],
        [InlineKeyboardButton(text="« Отмена", callback_data=f"person:{person_id}")],
    ])
    await callback.message.edit_text(
        f"Удалить *{person['name']}*?", parse_mode="Markdown", reply_markup=kb,
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("delconfirm:"))
async def cb_delete_confirm(callback: CallbackQuery, state: FSMContext):
    person_id = int(callback.data.split(":", 1)[1])
    await db.delete_person(person_id)
    await state.clear()
    await callback.message.edit_text("🗑 Удалено.")
    await callback.answer()


# --- Wishlist ---

@dp.callback_query(F.data.startswith("addwish:"))
async def cb_addwish_start(callback: CallbackQuery, state: FSMContext):
    person_id = int(callback.data.split(":", 1)[1])
    await state.set_state(AddWish.waiting_text)
    await state.update_data(person_id=person_id)
    await callback.message.answer("Введи идею подарка:")
    await callback.answer()


@dp.message(AddWish.waiting_text)
async def addwish_input(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text:
        await message.answer("Пусто. Попробуй ещё или /cancel.")
        return
    data = await state.get_data()
    person_id = data["person_id"]
    await db.add_wish(person_id, text)
    await state.clear()
    await message.answer("✅ Идея добавлена.", reply_markup=back_kb())


@dp.callback_query(F.data.startswith("wishes:"))
async def cb_wishes(callback: CallbackQuery):
    person_id = int(callback.data.split(":", 1)[1])
    wishes = await db.list_wishes(person_id)
    if not wishes:
        await callback.message.edit_text(
            "Идей пока нет. Нажми «＋ Идея подарка» в карточке.",
            reply_markup=back_kb(),
        )
        await callback.answer()
        return
    buttons = [
        [InlineKeyboardButton(text=f"🗑 {w['text'][:40]}", callback_data=f"delwish:{w['id']}")]
        for w in wishes
    ]
    buttons.append([InlineKeyboardButton(text="« Назад", callback_data=f"person:{person_id}")])
    await callback.message.edit_text(
        "*Идеи подарков:*", parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("delwish:"))
async def cb_delwish(callback: CallbackQuery):
    wish_id = int(callback.data.split(":", 1)[1])
    await db.delete_wish(wish_id)
    await callback.answer("Удалено")
    # Перерисуем список идей — но мы не знаем person_id без запроса. Просто вернём к карточке?
    # Проще: убрать сообщение и попросить открыть заново.
    await callback.message.edit_text("Удалено. Открой «💡 Идеи» снова, чтобы обновить список.")


# --- Настройки ---

@dp.message(Command("settings"))
async def cmd_settings(message: Message):
    u = await db.get_user(message.chat.id)
    if not u:
        await db.ensure_user(message.chat.id)
        u = await db.get_user(message.chat.id)
    buttons = [
        [InlineKeyboardButton(text=tz, callback_data=f"tz:{tz}")] for tz in POPULAR_TZS
    ]
    buttons.append([InlineKeyboardButton(text="✏️ Свой пояс", callback_data="tz:custom")])
    buttons.append([InlineKeyboardButton(text="🕐 Изменить время", callback_data="time:set")])
    await message.answer(
        f"Текущие настройки:\n"
        f"🌍 Пояс: {u['tz']}\n"
        f"🕐 Уведомление в {u['notify_hour']:02d}:{u['notify_minute']:02d}\n\n"
        "Часовой пояс:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@dp.callback_query(F.data.startswith("tz:"))
async def cb_tz(callback: CallbackQuery, state: FSMContext):
    value = callback.data.split(":", 1)[1]
    if value == "custom":
        await state.set_state(Settings.waiting_tz)
        await callback.message.answer(
            "Введи свой часовой пояс, например `Europe/Moscow` или `Asia/Almaty`.\n/cancel — отмена.",
            parse_mode="Markdown",
        )
        await callback.answer()
        return
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError:
        await callback.answer("Неизвестный пояс")
        return
    await db.update_tz(callback.message.chat.id, value)
    await callback.answer("Сохранено")
    await callback.message.answer(f"✅ Пояс: {value}")


@dp.message(Settings.waiting_tz)
async def settings_tz_input(message: Message, state: FSMContext):
    tz = message.text.strip()
    try:
        ZoneInfo(tz)
    except ZoneInfoNotFoundError:
        await message.answer("Не знаю такой пояс. Пример: `Europe/Moscow`. /cancel — отмена.",
                             parse_mode="Markdown")
        return
    await db.update_tz(message.chat.id, tz)
    await state.clear()
    await message.answer(f"✅ Пояс: {tz}")


@dp.callback_query(F.data == "time:set")
async def cb_time_set(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Settings.waiting_time)
    await callback.message.answer("Введи время уведомления, например `09:00`.")
    await callback.answer()


@dp.message(Settings.waiting_time)
async def settings_time_input(message: Message, state: FSMContext):
    text = message.text.strip().replace(".", ":")
    parts = text.split(":")
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        await message.answer("Не понял. Пример: `09:00`. /cancel — отмена.", parse_mode="Markdown")
        return
    h, m = int(parts[0]), int(parts[1])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        await message.answer("Часы 0–23, минуты 0–59. Попробуй ещё.")
        return
    await db.update_notify_time(message.chat.id, h, m)
    await state.clear()
    await message.answer(f"✅ Буду уведомлять в {h:02d}:{m:02d}")


# --- Запуск ---

async def main():
    await db.init_db()
    scheduler.start_scheduler(bot)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())