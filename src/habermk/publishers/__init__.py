"""Each publisher posts one approved item to one platform and returns the post id.

A publisher raises on failure; the caller isolates platforms from each other.
"""
from __future__ import annotations

import os
from typing import Any, Protocol


class Publisher(Protocol):
    name: str

    def post(self, item: dict[str, Any]) -> str: ...

    def delete(self, post_id: str) -> None:
        """Remove a post (takedown). Raises on failure."""
        ...

    def link(self, post_id: str) -> str | None:
        """Public web link to a post, if there is one."""
        ...


def from_env(cfg: dict[str, Any], env: dict[str, str] | None = None) -> list[Publisher]:
    """Every platform whose secrets are set is enabled."""
    from habermk.cards import card_maker

    env = dict(os.environ) if env is None else env
    pubs: list[Publisher] = []
    if env.get("TELEGRAM_BOT_TOKEN") and env.get("TELEGRAM_CHANNEL_ID"):
        from habermk.publishers.telegram import TelegramPublisher
        from habermk.telegram import TelegramAPI

        pubs.append(TelegramPublisher(TelegramAPI(env["TELEGRAM_BOT_TOKEN"]),
                                      env["TELEGRAM_CHANNEL_ID"],
                                      card=card_maker(cfg, "telegram")))
    if env.get("BLUESKY_HANDLE") and env.get("BLUESKY_APP_PASSWORD"):
        from habermk.publishers.bluesky import BlueskyPublisher

        pubs.append(BlueskyPublisher(env["BLUESKY_HANDLE"], env["BLUESKY_APP_PASSWORD"],
                                     card=card_maker(cfg, "bluesky")))
    if env.get("FB_PAGE_ID") and env.get("FB_PAGE_TOKEN"):
        from habermk.publishers.facebook import FacebookPublisher

        pubs.append(FacebookPublisher(env["FB_PAGE_ID"], env["FB_PAGE_TOKEN"],
                                      cfg["platforms"]["facebook_graph_version"]))
    return pubs
