from __future__ import annotations

from typing import Any

from habermk.formatting import bluesky_text


class BlueskyPublisher:
    """Posts the sentence with the article as a link card (the link is not counted
    in the 300-grapheme limit)."""

    name = "bluesky"

    def __init__(self, handle: str, app_password: str, client: Any = None):
        self.handle = handle
        self._password = app_password
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            from atproto import Client

            self._client = Client()
            self._client.login(self.handle, self._password)
        return self._client

    def find_existing(self, url: str) -> str | None:
        """Our post linking to `url` among the last 30, if any (crash safety)."""
        feed = self.client.get_author_feed(actor=self.handle, limit=30)
        for entry in feed.feed:
            embed = getattr(entry.post, "embed", None)
            external = getattr(embed, "external", None)
            if external is not None and getattr(external, "uri", None) == url:
                return entry.post.uri
        return None

    def post(self, item: dict[str, Any]) -> str:
        existing = self.find_existing(item["url"])
        if existing:
            return existing
        from atproto import models

        embed = models.AppBskyEmbedExternal.Main(
            external=models.AppBskyEmbedExternal.External(
                uri=item["url"], title=item["title"][:300], description=item["outlet"],
            )
        )
        resp = self.client.send_post(
            text=bluesky_text(item["sentence"], item["outlet"]), embed=embed, langs=["mk"],
        )
        return resp.uri
