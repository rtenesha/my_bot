from __future__ import annotations

import asyncio
import json
import logging
from http.server import BaseHTTPRequestHandler

from aiogram import Bot

import bot as bot_module  # импорт регистрирует хендлеры в dp
import db
from config import BOT_TOKEN

logging.basicConfig(level=logging.INFO)

_initialized = False


def _ensure_schema():
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


class handler(BaseHTTPRequestHandler):
    """Vercel file-based Python-функция: принимает Telegram-вебхук."""

    def do_GET(self):
        # health-check
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            payload = json.loads(body)
        except (ValueError, json.JSONDecodeError):
            self.send_response(400)
            self.end_headers()
            return

        _ensure_schema()
        try:
            asyncio.run(_process(payload))
        except Exception:  # noqa: BLE001 — всегда 200, чтобы Telegram не спамил ретраями
            logging.exception("webhook processing error")

        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):  # тишина стандартного лога HTTP-сервера
        pass