from __future__ import annotations

from typing import Any, Callable

from habermk.formatting import telegram_text
from habermk.telegram import TelegramAPI

CAPTION_LIMIT = 1024  # Telegram's limit for photo captions


class TelegramPublisher:
    name = "telegram"

    def __init__(self, api: TelegramAPI, channel_id: str,
                 card: Callable[[dict], bytes] | None = None):
        self.api = api
        self.channel_id = channel_id
        self.card = card

    def post(self, item: dict[str, Any]) -> str:
        text = telegram_text(item["sentence"], item["outlet"], item["url"])
        if self.card and len(text) <= CAPTION_LIMIT:
            msg = self.api.send_photo(self.channel_id, self.card(item), caption=text)
        else:
            msg = self.api.send_message(
                self.channel_id, text,
                link_preview_options={"url": item["url"], "prefer_small_media": True},
            )
        return str(msg["message_id"])
