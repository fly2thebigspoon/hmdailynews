import os
import requests


def send(text: str):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    # Telegram 单条 4096 字符限制，超长自动分段
    for chunk in _split(text, 4000):
        r = requests.post(url, data={
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=15)
        r.raise_for_status()


def _split(text, size):
    return [text[i:i + size] for i in range(0, len(text), size)]
