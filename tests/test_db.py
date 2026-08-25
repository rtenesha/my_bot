from __future__ import annotations

import pytest

import db


def test_init_db_creates_tables(db_path):
    db.init_db()
    assert set(db.list_tables()) == {
        "users", "people", "wishes", "sent_reminders", "pending_actions"
    }


def test_ensure_user_creates_with_defaults(db_ready):
    assert db.ensure_user(100) is True
    u = db.get_user(100)
    assert u["chat_id"] == 100
    assert u["tz"] == "Europe/Moscow"
    assert u["notify_hour"] == 9
    assert u["notify_minute"] == 0


def test_ensure_user_idempotent(db_ready):
    db.ensure_user(100)
    assert db.ensure_user(100) is False


def test_add_and_get_person(db_ready):
    db.ensure_user(100)
    pid = db.add_person(100, "Мама", 15, 3, 1990)
    person = db.get_person(pid)
    assert person["name"] == "Мама"
    assert person["birth_day"] == 15
    assert person["birth_month"] == 3
    assert person["birth_year"] == 1990
    assert person["user_chat_id"] == 100


def test_add_person_without_year(db_ready):
    db.ensure_user(100)
    pid = db.add_person(100, "Коля", 29, 2, None)
    assert db.get_person(pid)["birth_year"] is None


def test_list_people_isolated_per_user(db_ready):
    db.ensure_user(100)
    db.ensure_user(200)
    db.add_person(100, "Мама", 15, 3, 1990)
    db.add_person(200, "Чужая мама", 15, 3, 1990)
    assert len(db.list_people(100)) == 1
    assert len(db.list_people(200)) == 1


def test_delete_person_cascades(db_ready):
    db.ensure_user(100)
    pid = db.add_person(100, "Мама", 15, 3, 1990)
    db.add_wish(pid, "цветы")
    db.mark_sent(pid, "2026-03-15")
    db.delete_person(pid)

    assert db.get_person(pid) is None
    assert db.list_wishes(pid) == []
    assert db.already_sent(pid, "2026-03-15") is False


def test_wishes_crud(db_ready):
    db.ensure_user(100)
    pid = db.add_person(100, "Мама", 15, 3, 1990)
    wid = db.add_wish(pid, "цветы")
    db.add_wish(pid, "билет в театр")
    assert len(db.list_wishes(pid)) == 2
    db.delete_wish(wid)
    wishes = db.list_wishes(pid)
    assert len(wishes) == 1
    assert wishes[0]["text"] == "билет в театр"


def test_get_people_with_birthday_on(db_ready):
    db.ensure_user(100)
    db.add_person(100, "Мама", 15, 3, 1990)
    db.add_person(100, "Папа", 1, 1, None)
    db.add_person(100, "Сестра", 15, 3, None)
    names = {p["name"] for p in db.get_people_with_birthday_on(100, 15, 3)}
    assert names == {"Мама", "Сестра"}


def test_already_sent_and_mark_sent(db_ready):
    db.ensure_user(100)
    pid = db.add_person(100, "Мама", 15, 3, 1990)
    assert db.already_sent(pid, "2026-03-15") is False
    db.mark_sent(pid, "2026-03-15")
    assert db.already_sent(pid, "2026-03-15") is True


def test_mark_sent_duplicate_raises_integrity_error(db_ready):
    db.ensure_user(100)
    pid = db.add_person(100, "Мама", 15, 3, 1990)
    db.mark_sent(pid, "2026-03-15")
    with pytest.raises(Exception):
        db.mark_sent(pid, "2026-03-15")


def test_update_tz_and_notify_time(db_ready):
    db.ensure_user(100)
    db.update_tz(100, "Asia/Vladivostok")
    db.update_notify_time(100, 10, 30)
    u = db.get_user(100)
    assert u["tz"] == "Asia/Vladivostok"
    assert u["notify_hour"] == 10
    assert u["notify_minute"] == 30


def test_all_users(db_ready):
    db.ensure_user(100)
    db.ensure_user(200)
    assert {u["chat_id"] for u in db.all_users()} == {100, 200}


def test_update_person(db_ready):
    db.ensure_user(100)
    pid = db.add_person(100, "Мама", 15, 3, 1990)
    db.update_person(pid, name="Мамуля", birth_year=1991)
    person = db.get_person(pid)
    assert person["name"] == "Мамуля"
    assert person["birth_year"] == 1991
    assert person["birth_day"] == 15


def test_pending_actions(db_ready):
    db.ensure_user(100)
    assert db.get_pending(100) is None
    db.set_pending(100, "edit", person_id=5)
    p = db.get_pending(100)
    assert p["action"] == "edit"
    assert p["person_id"] == 5
    # перезапись того же chat_id (UPSERT)
    db.set_pending(100, "addwish", person_id=7)
    assert db.get_pending(100)["action"] == "addwish"
    db.clear_pending(100)
    assert db.get_pending(100) is None


def test_clear_pending_on_delete_user_cascade(db_ready):
    db.ensure_user(100)
    db.set_pending(100, "edit", person_id=5)
    assert db.get_pending(100) is not None
    # удаляем пользователя — pending должен уйти каскадом
    with db._conn() as c:
        c.execute("DELETE FROM users WHERE chat_id = ?", (100,))
        c.commit()
    assert db.get_pending(100) is None