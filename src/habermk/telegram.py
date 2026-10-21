"""Minimal Telegram Bot API client (only the calls we use)."""
from __future__ import annotations

from typing import Any

import httpx


class TelegramError(RuntimeError):
    pass


class TelegramAPI:
    def __init__(self, token: str, client: httpx.Client | None = None):
        self._base = f"https://api.telegram.org/bot{token}/"
        self._client = client or httpx.Client(timeout=30)

    def call(self, method: str, **params: Any) -> Any:
        try:
            resp = self._client.post(self._base + method, json=params)
            data = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            # Never let the token (part of the URL) reach the logs.
            raise TelegramError(f"{method}: {type(e).__name__}") from None
        if not data.get("ok"):
            raise TelegramError(f"{method}: {data.get('description', resp.status_code)}")
        return data["result"]

    def send_message(self, chat_id: str | int, text: str, **params: Any) -> dict:
        return self.call("sendMessage", chat_id=chat_id, text=text, **params)
