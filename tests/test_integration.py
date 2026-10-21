"""The real parser and extractor wired into the bot (only the model and the
platforms are fakes), plus build(): what the workflow actually runs."""
import json
from datetime import datetime

from fakes import FakePublisher, FakeTelegram

from habermk.extract import extract_text
from habermk.llm.router import ModelSpec, Router
from habermk.main import Bot, build
from habermk.sources.vesti import parse_clusters
from habermk.state import StateStore

ANSWER = json.dumps({
    "status": "OK",
    "sentence": "Министерството за внатрешни работи соопшти дека полицијата во Скопје пронашла "
                "две автоматски пушки и над 500 парчиња муниција.",
    "evidence": "Министерството за внатрешни работи соопшти дека полицијата во Скопје пронашла "
                "две автоматски пушки, снајпер и над 500 парчиња муниција при претрес на стан "
                "во населбата Аеродром.",
    "scope": "MK", "reason": "",
}, ensure_ascii=False)


class Model:
    def complete(self, *a):
        return ANSWER


def test_fixture_page_to_published_post(tmp_path, cfg, vesti_html, article_html):
    pub = FakePublisher("telegram")
    bot = Bot(
        cfg=cfg, store=StateStore(tmp_path / "state.json"),
        router=Router([ModelSpec(id="fake:m")], providers={"fake": Model()}),
        publishers=[pub], telegram=FakeTelegram(), admin_chat="111", auto=True,
        get_clusters=lambda: parse_clusters(vesti_html),
        get_texts=lambda c: [(c.lead, extract_text(article_html))],
        now=lambda: datetime.fromisoformat("2026-10-21T12:00:00+02:00"),
    )
    bot.run()
    posted = pub.posts[0]
    assert posted["cluster_id"] == "255191"            # "Вест #1" on the page
    assert posted["outlet"] == "360 Степени"
    assert posted["url"].startswith("https://360stepeni.mk/")
    assert len(pub.posts) == cfg["run"]["max_posts_per_run"]


def test_build_wires_platforms_from_secrets(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path.parent)  # config is found via the repo, not cwd
    env = {"TELEGRAM_BOT_TOKEN": "123:abc", "TELEGRAM_ADMIN_CHAT_ID": "111",
           "TELEGRAM_CHANNEL_ID": "@ch", "BLUESKY_HANDLE": "x.bsky.social",
           "BLUESKY_APP_PASSWORD": "p", "APPROVAL_MODE": "auto", "DRY_RUN": "1",
           "STATE_FILE": str(tmp_path / "s.json")}
    bot = build(env)
    assert [p.name for p in bot.publishers] == ["telegram", "bluesky"]
    assert all(p.card is not None for p in bot.publishers)   # cards on both
    assert bot.auto and bot.dry_run and bot.telegram is not None and bot.card is not None


def test_build_without_secrets_has_no_platforms(tmp_path):
    bot = build({"STATE_FILE": str(tmp_path / "s.json")})
    assert bot.publishers == [] and bot.telegram is None and not bot.auto
