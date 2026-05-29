from pyairtable import Api
from datetime import datetime
from config import AIRTABLE_TOKEN, AIRTABLE_BASE_ID

TABLE_TRANSACTIONS = "Транзакции"
TABLE_CATEGORIES = "Категории"
TABLE_BUDGET = "Бюджет"


def _api():
    return Api(AIRTABLE_TOKEN)


def _table(name: str):
    return _api().table(AIRTABLE_BASE_ID, name)


# --- Категории ---

def get_categories() -> list[str]:
    records = _table(TABLE_CATEGORIES).all()
    return [r["fields"].get("Категория", "") for r in records if r["fields"].get("Категория")]


def add_category(name: str) -> bool:
    existing = [c.lower() for c in get_categories()]
    if name.lower() in existing:
        return False
    _table(TABLE_CATEGORIES).create({"Категория": name})
    return True


def delete_category(name: str) -> bool:
    records = _table(TABLE_CATEGORIES).all()
    for r in records:
        if r["fields"].get("Категория", "").lower() == name.lower():
            _table(TABLE_CATEGORIES).delete(r["id"])
            return True
    return False


# --- Бюджет ---

def get_budgets() -> dict[str, float]:
    records = _table(TABLE_BUDGET).all()
    result = {}
    for r in records:
        cat = r["fields"].get("Категория", "")
        limit = r["fields"].get("Лимит")
        if cat and limit is not None:
            result[cat] = float(limit)
    return result


def set_budget(category: str, limit: float):
    records = _table(TABLE_BUDGET).all()
    for r in records:
        if r["fields"].get("Категория", "").lower() == category.lower():
            _table(TABLE_BUDGET).update(r["id"], {"Лимит": limit})
            return
    _table(TABLE_BUDGET).create({"Категория": category, "Лимит": limit})


# --- Транзакции ---

def add_transaction(tx_type: str, amount: float, category: str, description: str):
    now = datetime.now()
    _table(TABLE_TRANSACTIONS).create({
        "Дата": now.strftime("%d.%m.%Y"),
        "Время": now.strftime("%H:%M"),
        "Тип": tx_type,
        "Сумма": amount,
        "Категория": category,
        "Описание": description,
    })


def get_transactions_this_month() -> list[dict]:
    current_month = datetime.now().strftime("%m.%Y")
    records = _table(TABLE_TRANSACTIONS).all()
    result = []
    for r in records:
        f = r["fields"]
        if f.get("Дата", "").endswith(current_month):
            result.append({
                "date": f.get("Дата", ""),
                "time": f.get("Время", ""),
                "type": f.get("Тип", ""),
                "amount": float(f.get("Сумма", 0)),
                "category": f.get("Категория", ""),
                "description": f.get("Описание", ""),
            })
    return result


def get_transactions_today() -> list[dict]:
    today = datetime.now().strftime("%d.%m.%Y")
    records = _table(TABLE_TRANSACTIONS).all()
    result = []
    for r in records:
        f = r["fields"]
        if f.get("Дата") == today:
            result.append({
                "date": f.get("Дата", ""),
                "time": f.get("Время", ""),
                "type": f.get("Тип", ""),
                "amount": float(f.get("Сумма", 0)),
                "category": f.get("Категория", ""),
                "description": f.get("Описание", ""),
            })
    return result


def get_monthly_spent_by_category() -> dict[str, float]:
    result: dict[str, float] = {}
    for tx in get_transactions_this_month():
        if tx["type"] == "расход":
            result[tx["category"]] = result.get(tx["category"], 0) + tx["amount"]
    return result
