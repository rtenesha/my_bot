from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import aiosqlite

from config import DB_PATH


@asynccontextmanager
async def _connect():
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = aiosqlite.Row
        yield conn

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    chat_id        INTEGER PRIMARY KEY,
    tz             TEXT NOT NULL DEFAULT 'Europe/Moscow',
    notify_hour    INTEGER NOT NULL DEFAULT 9,
    notify_minute  INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS people (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_chat_id  INTEGER NOT NULL REFERENCES users(chat_id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    birth_day     INTEGER NOT NULL,
    birth_month   INTEGER NOT NULL,
    birth_year    INTEGER,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_people_user_date
    ON people(user_chat_id, birth_month, birth_day);
CREATE TABLE IF NOT EXISTS wishes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id   INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    text        TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS sent_reminders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id   INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    event_date  TEXT NOT NULL,
    sent_at     TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(person_id, event_date)
);
"""

# Сигнал «поле не передано» для update_person (отличимо от None = «обнулить»).
_UNSET = object()


async def init_db() -> None:
    async with _connect() as conn:
        await conn.executescript(_SCHEMA)
        await conn.commit()


async def list_tables() -> list[str]:
    async with _connect() as conn:
        cur = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        rows = await cur.fetchall()
        return [r["name"] for r in rows]


# --- users ---

async def ensure_user(chat_id: int) -> bool:
    """Создаёт пользователя с дефолтами, если его ещё нет. True — создан."""
    from config import DEFAULT_NOTIFY_HOUR, DEFAULT_NOTIFY_MINUTE, DEFAULT_TZ

    async with _connect() as conn:
        cur = await conn.execute("SELECT 1 FROM users WHERE chat_id = ?", (chat_id,))
        if await cur.fetchone():
            return False
        await conn.execute(
            "INSERT INTO users (chat_id, tz, notify_hour, notify_minute) VALUES (?, ?, ?, ?)",
            (chat_id, DEFAULT_TZ, DEFAULT_NOTIFY_HOUR, DEFAULT_NOTIFY_MINUTE),
        )
        await conn.commit()
        return True


async def get_user(chat_id: int) -> dict[str, Any] | None:
    async with _connect() as conn:
        cur = await conn.execute("SELECT * FROM users WHERE chat_id = ?", (chat_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def all_users() -> list[dict[str, Any]]:
    async with _connect() as conn:
        cur = await conn.execute("SELECT * FROM users")
        return [dict(r) for r in await cur.fetchall()]


async def update_tz(chat_id: int, tz: str) -> None:
    async with _connect() as conn:
        await conn.execute("UPDATE users SET tz = ? WHERE chat_id = ?", (tz, chat_id))
        await conn.commit()


async def update_notify_time(chat_id: int, hour: int, minute: int) -> None:
    async with _connect() as conn:
        await conn.execute(
            "UPDATE users SET notify_hour = ?, notify_minute = ? WHERE chat_id = ?",
            (hour, minute, chat_id),
        )
        await conn.commit()


# --- people ---

async def add_person(
    chat_id: int, name: str, day: int, month: int, year: int | None
) -> int:
    async with _connect() as conn:
        cur = await conn.execute(
            "INSERT INTO people (user_chat_id, name, birth_day, birth_month, birth_year) "
            "VALUES (?, ?, ?, ?, ?)",
            (chat_id, name, day, month, year),
        )
        await conn.commit()
        return cur.lastrowid


async def get_person(person_id: int) -> dict[str, Any] | None:
    async with _connect() as conn:
        cur = await conn.execute("SELECT * FROM people WHERE id = ?", (person_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def list_people(chat_id: int) -> list[dict[str, Any]]:
    async with _connect() as conn:
        cur = await conn.execute(
            "SELECT * FROM people WHERE user_chat_id = ? ORDER BY created_at",
            (chat_id,),
        )
        return [dict(r) for r in await cur.fetchall()]


async def update_person(
    person_id: int,
    name: str = _UNSET,
    birth_day: int = _UNSET,
    birth_month: int = _UNSET,
    birth_year: int | None = _UNSET,
) -> None:
    fields: list[str] = []
    params: list[Any] = []
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
    async with _connect() as conn:
        await conn.execute(
            f"UPDATE people SET {', '.join(fields)} WHERE id = ?", params
        )
        await conn.commit()


async def delete_person(person_id: int) -> None:
    async with _connect() as conn:
        await conn.execute("DELETE FROM people WHERE id = ?", (person_id,))
        await conn.commit()


async def get_people_with_birthday_on(
    chat_id: int, day: int, month: int
) -> list[dict[str, Any]]:
    async with _connect() as conn:
        cur = await conn.execute(
            "SELECT * FROM people WHERE user_chat_id = ? AND birth_day = ? AND birth_month = ?",
            (chat_id, day, month),
        )
        return [dict(r) for r in await cur.fetchall()]


# --- wishes ---

async def add_wish(person_id: int, text: str) -> int:
    async with _connect() as conn:
        cur = await conn.execute(
            "INSERT INTO wishes (person_id, text) VALUES (?, ?)", (person_id, text)
        )
        await conn.commit()
        return cur.lastrowid


async def list_wishes(person_id: int) -> list[dict[str, Any]]:
    async with _connect() as conn:
        cur = await conn.execute(
            "SELECT * FROM wishes WHERE person_id = ? ORDER BY id", (person_id,)
        )
        return [dict(r) for r in await cur.fetchall()]


async def delete_wish(wish_id: int) -> None:
    async with _connect() as conn:
        await conn.execute("DELETE FROM wishes WHERE id = ?", (wish_id,))
        await conn.commit()


# --- sent reminders ---

async def already_sent(person_id: int, event_date: str) -> bool:
    async with _connect() as conn:
        cur = await conn.execute(
            "SELECT 1 FROM sent_reminders WHERE person_id = ? AND event_date = ?",
            (person_id, event_date),
        )
        return await cur.fetchone() is not None


async def mark_sent(person_id: int, event_date: str) -> None:
    async with _connect() as conn:
        await conn.execute(
            "INSERT INTO sent_reminders (person_id, event_date) VALUES (?, ?)",
            (person_id, event_date),
        )
        await conn.commit()