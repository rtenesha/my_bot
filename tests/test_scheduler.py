from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError

import db
import scheduler


pytestmark = pytest.mark.asyncio


class FakeBot:
    def __init__(self, raise_exc=None):
        self.calls = []
        self.raise_exc = raise_exc

    async def send_message(self, chat_id, text, **kwargs):
        if self.raise_exc is not None:
            raise self.raise_exc
        self.calls.append({"chat_id": chat_id, "text": text})


def _make_user(chat_id=100, tz="UTC", notify=(0, 1)):
    db.ensure_user(chat_id)
    db.update_tz(chat_id, tz)
    db.update_notify_time(chat_id, notify[0], notify[1])
    return chat_id


UTC = timezone.utc


class TestEventDateFor:
    def test_normal(self):
        person = {"birth_day": 15, "birth_month": 3, "birth_year": 1990}
        assert scheduler.event_date_for(person, date(2026, 8, 1)) == date(2026, 3, 15)

    def test_leap_day_leap_year(self):
        person = {"birth_day": 29, "birth_month": 2, "birth_year": 2000}
        assert scheduler.event_date_for(person, date(2024, 1, 1)) == date(2024, 2, 29)

    def test_leap_day_non_leap_year(self):
        person = {"birth_day": 29, "birth_month": 2, "birth_year": 2000}
        assert scheduler.event_date_for(person, date(2026, 1, 1)) == date(2026, 2, 28)


class TestFormatMessage:
    person_no_year = {"name": "Мама", "birth_year": None}
    person_year = {"name": "Мама", "birth_year": 1990}
    person_jubilee = {"name": "Мама", "birth_year": 1976}

    def test_no_year(self):
        msg = scheduler.format_message(self.person_no_year, date(2026, 3, 15), [])
        assert msg == "🎂 Сегодня день рождения: Мама"

    def test_with_year(self):
        msg = scheduler.format_message(self.person_year, date(2026, 3, 15), [])
        assert msg == "🎂 Сегодня у Мама день рождения — исполняется 36!"

    def test_jubilee(self):
        msg = scheduler.format_message(self.person_jubilee, date(2026, 3, 15), [])
        assert msg == "🎂 Сегодня у Мама юбилей — исполняется 50! 🎉"

    def test_with_wishes(self):
        wishes = [{"text": "цветы"}, {"text": "билет в театр"}]
        msg = scheduler.format_message(self.person_year, date(2026, 3, 15), wishes)
        assert "💡 Идеи подарков:" in msg
        assert " • цветы" in msg
        assert " • билет в театр" in msg


class TestCheckAndSend:
    async def test_sends_for_birthday_today(self, db_ready):
        _make_user(chat_id=100, tz="UTC", notify=(0, 1))
        pid = db.add_person(100, "Мама", 25, 8, 1990)
        bot = FakeBot()

        await scheduler.check_and_send(bot, now_utc=datetime(2026, 8, 25, 9, 0, tzinfo=UTC))

        assert len(bot.calls) == 1
        assert bot.calls[0]["chat_id"] == 100
        assert "Мама" in bot.calls[0]["text"]
        assert db.already_sent(pid, "2026-08-25") is True

    async def test_no_send_before_notify_time(self, db_ready):
        _make_user(chat_id=100, tz="UTC", notify=(10, 0))
        pid = db.add_person(100, "Мама", 25, 8, 1990)
        bot = FakeBot()

        await scheduler.check_and_send(bot, now_utc=datetime(2026, 8, 25, 9, 0, tzinfo=UTC))

        assert bot.calls == []
        assert db.already_sent(pid, "2026-08-25") is False

    async def test_no_duplicate_on_second_run(self, db_ready):
        _make_user(chat_id=100, tz="UTC", notify=(0, 1))
        db.add_person(100, "Мама", 25, 8, 1990)
        bot = FakeBot()
        now = datetime(2026, 8, 25, 9, 0, tzinfo=UTC)

        await scheduler.check_and_send(bot, now_utc=now)
        await scheduler.check_and_send(bot, now_utc=now)

        assert len(bot.calls) == 1

    async def test_leap_day_non_leap_year_sends_on_feb28(self, db_ready):
        _make_user(chat_id=100, tz="UTC", notify=(0, 1))
        pid = db.add_person(100, "Коля", 29, 2, 2000)
        bot = FakeBot()

        await scheduler.check_and_send(bot, now_utc=datetime(2026, 2, 28, 9, 0, tzinfo=UTC))

        assert len(bot.calls) == 1
        assert db.already_sent(pid, "2026-02-28") is True

    async def test_leap_day_leap_year_sends_on_feb29(self, db_ready):
        _make_user(chat_id=100, tz="UTC", notify=(0, 1))
        pid = db.add_person(100, "Коля", 29, 2, 2000)
        bot = FakeBot()

        await scheduler.check_and_send(bot, now_utc=datetime(2024, 2, 29, 9, 0, tzinfo=UTC))

        assert len(bot.calls) == 1
        assert db.already_sent(pid, "2024-02-29") is True

    async def test_forbidden_marks_sent(self, db_ready):
        _make_user(chat_id=100, tz="UTC", notify=(0, 1))
        pid = db.add_person(100, "Мама", 25, 8, 1990)
        bot = FakeBot(raise_exc=TelegramForbiddenError(method="sendMessage", message="blocked"))

        await scheduler.check_and_send(bot, now_utc=datetime(2026, 8, 25, 9, 0, tzinfo=UTC))

        assert db.already_sent(pid, "2026-08-25") is True

    async def test_other_error_does_not_mark(self, db_ready):
        _make_user(chat_id=100, tz="UTC", notify=(0, 1))
        pid = db.add_person(100, "Мама", 25, 8, 1990)
        bot = FakeBot(raise_exc=TelegramAPIError(method="sendMessage", message="boom"))

        await scheduler.check_and_send(bot, now_utc=datetime(2026, 8, 25, 9, 0, tzinfo=UTC))

        assert db.already_sent(pid, "2026-08-25") is False

    async def test_timezone_moscow(self, db_ready):
        _make_user(chat_id=100, tz="Europe/Moscow", notify=(9, 0))
        db.add_person(100, "Мама", 25, 8, 1990)
        bot = FakeBot()

        # 25.08 06:00 UTC == 25.08 09:00 MSK
        await scheduler.check_and_send(bot, now_utc=datetime(2026, 8, 25, 6, 0, tzinfo=UTC))

        assert len(bot.calls) == 1

    async def test_multiple_users_isolated(self, db_ready):
        _make_user(chat_id=100, tz="UTC", notify=(0, 1))
        _make_user(chat_id=200, tz="UTC", notify=(0, 1))
        db.add_person(100, "Мама", 25, 8, 1990)
        db.add_person(200, "Папа", 25, 8, 1990)
        bot = FakeBot()

        await scheduler.check_and_send(bot, now_utc=datetime(2026, 8, 25, 9, 0, tzinfo=UTC))

        assert {c["chat_id"] for c in bot.calls} == {100, 200}