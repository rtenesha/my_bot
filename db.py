from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Any

from config import DEFAULT_NOTIFY_HOUR, DEFAULT_NOTIFY_MINUTE, DEFAULT_TZ
from config import TURSO_AUTH_TOKEN, TURSO_DATABASE_URL

# Схема — список отдельных операторов (исполняется по одному, работает
# одинаково и на stdlib sqlite3, и на libsql/Тurso).
_SCHEMA_STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS users (
        chat_id        INTEGER PRIMARY KEY,
        tz             TEXT NOT NULL DEFAULT 'Europe/Moscow',
        notify_hour    INTEGER NOT NULL DEFAULT 9,
        notify_minute  INTEGER NOT NULL DEFAULT 0,
        created_at     TEXT NOT NULL DEFAULT (datetime('now'))
    )""",
    """CREATE TABLE IF NOT EXISTS people (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        user_chat_id  INTEGER NOT NULL REFERENCES users(chat_id) ON DELETE CASCADE,
        name          TEXT NOT NULL,
        birth_day     INTEGER NOT NULL,
        birth_month   INTEGER NOT NULL,
        birth_year    INTEGER,
        created_at    TEXT NOT NULL DEFAULT (datetime('now'))
    )""",
    "CREATE INDEX IF NOT EXISTS idx_people_user_date "
    "ON people(user_chat_id, birth_month, birth_day)",
    """CREATE TABLE IF NOT EXISTS wishes (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        person_id   INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
        text        TEXT NOT NULL,
        created_at  TEXT NOT NULL DEFAULT (datetime('now'))
    )""",
    """CREATE TABLE IF NOT EXISTS sent_reminders (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        person_id   INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
        event_date  TEXT NOT NULL,
        sent_at     TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(person_id, event_date)
    )""",
    """CREATE TABLE IF NOT EXISTS pending_actions (
        chat_id    INTEGER PRIMARY KEY REFERENCES users(chat_id) ON DELETE CASCADE,
        action     TEXT NOT NULL,
        person_id  INTEGER,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""",
]


def _connect():
    """Открывает соединение. Локальный путь/файл — stdlib sqlite3;
    удалённая Turso-БД — libsql (один и тот же API)."""
    url = TURSO_DATABASE_URL
    if url and url.startswith(("http://", "https://", "libsql:")):
        import libsql  # отложенный импорт: локально/тестах пакет не нужен

        return libsql.connect(url, auth_token=TURSO_AUTH_TOKEN)
    path = url or "bot.db"
    if path.startswith("file:"):
        return sqlite3.connect(path)
    return sqlite3.connect(path)


@contextmanager
def _conn():
    c = _connect()
    c.execute("PRAGMA foreign_keys = ON")
    try:
        yield c
    finally:
        c.close()


def _fetchall_dicts(cur) -> list[dict[str, Any]]:
    cols = [d[0] for d in cur.description] if cur.description else []
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _fetchone_dict(cur) -> dict[str, Any] | None:
    cols = [d[0] for d in cur.description] if cur.description else []
    row = cur.fetchone()
    return dict(zip(cols, row)) if row else None


def init_db() -> None:
    with _conn() as c:
        for stmt in _SCHEMA_STATEMENTS:
            c.execute(stmt)
        c.commit()


def list_tables() -> list[str]:
    with _conn() as c:
        cur = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        return [r[0] for r in cur.fetchall()]


# --- users ---

def ensure_user(chat_id: int) -> bool:
    """Создаёт пользователя с дефолтами, если его ещё нет. True — создан."""
    with _conn() as c:
        if c.execute("SELECT 1 FROM users WHERE chat_id = ?", (chat_id,)).fetchone():
            return False
        c.execute(
            "INSERT INTO users (chat_id, tz, notify_hour, notify_minute) VALUES (?, ?, ?, ?)",
            (chat_id, DEFAULT_TZ, DEFAULT_NOTIFY_HOUR, DEFAULT_NOTIFY_MINUTE),
        )
        c.commit()
        return True


def get_user(chat_id: int) -> dict[str, Any] | None:
    with _conn() as c:
        return _fetchone_dict(c.execute("SELECT * FROM users WHERE chat_id = ?", (chat_id,)))


def all_users() -> list[dict[str, Any]]:
    with _conn() as c:
        return _fetchall_dicts(c.execute("SELECT * FROM users"))


def update_tz(chat_id: int, tz: str) -> None:
    with _conn() as c:
        c.execute("UPDATE users SET tz = ? WHERE chat_id = ?", (tz, chat_id))
        c.commit()


def update_notify_time(chat_id: int, hour: int, minute: int) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE users SET notify_hour = ?, notify_minute = ? WHERE chat_id = ?",
            (hour, minute, chat_id),
        )
        c.commit()


# --- people ---

def add_person(chat_id: int, name: str, day: int, month: int, year: int | None) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO people (user_chat_id, name, birth_day, birth_month, birth_year) "
            "VALUES (?, ?, ?, ?, ?)",
            (chat_id, name, day, month, year),
        )
        c.commit()
        return cur.lastrowid


def get_person(person_id: int) -> dict[str, Any] | None:
    with _conn() as c:
        return _fetchone_dict(c.execute("SELECT * FROM people WHERE id = ?", (person_id,)))


def list_people(chat_id: int) -> list[dict[str, Any]]:
    with _conn() as c:
        return _fetchall_dicts(
            c.execute("SELECT * FROM people WHERE user_chat_id = ? ORDER BY created_at", (chat_id,))
        )


_UNSET = object()


def update_person(
    person_id: int,
    name=_UNSET,
    birth_day=_UNSET,
    birth_month=_UNSET,
    birth_year=_UNSET,
) -> None:
    fields, params = [], []
    for col, val in (
        ("name", name),
        ("birth_day", birth_day),
        ("birth_month", birth_month),
        ("birth_year", birth_year),
    ):
        if val is not _UNSET:
            fields.append(f"{col} = ?")
            params.append(val)
    if not fields:
        return
    params.append(person_id)
    with _conn() as c:
        c.execute(f"UPDATE people SET {', '.join(fields)} WHERE id = ?", params)
        c.commit()


def delete_person(person_id: int) -> None:
    with _conn() as c:
        c.execute("DELETE FROM people WHERE id = ?", (person_id,))
        c.commit()


def get_people_with_birthday_on(
    chat_id: int, day: int, month: int
) -> list[dict[str, Any]]:
    with _conn() as c:
        return _fetchall_dicts(
            c.execute(
                "SELECT * FROM people WHERE user_chat_id = ? AND birth_day = ? AND birth_month = ?",
                (chat_id, day, month),
            )
        )


# --- wishes ---

def add_wish(person_id: int, text: str) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO wishes (person_id, text) VALUES (?, ?)", (person_id, text)
        )
        c.commit()
        return cur.lastrowid


def list_wishes(person_id: int) -> list[dict[str, Any]]:
    with _conn() as c:
        return _fetchall_dicts(
            c.execute("SELECT * FROM wishes WHERE person_id = ? ORDER BY id", (person_id,))
        )


def delete_wish(wish_id: int) -> None:
    with _conn() as c:
        c.execute("DELETE FROM wishes WHERE id = ?", (wish_id,))
        c.commit()


# --- sent reminders ---

def already_sent(person_id: int, event_date: str) -> bool:
    with _conn() as c:
        return c.execute(
            "SELECT 1 FROM sent_reminders WHERE person_id = ? AND event_date = ?",
            (person_id, event_date),
        ).fetchone() is not None


def mark_sent(person_id: int, event_date: str) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO sent_reminders (person_id, event_date) VALUES (?, ?)",
            (person_id, event_date),
        )
        c.commit()


# --- pending actions (замена FSM для serverless) ---

def set_pending(chat_id: int, action: str, person_id: int | None = None) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO pending_actions (chat_id, action, person_id) VALUES (?, ?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET action=excluded.action, person_id=excluded.person_id",
            (chat_id, action, person_id),
        )
        c.commit()


def get_pending(chat_id: int) -> dict[str, Any] | None:
    with _conn() as c:
        return _fetchone_dict(
            c.execute("SELECT * FROM pending_actions WHERE chat_id = ?", (chat_id,))
        )


def clear_pending(chat_id: int) -> None:
    with _conn() as c:
        c.execute("DELETE FROM pending_actions WHERE chat_id = ?", (chat_id,))
        c.commit()