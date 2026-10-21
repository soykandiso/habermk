from datetime import datetime, timedelta

from fakes import FakeTelegram

from habermk.approval import expire_drafts, process_updates, send_draft

NOW = datetime.fromisoformat("2026-10-21T12:00:00+02:00")


def draft(**extra):
    return {"status": "draft", "sentence": "Владата усвои измени.", "outlet": "СДК",
            "url": "https://sdk.mk/a", "title": "Наслов", "evidence": "Доказ.",
            "model": "groq:x", "drafted_at": NOW.isoformat(), "draft_message_id": 5, **extra}


def test_send_draft_has_buttons():
    tg = FakeTelegram()
    send_draft(tg, "111", "abc", draft())
    msg = tg.sent()[0]
    buttons = msg["reply_markup"]["inline_keyboard"][0]
    assert [b["callback_data"] for b in buttons] == ["ok:abc", "no:abc"]
    assert "— СДК: https://sdk.mk/a" in msg["text"]


def test_approve_and_reject():
    tg = FakeTelegram()
    state = {"tg_offset": 0, "items": {"a": draft(), "b": draft()}}
    tg.press("a", "ok")
    tg.press("b", "no")
    assert process_updates(tg, "111", state, NOW) == 2
    assert state["items"]["a"]["status"] == "approved"
    assert state["items"]["b"]["status"] == "rejected"
    assert state["tg_offset"] == 3


def test_only_admin_can_approve():
    tg = FakeTelegram()
    state = {"tg_offset": 0, "items": {"a": draft()}}
    tg.press("a", "ok", user="999")
    assert process_updates(tg, "111", state, NOW) == 0
    assert state["items"]["a"]["status"] == "draft"


def test_old_presses_are_not_reapplied():
    tg = FakeTelegram()
    state = {"tg_offset": 0, "items": {"a": draft()}}
    tg.press("a", "ok")
    process_updates(tg, "111", state, NOW)
    state["items"]["a"]["status"] = "posted"
    assert process_updates(tg, "111", state, NOW) == 0
    assert state["items"]["a"]["status"] == "posted"


def test_double_press_does_not_change_decision():
    tg = FakeTelegram()
    state = {"tg_offset": 0, "items": {"a": draft()}}
    tg.press("a", "ok")
    tg.press("a", "no")
    process_updates(tg, "111", state, NOW)
    assert state["items"]["a"]["status"] == "approved"


def test_drafts_expire():
    items = {"old": draft(drafted_at=(NOW - timedelta(hours=7)).isoformat()), "new": draft()}
    assert expire_drafts(FakeTelegram(), "111", items, NOW, 6) == 1
    assert items["old"]["status"] == "expired" and items["new"]["status"] == "draft"
