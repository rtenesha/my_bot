from __future__ import annotations

import pytest
import pytest_asyncio

import db


pytestmark = pytest.mark.asyncio


async def test_init_db_creates_tables(db_path):
    await db.init_db()
    tables = await db.list_tables()
    assert set(tables) == {"users", "people", "wishes", "sent_reminders"}


async def test_ensure_user_creates_with_defaults(db_ready):
    created = await db.ensure_user(100)
    assert created is True
    u = await db.get_user(100)
    assert u["chat_id"] == 100
    assert u["tz"] == "Europe/Moscow"
    assert u["notify_hour"] == 9
    assert u["notify_minute"] == 0


async def test_ensure_user_idempotent(db_ready):
    await db.ensure_user(100)
    created = await db.ensure_user(100)
    assert created is False


async def test_add_and_get_person(db_ready):
    await db.ensure_user(100)
    pid = await db.add_person(100, "Мама", 15, 3, 1990)
    person = await db.get_person(pid)
    assert person["name"] == "Мама"
    assert person["birth_day"] == 15
    assert person["birth_month"] == 3
    assert person["birth_year"] == 1990
    assert person["user_chat_id"] == 100


async def test_add_person_without_year(db_ready):
    await db.ensure_user(100)
    pid = await db.add_person(100, "Коля", 29, 2, None)
    person = await db.get_person(pid)
    assert person["birth_year"] is None


async def test_list_people(db_ready):
    await db.ensure_user(100)
    await db.add_person(100, "Мама", 15, 3, 1990)
    await db.add_person(100, "Папа", 1, 1, None)
    people = await db.list_people(100)
    assert len(people) == 2
    names = {p["name"] for p in people}
    assert names == {"Мама", "Папа"}


async def test_list_people_isolated_per_user(db_ready):
    await db.ensure_user(100)
    await db.ensure_user(200)
    await db.add_person(100, "Мама", 15, 3, 1990)
    await db.add_person(200, "Чужая мама", 15, 3, 1990)
    assert len(await db.list_people(100)) == 1
    assert len(await db.list_people(200)) == 1


async def test_delete_person_cascades_wishes_and_reminders(db_ready):
    await db.ensure_user(100)
    pid = await db.add_person(100, "Мама", 15, 3, 1990)
    await db.add_wish(pid, "цветы")
    await db.mark_sent(pid, "2026-03-15")
    await db.delete_person(pid)

    assert await db.get_person(pid) is None
    assert await db.list_wishes(pid) == []
    assert await db.already_sent(pid, "2026-03-15") is False


async def test_wishes_crud(db_ready):
    await db.ensure_user(100)
    pid = await db.add_person(100, "Мама", 15, 3, 1990)
    wid = await db.add_wish(pid, "цветы")
    await db.add_wish(pid, "билет в театр")
    wishes = await db.list_wishes(pid)
    assert len(wishes) == 2
    await db.delete_wish(wid)
    wishes = await db.list_wishes(pid)
    assert len(wishes) == 1
    assert wishes[0]["text"] == "билет в театр"


async def test_get_people_with_birthday_on(db_ready):
    await db.ensure_user(100)
    await db.add_person(100, "Мама", 15, 3, 1990)
    await db.add_person(100, "Папа", 1, 1, None)
    await db.add_person(100, "Сестра", 15, 3, None)
    found = await db.get_people_with_birthday_on(100, 15, 3)
    names = {p["name"] for p in found}
    assert names == {"Мама", "Сестра"}


async def test_already_sent_and_mark_sent(db_ready):
    await db.ensure_user(100)
    pid = await db.add_person(100, "Мама", 15, 3, 1990)
    assert await db.already_sent(pid, "2026-03-15") is False
    await db.mark_sent(pid, "2026-03-15")
    assert await db.already_sent(pid, "2026-03-15") is True


async def test_mark_sent_duplicate_raises_integrity_error(db_ready):
    """UNIQUE(person_id, event_date) — повторная вставка падает."""
    await db.ensure_user(100)
    pid = await db.add_person(100, "Мама", 15, 3, 1990)
    await db.mark_sent(pid, "2026-03-15")
    with pytest.raises(Exception):
        await db.mark_sent(pid, "2026-03-15")


async def test_update_tz(db_ready):
    await db.ensure_user(100)
    await db.update_tz(100, "Asia/Vladivostok")
    u = await db.get_user(100)
    assert u["tz"] == "Asia/Vladivostok"


async def test_update_notify_time(db_ready):
    await db.ensure_user(100)
    await db.update_notify_time(100, 10, 30)
    u = await db.get_user(100)
    assert u["notify_hour"] == 10
    assert u["notify_minute"] == 30


async def test_all_users(db_ready):
    await db.ensure_user(100)
    await db.ensure_user(200)
    users = await db.all_users()
    assert {u["chat_id"] for u in users} == {100, 200}


async def test_update_person(db_ready):
    await db.ensure_user(100)
    pid = await db.add_person(100, "Мама", 15, 3, 1990)
    await db.update_person(pid, name="Мамуля", birth_year=1991)
    person = await db.get_person(pid)
    assert person["name"] == "Мамуля"
    assert person["birth_year"] == 1991
    # неизменные поля сохранены
    assert person["birth_day"] == 15
    assert person["birth_month"] == 3