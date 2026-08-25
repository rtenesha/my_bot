"""Разовая регистрация Telegram-вебхука на URL Vercel-функции.

Запуск:
    python set_webhook.py https://<your-app>.vercel.app/api/bot

Удаление вебхука (переход обратно на polling):
    python set_webhook.py delete
"""
from __future__ import annotations

import json
import sys
import urllib.request

from config import BOT_TOKEN

API = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python set_webhook.py https://<app>.vercel.app/api/bot")
        print("       python set_webhook.py delete")
        sys.exit(1)

    arg = sys.argv[1]
    if arg == "delete":
        data = json.dumps({"url": ""}).encode()
    else:
        data = json.dumps({"url": arg}).encode()

    req = urllib.request.Request(
        API, data=data, headers={"Content-Type": "application/json"}
    )
    print(urllib.request.urlopen(req).read().decode())


if __name__ == "__main__":
    main()