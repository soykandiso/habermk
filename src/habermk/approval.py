"""Drafts in your private Telegram chat with ✅ / ❌ buttons.

There is no server: each run reads the button presses since the last run with
getUpdates (Telegram keeps them for 24 h) and remembers the offset in state.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Callable

from habermk.formatting import telegram_text
from habermk.telegram import TelegramAPI, TelegramError

log = logging.getLogger(__name__)

APPROVE, REJECT = "ok", "no"


def draft_text(item: dict[str, Any]) -> str:
    lines = [
        "📝 НАЦРТ",
        "",
        telegram_text(item["sentence"], item["outlet"], item["url"]),
        "",
        f"Наслов: {item['title']}",
        f"Доказ: {item['evidence']}",
        f"Модел: {item.get('model', '?')}",
    ]
    if item.get("warning"):
        lines.append(f"⚠️ {item['warning']}")
    return "\n".join(lines)


def send_draft(api: TelegramAPI, admin_chat: str, key: str, item: dict[str, Any],
               card: Callable[[dict], bytes] | None = None) -> int:
    """The card (if any) first, so you approve the image too, then the text with buttons."""
    if card:
        try:
            api.send_photo(admin_chat, card(item))
        except Exception as e:  # the draft text matters more than the picture
            log.warning("could not send draft card: %s", e)
    keyboard = {"inline_keyboard": [[
        {"text": "✅ Објави", "callback_data": f"{APPROVE}:{key}"},
        {"text": "❌ Одбиј", "callback_data": f"{REJECT}:{key}"},
    ]]}
    msg = api.send_message(admin_chat, draft_text(item), reply_markup=keyboard,
                           link_preview_options={"is_disabled": True})
    return msg["message_id"]


def _close_draft(api: TelegramAPI, admin_chat: str, item: dict[str, Any], label: str) -> None:
    """Remove the buttons and say what happened (best effort)."""
    if not item.get("draft_message_id"):
        return
    try:
        api.call("editMessageText", chat_id=admin_chat, message_id=item["draft_message_id"],
                 text=f"{label}\n\n{draft_text(item)}",
                 link_preview_options={"is_disabled": True})
    except TelegramError as e:
        log.info("could not edit draft message: %s", e)


def process_updates(api: TelegramAPI, admin_chat: str, state: dict[str, Any],
                    now: datetime) -> int:
    """Apply button presses. Only presses by the admin count. Returns decisions made."""
    updates = api.call("getUpdates", offset=state.get("tg_offset", 0), timeout=0,
                       allowed_updates=["callback_query"])
    decided = 0
    for upd in updates:
        state["tg_offset"] = upd["update_id"] + 1
        cq = upd.get("callback_query")
        if not cq:
            continue
        if str(cq.get("from", {}).get("id")) != str(admin_chat):
            api.call("answerCallbackQuery", callback_query_id=cq["id"], text="Не е дозволено.")
            continue
        action, _, key = (cq.get("data") or "").partition(":")
        item = state["items"].get(key)
        if item is None or item.get("status") != "draft" or action not in (APPROVE, REJECT):
            status = item.get("status") if item else "непознато"
            api.call("answerCallbackQuery", callback_query_id=cq["id"], text=f"Веќе: {status}")
            continue
        item["status"] = "approved" if action == APPROVE else "rejected"
        item["decided_at"] = now.isoformat()
        decided += 1
        api.call("answerCallbackQuery", callback_query_id=cq["id"],
                 text="Одобрено ✅" if action == APPROVE else "Одбиено ❌")
        _close_draft(api, admin_chat, item, "✅ ОДОБРЕНО" if action == APPROVE else "❌ ОДБИЕНО")
    return decided


def expire_drafts(api: TelegramAPI | None, admin_chat: str, items: dict[str, dict[str, Any]],
                  now: datetime, ttl_hours: int) -> int:
    cutoff = now - timedelta(hours=ttl_hours)
    expired = 0
    for item in items.values():
        if item.get("status") == "draft" and datetime.fromisoformat(item["drafted_at"]) < cutoff:
            item["status"] = "expired"
            expired += 1
            if api:
                _close_draft(api, admin_chat, item, "⌛ ИСТЕЧЕНО")
    return expired
