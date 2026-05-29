import asyncio
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.state import default_state
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

import sheets
from config import BOT_TOKEN, BUDGET_WARN_PERCENT

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# --- FSM States ---

class AddCategory(StatesGroup):
    waiting_name = State()

class DeleteCategory(StatesGroup):
    waiting_name = State()

class SetBudget(StatesGroup):
    waiting_category = State()
    waiting_amount = State()

class AddTransaction(StatesGroup):
    waiting_category = State()
    # tx_type, amount, description хранятся в state data


# --- Helpers ---

def categories_keyboard(callback_prefix: str) -> InlineKeyboardMarkup:
    categories = sheets.get_categories()
    buttons = [
        [InlineKeyboardButton(text=cat, callback_data=f"{callback_prefix}:{cat}")]
        for cat in categories
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def format_money(amount: float) -> str:
    return f"{amount:,.0f}".replace(",", " ")


async def check_budget_alert(bot: Bot, chat_id: int, category: str):
    budgets = sheets.get_budgets()
    if category not in budgets:
        return
    limit = budgets[category]
    spent = sheets.get_monthly_spent_by_category().get(category, 0)
    percent = (spent / limit * 100) if limit > 0 else 0

    if percent >= 100:
        await bot.send_message(
            chat_id,
            f"🔴 Бюджет по категории *{category}* исчерпан!\n"
            f"Потрачено: {format_money(spent)} / {format_money(limit)} ₽",
            parse_mode="Markdown",
        )
    elif percent >= BUDGET_WARN_PERCENT:
        await bot.send_message(
            chat_id,
            f"⚠️ Использовано {percent:.0f}% бюджета по категории *{category}*\n"
            f"Потрачено: {format_money(spent)} / {format_money(limit)} ₽",
            parse_mode="Markdown",
        )


# --- /start ---

@dp.message(CommandStart())
async def cmd_start(message: Message):
    text = (
        "Привет! Я помогу вести учёт доходов и расходов.\n\n"
        "*Как добавить транзакцию:*\n"
        "• Расход: просто напиши `500 кофе`\n"
        "• Доход: напиши `+50000 зарплата`\n\n"
        "*Команды:*\n"
        "/categories — управление категориями\n"
        "/budget — установить бюджет\n"
        "/today — траты за сегодня\n"
        "/month — статистика за месяц\n"
    )
    await message.answer(text, parse_mode="Markdown")


# --- Парсинг транзакции из текста ---

def parse_transaction(text: str):
    """
    Возвращает (tx_type, amount, description) или None если не распознано.
    Форматы: '500 кофе', '+50000 зарплата', '-1200 продукты'
    """
    text = text.strip()
    tx_type = "расход"

    if text.startswith("+"):
        tx_type = "доход"
        text = text[1:].strip()
    elif text.startswith("-"):
        tx_type = "расход"
        text = text[1:].strip()

    parts = text.split(maxsplit=1)
    if not parts:
        return None
    try:
        amount = float(parts[0].replace(",", "."))
    except ValueError:
        return None

    description = parts[1].strip() if len(parts) > 1 else ""
    return tx_type, amount, description


@dp.message(StateFilter(default_state), F.text & ~F.text.startswith("/"))
async def handle_transaction(message: Message, state: FSMContext):
    parsed = parse_transaction(message.text)
    if not parsed:
        await message.answer(
            "Не понял. Пример: `500 кофе` или `+50000 зарплата`",
            parse_mode="Markdown",
        )
        return

    tx_type, amount, description = parsed
    categories = sheets.get_categories()

    if not categories:
        await message.answer(
            "Сначала добавь категории через /categories",
        )
        return

    await state.set_state(AddTransaction.waiting_category)
    await state.update_data(tx_type=tx_type, amount=amount, description=description)

    type_label = "Доход" if tx_type == "доход" else "Расход"
    await message.answer(
        f"{type_label}: *{format_money(amount)} ₽* — {description}\n\nВыбери категорию:",
        parse_mode="Markdown",
        reply_markup=categories_keyboard("tx_cat"),
    )


@dp.callback_query(AddTransaction.waiting_category, F.data.startswith("tx_cat:"))
async def transaction_category_chosen(callback: CallbackQuery, state: FSMContext):
    category = callback.data.split(":", 1)[1]
    data = await state.get_data()
    tx_type = data["tx_type"]
    amount = data["amount"]
    description = data["description"]

    sheets.add_transaction(tx_type, amount, category, description)
    await state.clear()

    type_label = "✅ Доход" if tx_type == "доход" else "✅ Расход"
    await callback.message.edit_text(
        f"{type_label} записан\n"
        f"*{format_money(amount)} ₽* · {category} · {description}",
        parse_mode="Markdown",
    )

    if tx_type == "расход":
        await check_budget_alert(callback.bot, callback.from_user.id, category)


# --- Категории ---

@dp.message(Command("categories"))
async def cmd_categories(message: Message):
    categories = sheets.get_categories()
    cat_list = "\n".join(f"• {c}" for c in categories) if categories else "Список пуст"
    await message.answer(
        f"*Категории:*\n{cat_list}\n\n"
        "Что сделать?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить", callback_data="cat_add")],
            [InlineKeyboardButton(text="🗑 Удалить", callback_data="cat_delete")],
        ]),
    )


@dp.callback_query(F.data == "cat_add")
async def cat_add_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AddCategory.waiting_name)
    await callback.message.answer("Введи название новой категории:")
    await callback.answer()


@dp.message(AddCategory.waiting_name)
async def cat_add_finish(message: Message, state: FSMContext):
    name = message.text.strip()
    added = sheets.add_category(name)
    await state.clear()
    if added:
        await message.answer(f"✅ Категория *{name}* добавлена", parse_mode="Markdown")
    else:
        await message.answer(f"Категория *{name}* уже существует", parse_mode="Markdown")


