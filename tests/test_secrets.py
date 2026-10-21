"""Nothing secret or unpublished may reach the public repo or the public logs."""
import json
import logging
import subprocess

import pytest

from habermk.logs import RedactFilter, redact, setup_logging
from habermk.state import StateKeyError, StateStore

KEY = "a long random passphrase for tests"
SENTENCE = "Одбиена реченица што никој не смее да ја види."


def test_state_on_disk_is_encrypted(tmp_path):
    store = StateStore(tmp_path / "state.json", secret=KEY)
    store.items["a"] = {"status": "rejected", "sentence": SENTENCE}
    store.save()
    raw = (tmp_path / "state.json").read_bytes()
    assert SENTENCE.encode() not in raw and b"rejected" not in raw
    again = StateStore(tmp_path / "state.json", secret=KEY).load()
    assert again.items["a"]["sentence"] == SENTENCE


def test_wrong_or_missing_key_is_a_clear_error(tmp_path):
    StateStore(tmp_path / "state.json", secret=KEY).save()
    with pytest.raises(StateKeyError, match="does not match"):
        StateStore(tmp_path / "state.json", secret=KEY + "x").load()
    with pytest.raises(StateKeyError, match="not set"):
        StateStore(tmp_path / "state.json").load()


def test_short_key_is_refused(tmp_path):
    with pytest.raises(StateKeyError, match="at least 20"):
        StateStore(tmp_path / "state.json", secret="short")


def test_plain_state_is_encrypted_on_next_save(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps({"items": {"a": {"x": SENTENCE}}}),
                                         encoding="utf-8")
    store = StateStore(tmp_path / "state.json", secret=KEY).load()
    store.save()
    assert SENTENCE.encode() not in (tmp_path / "state.json").read_bytes()


def test_unchanged_state_is_not_rewritten(tmp_path):
    store = StateStore(tmp_path / "state.json", secret=KEY)
    store.save()
    first = (tmp_path / "state.json").read_bytes()
    store.save()
    assert (tmp_path / "state.json").read_bytes() == first   # no new ciphertext
    store.data["tg_offset"] = 5
    store.save()
    assert (tmp_path / "state.json").read_bytes() != first


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout


def test_state_branch_keeps_a_single_commit(tmp_path):
    remote, work = tmp_path / "remote.git", tmp_path / "wt"
    git("init", "-q", "--bare", str(remote), cwd=tmp_path)
    git("init", "-q", "-b", "state", str(work), cwd=tmp_path)
    git("config", "user.email", "t@t", cwd=work)
    git("config", "user.name", "t", cwd=work)
    git("remote", "add", "origin", str(remote), cwd=work)
    store = StateStore(work / "state.json", git_dir=work, secret=KEY)
    for i in range(3):
        store.items[str(i)] = {"status": "rejected", "sentence": SENTENCE}
        store.save(f"save {i}", push=True)
    store.save("nothing new", push=True)
    assert git("--git-dir", str(remote), "rev-list", "--count", "state", cwd=tmp_path).strip() == "1"
    assert git("--git-dir", str(remote), "log", "--format=%s", "state", cwd=tmp_path).strip() == "save 2"
    blob = git("--git-dir", str(remote), "show", "state:state.json", cwd=tmp_path)
    assert "rejected" not in blob


def test_redact_removes_secret_values_and_token_urls():
    env = {"TELEGRAM_BOT_TOKEN": "123456:ABCdefGHIjklMNOpqrSTUvwx", "FB_PAGE_TOKEN": "EAAGsecretvalue",
           "TELEGRAM_ADMIN_CHAT_ID": "12345678"}
    text = ("POST https://api.telegram.org/bot123456:ABCdefGHIjklMNOpqrSTUvwx/sendMessage failed; "
            "DELETE https://graph.facebook.com/v26.0/1_2?access_token=EAAGsecretvalue; chat 12345678")
    clean = redact(text, env)
    assert "ABCdef" not in clean and "EAAGsecret" not in clean
    assert "bot***" in clean and "access_token=***" in clean
    assert "chat 12345678" in clean            # ids are not secrets
    assert redact("https://x.mk/?input_token=abc&b=1", {}) == "https://x.mk/?input_token=***&b=1"


def test_log_lines_are_redacted(monkeypatch):
    monkeypatch.setenv("BLUESKY_APP_PASSWORD", "abcd-efgh-ijkl-mnop")
    record = logging.LogRecord("x", logging.ERROR, __file__, 1, "login with %s failed",
                               ("abcd-efgh-ijkl-mnop",), None)
    RedactFilter().filter(record)
    assert record.getMessage() == "login with *** failed"


def test_setup_logging_installs_the_filter():
    setup_logging()
    assert all(any(isinstance(f, RedactFilter) for f in h.filters)
               for h in logging.getLogger().handlers)


def test_bot_errors_and_stored_errors_are_redacted(tmp_path, cfg, monkeypatch):
    from datetime import datetime

    from fakes import FakeTelegram

    from habermk.llm.router import Router
    from habermk.main import Bot

    monkeypatch.setenv("FB_PAGE_TOKEN", "EAAGsecretvalue123")

    class LeakyPublisher:
        name = "facebook"

        def post(self, item):
            raise RuntimeError("connect failed for https://graph.facebook.com/?access_token=EAAGsecretvalue123")

    tg = FakeTelegram()
    bot = Bot(cfg=cfg, store=StateStore(tmp_path / "s.json"), router=Router([]),
              publishers=[LeakyPublisher()], telegram=tg, admin_chat="111", auto=True,
              get_clusters=lambda: [], now=lambda: datetime.fromisoformat("2026-10-21T12:00:00+02:00"))
    bot.store.items["k"] = {"cluster_id": "k", "status": "approved", "platforms": {},
                            "first_seen": "2026-10-21T11:00:00+02:00",
                            "drafted_at": "2026-10-21T11:00:00+02:00", "sentence": "А."}
    bot.publish_item(bot.store.items["k"], datetime.fromisoformat("2026-10-21T12:00:00+02:00"))
    bot.alert(datetime.fromisoformat("2026-10-21T12:00:00+02:00"))
    stored = json.dumps(bot.store.data)
    sent = " ".join(m["text"] for m in tg.sent())
    assert "EAAGsecret" not in stored and "EAAGsecret" not in sent
    assert "EAAGsecret" not in " ".join(bot.errors)


def test_main_refuses_to_push_unencrypted_state(monkeypatch):
    from habermk import main as main_module

    monkeypatch.setenv("STATE_GIT_DIR", "state-wt")
    monkeypatch.delenv("STATE_KEY", raising=False)
    assert main_module.main() == 1
