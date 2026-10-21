from __future__ import annotations

from typing import Any

import httpx

from habermk.formatting import facebook_text


class FacebookError(RuntimeError):
    pass


class FacebookPublisher:
    """Posts to a Facebook Page through the Graph API with a Page access token."""

    name = "facebook"

    def __init__(self, page_id: str, page_token: str, version: str = "v26.0",
                 client: httpx.Client | None = None):
        self.page_id = page_id
        self._token = page_token
        self._base = f"https://graph.facebook.com/{version}/"
        self._client = client or httpx.Client(timeout=30)

    def post(self, item: dict[str, Any]) -> str:
        resp = self._client.post(
            f"{self._base}{self.page_id}/feed",
            data={"message": facebook_text(item["sentence"], item["outlet"]),
                  "link": item["url"], "access_token": self._token},
        )
        data = resp.json()
        if "id" not in data:
            raise FacebookError(self._error(data, resp.status_code))
        return data["id"]

    def delete(self, post_id: str) -> None:
        resp = self._client.delete(f"{self._base}{post_id}", params={"access_token": self._token})
        data = resp.json()
        if not data.get("success"):
            raise FacebookError(self._error(data, resp.status_code))

    def link(self, post_id: str) -> str | None:
        return f"https://www.facebook.com/{post_id}"

    @staticmethod
    def _error(data: dict, status: int) -> str:
        err = data.get("error", {})
        return f"{err.get('type', status)}: {err.get('message', '')}"
