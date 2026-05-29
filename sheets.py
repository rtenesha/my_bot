import requests
from datetime import datetime
from config import AIRTABLE_TOKEN, AIRTABLE_BASE_ID

BASE_URL = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}"

TABLE_TRANSACTIONS = "Транзакции"
TABLE_CATEGORIES = "Категории"
TABLE_BUDGET = "Бюджет"


def _headers():
    return {"Authorization": f"Bearer {AIRTABLE_TOKEN}"}


def _get_records(table: str) -> list[dict]:
    url = f"{BASE_URL}/{requests.utils.quote(table)}"
    records = []
    params = {}
    while True:
        r = requests.get(url, headers=_headers(), params=params)
        data = r.json()
        records.extend(data.get("records", []))
        offset = data.get("offset")
        if not offset:
            break
        params["offset"] = offset
    return records


def _create_record(table: str, fields: dict):
    url = f"{BASE_URL}/{requests.utils.quote(table)}"
    requests.post(url, headers=_headers(), json={"fields": fields})


def _update_record(table: str, record_id: str, fields: dict):
    url = f"{BASE_URL}/{requests.utils.quote(table)}/{record_id}"
    requests.patch(url, headers=_headers(), json={"fields": fields})


def _delete_record(table: str, record_id: str):
    url = f"{BASE_URL}/{requests.utils.quote(table)}/{record_id}"
    requests.delete(url, headers=_headers())


# --- Категории ---

def get_categories() -> list[str]:
    records = _get_records(TABLE_CATEGORIES)
    return [r["fields"].get("Категория", "") for r in records if r["fields"].get("Категория")]


def add_category(name: str) -> bool:
    existing = [c.lower() for c in get_categories()]
    if name.lower() in existing:
        return False
    _create_record(TABLE_CATEGORIES, {"Категория": name})
    return True


def delete_category(name: str) -> bool:
    records = _get_records(TABLE_CATEGORIES)
    for r in records:
        if r["fields"].get("Категория", "").lower() == name.lower():
            _delete_record(TABLE_CATEGORIES, r["id"])
            return True
    return False


# --- Бюджет ---

def get_budgets() -> dict[str, float]:
    records = _get_records(TABLE_BUDGET)
    result = {}
    for r in records:
        cat = r["fields"].get("Категория", "")
        limit = r["fields"].get("Лимит")
        if cat and limit is not None:
            result[cat] = float(limit)
    return result


def set_budget(category: str, limit: float):
    records = _get_records(TABLE_BUDGET)
    for r in records:
        if r["fields"].get("Категория", "").lower() == category.lower():
            _update_record(TABLE_BUDGET, r["id"], {"Лимит": limit})
            return
    _create_record(TABLE_BUDGET, {"Категория": category, "Лимит": limit})


# --- Транзакции ---

def add_transaction(tx_type: str, amount: float, category: str, description: str):
    now = datetime.now()
    _create_record(TABLE_TRANSACTIONS, {
        "Дата": now.strftime("%d.%m.%Y"),
        "Время": now.strftime("%H:%M"),
        "Тип": tx_type,
        "Сумма": amount,
        "Категория": category,
        "Описание": description,
    })


def get_transactions_this_month() -> list[dict]:
    current_month = datetime.now().strftime("%m.%Y")
    records = _get_records(TABLE_TRANSACTIONS)
    result = []
    for r in records:
        f = r["fields"]
        if f.get("Дата", "").endswith(current_month):
            try:
                result.append({
                    "date": f.get("Дата", ""),
                    "time": f.get("Время", ""),
                    "type": f.get("Тип", ""),
                    "amount": float(f.get("Сумма", 0)),
                    "category": f.get("Категория", ""),
                    "description": f.get("Описание", ""),
                })
            except (ValueError, TypeError):
                pass
    return result


def get_transactions_today() -> list[dict]:
    today = datetime.now().strftime("%d.%m.%Y")
    records = _get_records(TABLE_TRANSACTIONS)
    result = []
    for r in records:
        f = r["fields"]
        if f.get("Дата") == today:
            try:
                result.append({
                    "date": f.get("Дата", ""),
                    "time": f.get("Время", ""),
                    "type": f.get("Тип", ""),
                    "amount": float(f.get("Сумма", 0)),
                    "category": f.get("Категория", ""),
                    "description": f.get("Описание", ""),
                })
            except (ValueError, TypeError):
                pass
    return result


def get_monthly_spent_by_category() -> dict[str, float]:
    result: dict[str, float] = {}
    for tx in get_transactions_this_month():
        if tx["type"] == "расход":
            result[tx["category"]] = result.get(tx["category"], 0) + tx["amount"]
    return result
