"""Test doubles: no network in tests."""
from __future__ import annotations

from typing import Any

from habermk.telegram import TelegramError


class FakeTelegram:
    def __init__(self, admin: str = "111"):
        self.admin = admin
        self.calls: list[tuple[str, dict]] = []
        self.updates: list[dict] = []
        self.fail: set[str] = set()
        self._next_id = 100

    def call(self, method: str, **params: Any) -> Any:
        self.calls.append((method, params))
        if method in self.fail:
            raise TelegramError(f"{method}: forced failure")
        if method == "getUpdates":
            ups = [u for u in self.updates if u["update_id"] >= params.get("offset", 0)]
            return ups
        if method in ("sendMessage", "sendPhoto"):
            self._next_id += 1
            return {"message_id": self._next_id}
        return True

    def send_message(self, chat_id, text, **params):
        return self.call("sendMessage", chat_id=chat_id, text=text, **params)

    def send_photo(self, chat_id, photo, **params):
        return self.call("sendPhoto", chat_id=chat_id, photo=photo, **params)

    def press(self, key: str, action: str = "ok", user: str | None = None) -> None:
        uid = len(self.updates) + 1
        self.updates.append({"update_id": uid, "callback_query": {
            "id": f"cq{uid}", "from": {"id": int(user or self.admin)}, "data": f"{action}:{key}"}})

    def sent(self, method: str = "sendMessage") -> list[dict]:
        return [p for m, p in self.calls if m == method]


class FakePublisher:
    def __init__(self, name: str, fail: bool = False):
        self.name = name
        self.fail = fail
        self.fail_delete = False
        self.posts: list[dict] = []
        self.deleted: list[str] = []

    def post(self, item: dict) -> str:
        if self.fail:
            raise RuntimeError(f"{self.name} is down")
        self.posts.append(item)
        return f"{self.name}-{len(self.posts)}"

    def delete(self, post_id: str) -> None:
        if self.fail_delete:
            raise RuntimeError(f"{self.name} refused delete")
        self.deleted.append(post_id)

    def link(self, post_id: str) -> str:
        return f"https://{self.name}.test/{post_id}"
