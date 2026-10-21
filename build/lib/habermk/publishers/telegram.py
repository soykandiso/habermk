from __future__ import annotations

from typing import Any

from habermk.formatting import telegram_text
from habermk.telegram import TelegramAPI


class TelegramPublisher:
    name = "telegram"

    def __init__(self, api: TelegramAPI, channel_id: str):
        self.api = api
        self.channel_id = channel_id

    def post(self, item: dict[str, Any]) -> str:
        msg = self.api.send_message(
            self.channel_id, telegram_text(item["sentence"], item["outlet"], item["url"]),
            link_preview_options={"url": item["url"], "prefer_small_media": True},
        )
        return str(msg["message_id"])
