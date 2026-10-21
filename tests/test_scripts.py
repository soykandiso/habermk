"""The scripts you run by hand or on a schedule: eval, health check, Facebook token."""
import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from habermk import health  # noqa: E402
from habermk.llm.router import ModelSpec, Router  # noqa: E402
from habermk.models import Article, Cluster  # noqa: E402

ARTICLE = ("Министерството за внатрешни работи соопшти дека полицијата во Скопје пронашла две "
           "автоматски пушки и над 500 парчиња муниција. Според МВР, осомничениот Б.А. (24) е "
           "член на ИСИС и врбувал млади лица. Обвинителството ќе побара притвор од 30 дена.")
GOOD = {"status": "OK",
        "sentence": "Полицијата во Скопје пронашла пушки и над 500 парчиња муниција кај Б.А. (24), "
                    "кој според МВР е член на ИСИС.",
        "evidence": "Според МВР, осомничениот Б.А. (24) е член на ИСИС и врбувал млади лица.",
        "scope": "MK", "reason": ""}


class Fixed:
    def __init__(self, reply):
        self.reply = reply

    def complete(self, *a):
        return json.dumps(self.reply, ensure_ascii=False)


def test_eval_writes_a_scorable_table(tmp_path, monkeypatch):
    import eval_models

    clusters = [
        Cluster(cluster_id="1", rank=0, title="Ова е причината", article_count=20,
                lead=Article(url="https://makfax.com.mk/a", outlet="Макфакс")),
        Cluster(cluster_id="2", rank=1, title="Видео", article_count=9,
                lead=Article(url="https://x.mk/b", outlet="Икс")),
    ]
    monkeypatch.setattr(eval_models, "fetch_clusters", lambda *a: clusters)
    monkeypatch.setattr(eval_models, "best_texts",
                        lambda c, cfg, client: [(c.lead, ARTICLE)] if c.cluster_id == "1" else [])
    invented = dict(GOOD, sentence=GOOD["sentence"].replace("500", "900"))
    providers = {"good": Fixed(GOOD), "bad": Fixed(invented)}
    monkeypatch.setattr(eval_models.Router, "from_config",
                        classmethod(lambda cls, llm, only: Router([ModelSpec(id=i) for i in only],
                                                                  providers=providers)))
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr(sys, "argv", ["eval", "--models", "good:m,bad:m", "--outdir", str(tmp_path),
                                      "--stories", "5"])
    assert eval_models.main() == 0

    table, = tmp_path.glob("eval_*.csv")
    assert table.read_bytes().startswith(b"\xef\xbb\xbf")        # BOM: Excel shows Cyrillic
    rows = list(csv.DictReader(table.open(encoding="utf-8-sig")))
    assert [(r["cluster_id"], r["model"], r["status"]) for r in rows] == [
        ("1", "good:m", "OK"), ("1", "bad:m", "REJECTED"),
        ("2", "good:m", "NO_TEXT"), ("2", "bad:m", "NO_TEXT")]
    assert "numbers not in article" in rows[1]["problems"]
    assert {"YOUR_macedonian_1to5", "YOUR_invented_fact_Y_N"} <= set(rows[0])
    assert (tmp_path / "texts" / "1.txt").read_text(encoding="utf-8").startswith("Ова е причината")
    assert "| good:m | 1 | 0 | 0 | 0 | 1 |" in summary.read_text(encoding="utf-8")


class FakeAPI:
    sent: list = []

    def __init__(self, token):
        pass

    def send_message(self, chat, text):
        FakeAPI.sent.append(text)


def test_health_ok_without_accounts(monkeypatch):
    for name in ("TELEGRAM_BOT_TOKEN", "BLUESKY_HANDLE", "FB_PAGE_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(health, "fetch_clusters", lambda *a: [object()] * 36)
    assert health.main() == 0


def test_health_failure_alerts_without_leaking_the_token(monkeypatch):
    FakeAPI.sent = []
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:ABCdefGHIjklMNOpqrSTUvwx")
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "111")
    monkeypatch.setattr(health, "fetch_clusters", lambda *a: [object()])

    def broken(env):
        raise RuntimeError("POST https://api.telegram.org/bot123456:ABCdefGHIjklMNOpqrSTUvwx/getMe")
    monkeypatch.setattr(health, "check_telegram", broken)
    monkeypatch.setattr(health, "TelegramAPI", FakeAPI)
    assert health.main() == 1
    assert len(FakeAPI.sent) == 1 and "telegram" in FakeAPI.sent[0]
    assert "ABCdef" not in FakeAPI.sent[0]


@pytest.mark.parametrize("payload,ok", [
    ({"data": {"is_valid": True, "expires_at": 0}}, True),
    ({"data": {"is_valid": False, "error": {"message": "expired"}}}, False),
])
def test_health_facebook_token_check(monkeypatch, cfg, payload, ok):
    class Resp:
        def json(self):
            return payload
    monkeypatch.setattr(health.httpx, "get", lambda *a, **k: Resp())
    if ok:
        assert "never expires" in health.check_facebook({"FB_PAGE_TOKEN": "t"}, cfg)
    else:
        with pytest.raises(RuntimeError, match="invalid"):
            health.check_facebook({"FB_PAGE_TOKEN": "t"}, cfg)


def test_fb_token_prints_page_id_and_token(monkeypatch, capsys):
    import fb_token

    answers = iter(["111"])
    secrets = iter(["app-secret", "short-token"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(fb_token.getpass, "getpass", lambda prompt="": next(secrets))
    replies = {
        "oauth/access_token": {"access_token": "long-user"},
        "me/accounts": {"data": [{"name": "Бадијала клик", "id": "999", "access_token": "page-tok"}]},
        "debug_token": {"data": {"is_valid": True, "expires_at": 0}},
    }
    calls = []
    monkeypatch.setattr(fb_token, "get", lambda path, **p: calls.append((path, p)) or replies[path])
    assert fb_token.main() == 0
    out = capsys.readouterr().out
    assert "FB_PAGE_ID    = 999" in out and "FB_PAGE_TOKEN = page-tok" in out
    assert "Expires: Never" in out
    assert calls[0][1]["fb_exchange_token"] == "short-token"
