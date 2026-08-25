from __future__ import annotations

import re
from datetime import date

# Дата — хвост строки. Имя — всё, что левее совпадения.
# Числовой формат: 15.03, 15.03.1990, 15/03/1990 (год — только 4 цифры).
NUMERIC_RE = re.compile(r"(\d{1,2})[./](\d{1,2})(?:[./](\d{4}))?\s*$")
# Месяц словом: 15 марта, 15 марта 1990 (любой падеж по префиксу).
MONTH_WORD_RE = re.compile(r"(\d{1,2})\s+([а-яёА-ЯЁ]{3,})\s*(?:(\d{4}))?\s*$")

# Стебли месяцев (3 буквы), май обрабатываем отдельно — его стебль «ма»
# конфликтует с «мар» (март), поэтому для мая проверяем полные префиксы.
_STEMS = {
    "янв": 1, "фев": 2, "мар": 3, "апр": 4,
    "июн": 6, "июл": 7, "авг": 8, "сен": 9,
    "окт": 10, "ноя": 11, "дек": 12,
}

_MIN_YEAR = 1900


def _month_from_word(word: str) -> int | None:
    w = word.lower()
    if w.startswith(("май", "мая", "маю", "маем", "маями")):
        return 5
    for stem, num in _STEMS.items():
        if w.startswith(stem):
            return num
    return None


def _valid_date(day: int, month: int, year: int | None) -> bool:
    if not (1 <= day <= 31 and 1 <= month <= 12):
        return False
    # Проверяем реальную дату. Без года используем 2000 (високосный) —
    # чтобы 29.02 считался валидным, а 31.02 — нет.
    check_year = year if year is not None else 2000
    try:
        date(check_year, month, day)
    except ValueError:
        return False
    return True


def parse_birthday(text: str) -> tuple[str, int, int, int | None] | None:
    """
    Парсит «Имя дата» в (name, day, month, year_or_None).

    Поддерживаемые форматы даты (в конце строки):
        15.03, 15.03.1990, 15/03/1990, 15 марта, 15 марта 1990

    Год необязателен. Если указан — должен быть 4 цифры в диапазоне
    1900..текущий год. Имя — всё, что левее даты (может быть из нескольких слов).
    Возвращает None, если строку не удалось распознать.
    """
    text = text.strip()
    if not text:
        return None

    m = NUMERIC_RE.search(text)
    if m:
        name = text[: m.start()].strip()
        day = int(m.group(1))
        month = int(m.group(2))
        year = int(m.group(3)) if m.group(3) else None
    else:
        m = MONTH_WORD_RE.search(text)
        if not m:
            return None
        name = text[: m.start()].strip()
        day = int(m.group(1))
        month = _month_from_word(m.group(2))
        if month is None:
            return None
        year = int(m.group(3)) if m.group(3) else None

    if not name:
        return None

    if year is not None and not (_MIN_YEAR <= year <= date.today().year):
        return None

    if not _valid_date(day, month, year):
        return None

    return name, day, month, year