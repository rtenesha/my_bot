from __future__ import annotations

import pytest

import bot as bot_module
import db


def _text_update(chat_id, text, update_id=1, message_id=10):
    return {
        "update_id": update_id,
        "message": {
            "message_id": message_id,
            "date": 1700000000,
            "chat": {"id": chat_id, "type": "private", "first_name": "U"},
            "from": {"id": chat_id, "is_bot": False, "first_name": "U"},
            "text": text,
        },
    }


def _callback_update(chat_id, data, message_id=10, update_id=2):
    return {
        "update_id": update_id,
        "callback_query": {
            "id": "cb",
            "from": {"id": chat_id, "is_bot": False, "first_name": "U"},
            "message": {
                "message_id": message_id,
                "date": 1700000000,
                "chat": {"id": chat_id, "type": "private", "first_name": "U"},
                "from": {"id": chat_id, "is_bot": False, "first_name": "U"},
                "text": "card",
            },
            "data": data,
            "chat_instance": "inst",
        },
    }


class FakeBot:
    id = 0

    def __init__(self):
        self.sent = []          # (chat_id, text)
        self.edited = []        # (chat_id, message_id, text)
        self.answers = []       # callback answers

    async def __call__(self, method):
        # aiogram вызывает bot(method); маршрутизируем по __api_method__.
        name = getattr(method, "__api_method__", "")
        if name == "sendMessage":
            self.sent.append((method.chat_id, method.text))
        elif name == "editMessageText":
            self.edited.append((method.chat_id, getattr(method, "message_id", None), method.text))
        elif name == "answerCallbackQuery":
            self.answers.append(getattr(method, "callback_query_id", None))
        return None


@pytest.fixture
def app(db_ready):
    return FakeBot()


async def _feed(fakebot, update):
    await bot_module.dp.feed_webhook_update(fakebot, update)


pytestmark = pytest.mark.asyncio


async def test_start_creates_user(app):
    await _feed(app, _text_update(100, "/start"))
    assert db.get_user(100) is not None
    assert any("Привет" in t for _, t in app.sent)


async def test_quick_add(app):
    await _feed(app, _text_update(100, "Мама 15.03.1990"))
    people = db.list_people(100)
    assert len(people) == 1
    assert people[0]["name"] == "Мама"
    assert people[0]["birth_year"] == 1990
    assert any("Записал" in t for _, t in app.sent)


async def test_add_via_command_then_text(app):
    await _feed(app, _text_update(100, "/add"))
    await _feed(app, _text_update(100, "Папа 20 мая", update_id=3, message_id=11))
    assert len(db.list_people(100)) == 1


async def test_invalid_input_no_crash(app):
    await _feed(app, _text_update(100, "абракадабра"))
    assert len(db.list_people(100)) == 0
    assert any("Не понял" in t for _, t in app.sent)


async def test_list_and_person_card(app):
    await _feed(app, _text_update(100, "Мама 15.03.1990"))
    await _feed(app, _text_update(100, "/list", update_id=3, message_id=11))
    # список отправлен (send_message с reply_markup) — карточку откроем колбэком
    people = db.list_people(100)
    pid = people[0]["id"]
    await _feed(app, _callback_update(100, f"person:{pid}", update_id=4))
    assert any(t and "Мама" in t for _, _, t in app.edited)


async def test_edit_flow(app):
    await _feed(app, _text_update(100, "Мама 15.03.1990"))
    pid = db.list_people(100)[0]["id"]
    # нажимаем «Изменить»
    await _feed(app, _callback_update(100, f"edit:{pid}", update_id=3))
    assert db.get_pending(100)["action"] == "edit"
    # вводим новые данные
    await _feed(app, _text_update(100, "Мамуля 1.1.1991", update_id=4, message_id=11))
    person = db.get_person(pid)
    assert person["name"] == "Мамуля"
    assert person["birth_year"] == 1991
    assert db.get_pending(100) is None


async def test_addwish_flow(app):
    await _feed(app, _text_update(100, "Мама 15.03.1990"))
    pid = db.list_people(100)[0]["id"]
    await _feed(app, _callback_update(100, f"addwish:{pid}", update_id=3))
    assert db.get_pending(100)["action"] == "addwish"
    await _feed(app, _text_update(100, "цветы", update_id=4, message_id=11))
    wishes = db.list_wishes(pid)
    assert len(wishes) == 1
    assert wishes[0]["text"] == "цветы"
    assert db.get_pending(100) is None


async def test_delete_flow(app):
    await _feed(app, _text_update(100, "Мама 15.03.1990"))
    pid = db.list_people(100)[0]["id"]
    await _feed(app, _callback_update(100, f"delete:{pid}", update_id=3))
    await _feed(app, _callback_update(100, f"delconfirm:{pid}", update_id=4))
    assert db.get_person(pid) is None


async def test_settings_tz_button(app):
    await _feed(app, _text_update(100, "/settings"))
    await _feed(app, _callback_update(100, "tz:Asia/Yekaterinburg", update_id=3))
    assert db.get_user(100)["tz"] == "Asia/Yekaterinburg"