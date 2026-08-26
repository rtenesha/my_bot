from __future__ import annotations

import json
import logging
import os
import sys

# Vercel запускает функцию из api/, но модули бота (bot/db/config) лежат в
# корне проекта — добавляем корень в sys.path, чтобы их импорты работали.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aiogram import Bot

import bot as bot_module  # импорт регистрирует хендлеры в dp
import db
from config import BOT_TOKEN

logging.basicConfig(level=logging.INFO)

_initialized = False


def _ensure_schema() -> None:
    global _initialized
    if not _initialized:
        db.init_db()
        _initialized = True


async def _process(payload: dict) -> None:
    bot = Bot(token=BOT_TOKEN)
    try:
        await bot_module.dp.feed_webhook_update(bot, payload)
    finally:
        await bot.session.close()


async def _read_body(receive) -> bytes:
    body = b""
    more = True
    while more:
        message = await receive()
        body += message.get("body", b"")
        more = message.get("more_body", False)
    return body


async def _send_text(send, status: int, text: bytes) -> None:
    headers = [(b"content-type", b"text/plain; charset=utf-8")]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": text})


async def app(scope, receive, send):
    """ASGI-функция: принимает Telegram-вебхук.

    Любой POST на этот URL трактуется как апдейт от Telegram и скармливается
    в aiogram Dispatcher. Всегда отвечаем 200, чтобы Telegram не спамил
    ретраями (ошибки логируем, но маскируем).
    """
    if scope.get("type") != "http":
        return

    method = scope.get("method", "")
    if method == "GET":
        await _send_text(send, 200, b"ok")
        return
    if method != "POST":
        await _send_text(send, 405, b"method not allowed")
        return

    body = await _read_body(receive)
    try:
        payload = json.loads(body)
    except (ValueError, json.JSONDecodeError):
        await _send_text(send, 400, b"bad json")
        return

    _ensure_schema()
    try:
        await _process(payload)
    except Exception:  # noqa: BLE001
        logging.exception("webhook processing error")

    await _send_text(send, 200, b"ok")