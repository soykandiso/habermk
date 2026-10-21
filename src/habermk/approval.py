"""Your private Telegram chat with the bot: drafts, takedowns and commands.

There is no server: each run reads what happened since the last run with
getUpdates (Telegram keeps updates for 24 h) and remembers the offset in state.

Buttons (callback data "<action>:<story key>"):
    ok / no      on a draft: publish / reject
    del          on a published post: ask "delete everywhere?"
    delok / keep confirm the deletion / cancel it

Commands: /status, /pause, /resume, /help (only from the admin).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Callable

from habermk.formatting import telegram_text
from habermk.telegram import TelegramAPI, TelegramError

log = logging.getLogger(__name__)

APPROVE, REJECT, DELETE, DELETE_OK, KEEP = "ok", "no", "del", "delok", "keep"
COMMANDS = [
    {"command": "status", "description": "Состојба: режим, пауза, објави денес"},
    {"command": "pause", "description": "Запри нови нацрти и објави"},
    {"command": "resume", "description": "Продолжи"},
    {"command": "help", "description": "Помош"},
]
COMMANDS_VERSION = 1


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


def _answer(api: TelegramAPI, callback_id: str, text: str) -> None:
    """Best effort: Telegram refuses answers to presses older than a few
    minutes, which is normal when we only look every 15 minutes."""
    try:
        api.call("answerCallbackQuery", callback_query_id=callback_id, text=text)
    except TelegramError as e:
        log.info("could not answer button press: %s", e)


def _edit(api: TelegramAPI, admin_chat: str, message_id: int | None, text: str,
          keyboard: list | None = None) -> None:
    if not message_id:
        return
    params: dict[str, Any] = {"chat_id": admin_chat, "message_id": message_id, "text": text,
                              "link_preview_options": {"is_disabled": True}}
    if keyboard is not None:
        params["reply_markup"] = {"inline_keyboard": keyboard}
    try:
        api.call("editMessageText", **params)
    except TelegramError as e:
        log.info("could not edit message: %s", e)


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


def posted_text(item: dict[str, Any], links: dict[str, str | None]) -> str:
    lines = ["📣 ОБЈАВЕНО", "", item["sentence"], f"— {item['outlet']}", ""]
    for name, rec in item["platforms"].items():
        if rec.get("id"):
            lines.append(f"{name}: {links.get(name) or '✓'}")
        elif rec.get("errors"):
            lines.append(f"{name}: ❌ {rec.get('last_error', '')}")
    return "\n".join(lines)


def delete_button(key: str) -> list:
    return [[{"text": "🗑 Избриши насекаде", "callback_data": f"{DELETE}:{key}"}]]


def send_posted(api: TelegramAPI, admin_chat: str, key: str, item: dict[str, Any],
                links: dict[str, str | None]) -> int:
    """Confirmation of a publication, with the takedown button."""
    msg = api.send_message(admin_chat, posted_text(item, links),
                           reply_markup={"inline_keyboard": delete_button(key)},
                           link_preview_options={"is_disabled": True})
    return msg["message_id"]


def _close_draft(api: TelegramAPI, admin_chat: str, item: dict[str, Any], label: str) -> None:
    """Remove the buttons and say what happened (best effort)."""
    _edit(api, admin_chat, item.get("draft_message_id"), f"{label}\n\n{draft_text(item)}")


def set_commands(api: TelegramAPI, admin_chat: str, state: dict[str, Any]) -> None:
    """Show the command menu in your chat (once per version)."""
    if state.get("commands_v") == COMMANDS_VERSION:
        return
    chat_id: int | str = int(admin_chat) if admin_chat.lstrip("-").isdigit() else admin_chat
    try:
        api.call("setMyCommands", commands=COMMANDS, scope={"type": "chat", "chat_id": chat_id})
        state["commands_v"] = COMMANDS_VERSION
    except TelegramError as e:
        log.info("could not set the command menu: %s", e)


def _handle_message(api: TelegramAPI, admin_chat: str, msg: dict[str, Any],
                    on_command: Callable[[str], str | None] | None) -> None:
    text = (msg.get("text") or "").strip()
    if str(msg.get("from", {}).get("id")) != str(admin_chat) or not text.startswith("/"):
        return  # only the admin's commands; everything else is ignored
    command = text.split()[0].split("@")[0].lower()
    reply = on_command(command) if on_command else None
    if reply:
        try:
            api.send_message(admin_chat, reply)
        except TelegramError as e:
            log.warning("could not reply to %s: %s", command, e)


def process_updates(api: TelegramAPI, admin_chat: str, state: dict[str, Any], now: datetime,
                    on_delete: Callable[[str, dict], str] | None = None,
                    on_command: Callable[[str], str | None] | None = None) -> int:
    """Apply button presses and commands. Only the admin counts. Returns decisions made."""
    updates = api.call("getUpdates", offset=state.get("tg_offset", 0), timeout=0,
                       allowed_updates=["callback_query", "message"])
    decided = 0
    for upd in updates:
        state["tg_offset"] = upd["update_id"] + 1
        if "message" in upd:
            _handle_message(api, admin_chat, upd["message"], on_command)
            continue
        cq = upd.get("callback_query")
        if not cq:
            continue
        if str(cq.get("from", {}).get("id")) != str(admin_chat):
            _answer(api, cq["id"], "Не е дозволено.")
            continue
        action, _, key = (cq.get("data") or "").partition(":")
        item = state["items"].get(key)
        message_id = (cq.get("message") or {}).get("message_id")
        status = item.get("status") if item else "непознато"

        if action in (APPROVE, REJECT) and status == "draft":
            item["status"] = "approved" if action == APPROVE else "rejected"
            item["decided_at"] = now.isoformat()
            decided += 1
            _answer(api, cq["id"], "Одобрено ✅" if action == APPROVE else "Одбиено ❌")
            _close_draft(api, admin_chat, item, "✅ ОДОБРЕНО" if action == APPROVE else "❌ ОДБИЕНО")
        elif action == DELETE and _published(item):
            _answer(api, cq["id"], "Потврди бришење")
            confirm = [[{"text": "⚠️ Да, избриши насекаде", "callback_data": f"{DELETE_OK}:{key}"},
                             {"text": "Откажи", "callback_data": f"{KEEP}:{key}"}]]
            _edit(api, admin_chat, message_id, "⚠️ Сигурно бришење?\n\n" + item["sentence"],
                  confirm)
        elif action == KEEP and _published(item):
            _answer(api, cq["id"], "Откажано")
            _edit(api, admin_chat, message_id, "📣 ОБЈАВЕНО\n\n" + item["sentence"],
                  delete_button(key))
        elif action == DELETE_OK and _published(item) and on_delete:
            result = on_delete(key, item)
            decided += 1
            _answer(api, cq["id"], "Избришано")
            _edit(api, admin_chat, message_id, f"🗑 ИЗБРИШАНО\n\n{item['sentence']}\n\n{result}")
        else:
            _answer(api, cq["id"], f"Веќе: {status}")
    return decided


def _published(item: dict[str, Any] | None) -> bool:
    return bool(item) and item.get("status") != "deleted" and any(
        p.get("id") and not p.get("deleted_at") for p in item.get("platforms", {}).values())


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