@dp.callback_query(F.data == "cat_delete")
async def cat_delete_start(callback: CallbackQuery, state: FSMContext):
    categories = sheets.get_categories()
    if not categories:
        await callback.answer("Нет категорий для удаления")
        return
    await state.set_state(DeleteCategory.waiting_name)
    await callback.message.answer(
        "Выбери категорию для удаления:",
        reply_markup=categories_keyboard("del_cat"),
    )
    await callback.answer()


@dp.callback_query(DeleteCategory.waiting_name, F.data.startswith("del_cat:"))
async def cat_delete_finish(callback: CallbackQuery, state: FSMContext):
    category = callback.data.split(":", 1)[1]
    sheets.delete_category(category)
    await state.clear()
    await callback.message.edit_text(f"🗑 Категория *{category}* удалена", parse_mode="Markdown")


# --- Бюджет ---

@dp.message(Command("budget"))
async def cmd_budget(message: Message):
    budgets = sheets.get_budgets()
    spent = sheets.get_monthly_spent_by_category()

    if not budgets:
        lines = ["Бюджет не установлен.\n"]
    else:
        lines = ["*Бюджет на этот месяц:*\n"]
        for cat, limit in budgets.items():
            s = spent.get(cat, 0)
            percent = (s / limit * 100) if limit > 0 else 0
            bar = "🟢" if percent < BUDGET_WARN_PERCENT else ("🟡" if percent < 100 else "🔴")
            lines.append(f"{bar} *{cat}*: {format_money(s)} / {format_money(limit)} ₽ ({percent:.0f}%)")

    await message.answer(
        "\n".join(lines) + "\n\nУстановить лимит для категории:",
        parse_mode="Markdown",
        reply_markup=categories_keyboard("budget_cat"),
    )


@dp.callback_query(F.data.startswith("budget_cat:"))
async def budget_category_chosen(callback: CallbackQuery, state: FSMContext):
    category = callback.data.split(":", 1)[1]
    await state.set_state(SetBudget.waiting_amount)
    await state.update_data(category=category)
    await callback.message.answer(
        f"Введи лимит расходов на месяц для категории *{category}* (в рублях):",
        parse_mode="Markdown",
    )
    await callback.answer()


@dp.message(SetBudget.waiting_amount)
async def budget_amount_set(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(" ", "").replace(",", "."))
    except ValueError:
        await message.answer("Введи число, например: `15000`", parse_mode="Markdown")
        return

    data = await state.get_data()
    category = data["category"]
    sheets.set_budget(category, amount)
    await state.clear()
    await message.answer(
        f"✅ Бюджет для *{category}*: {format_money(amount)} ₽/месяц",
        parse_mode="Markdown",
    )


# --- Статистика ---

@dp.message(Command("today"))
async def cmd_today(message: Message):
    txs = sheets.get_transactions_today()
    if not txs:
        await message.answer("Сегодня транзакций нет.")
        return

    expenses = [t for t in txs if t["type"] == "расход"]
    incomes = [t for t in txs if t["type"] == "доход"]

    lines = ["*Сегодня:*\n"]
    if incomes:
        lines.append("📥 *Доходы:*")
        for t in incomes:
            lines.append(f"  +{format_money(t['amount'])} ₽ · {t['category']} · {t['description']}")
    if expenses:
        lines.append("\n📤 *Расходы:*")
        for t in expenses:
            lines.append(f"  -{format_money(t['amount'])} ₽ · {t['category']} · {t['description']}")

    total_in = sum(t["amount"] for t in incomes)
    total_out = sum(t["amount"] for t in expenses)
    lines.append(f"\n💰 Итого: +{format_money(total_in)} / -{format_money(total_out)} ₽")

    await message.answer("\n".join(lines), parse_mode="Markdown")


@dp.message(Command("month"))
async def cmd_month(message: Message):
    txs = sheets.get_transactions_this_month()
    if not txs:
        await message.answer("В этом месяце транзакций нет.")
        return

    spent_by_cat: dict[str, float] = {}
    income_by_cat: dict[str, float] = {}

    for t in txs:
        if t["type"] == "расход":
            spent_by_cat[t["category"]] = spent_by_cat.get(t["category"], 0) + t["amount"]
        else:
            income_by_cat[t["category"]] = income_by_cat.get(t["category"], 0) + t["amount"]

    budgets = sheets.get_budgets()
    lines = ["*Статистика за месяц:*\n"]

    if income_by_cat:
        lines.append("📥 *Доходы:*")
        for cat, amt in sorted(income_by_cat.items(), key=lambda x: -x[1]):
            lines.append(f"  {cat}: +{format_money(amt)} ₽")

    if spent_by_cat:
        lines.append("\n📤 *Расходы:*")
        for cat, amt in sorted(spent_by_cat.items(), key=lambda x: -x[1]):
            limit = budgets.get(cat)
            if limit:
                percent = amt / limit * 100
                bar = "🟢" if percent < BUDGET_WARN_PERCENT else ("🟡" if percent < 100 else "🔴")
                lines.append(f"  {bar} {cat}: {format_money(amt)} / {format_money(limit)} ₽ ({percent:.0f}%)")
            else:
                lines.append(f"  • {cat}: {format_money(amt)} ₽")

    total_in = sum(t["amount"] for t in txs if t["type"] == "доход")
    total_out = sum(t["amount"] for t in txs if t["type"] == "расход")
    balance = total_in - total_out
    sign = "+" if balance >= 0 else ""
    lines.append(f"\n💰 Баланс: {sign}{format_money(balance)} ₽")

    await message.answer("\n".join(lines), parse_mode="Markdown")


# --- Запуск ---

async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
