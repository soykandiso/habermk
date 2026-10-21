"""End-to-end runs of the bot with fake source, model, Telegram and platforms."""
import json
from datetime import datetime

import pytest
from fakes import FakePublisher, FakeTelegram

from habermk.llm.providers import ModelError
from habermk.llm.router import ModelSpec, Router
from habermk.main import Bot
from habermk.models import Article, Cluster
from habermk.state import StateStore

ARTICLE = (
    "Министерството за внатрешни работи соопшти дека полицијата во Скопје пронашла две "
    "автоматски пушки и над 500 парчиња муниција. Според МВР, осомничениот Б.А. (24) е "
    "член на ИСИС и врбувал млади лица. Обвинителството ќе побара притвор од 30 дена."
)
ANSWER = json.dumps({
    "status": "OK",
    "sentence": "Полицијата во Скопје пронашла пушки и над 500 парчиња муниција кај Б.А. (24), "
                "кој според МВР е член на ИСИС.",
    "evidence": "Според МВР, осомничениот Б.А. (24) е член на ИСИС и врбувал млади лица.",
    "scope": "MK", "reason": "",
}, ensure_ascii=False)
NOON = datetime.fromisoformat("2026-10-21T12:00:00+02:00")


class Model:
    def __init__(self, reply=ANSWER):
        self.reply = reply
        self.calls = 0

    def complete(self, *a):
        self.calls += 1
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def clusters():
    return [
        Cluster(cluster_id="c1" * 10, rank=0, title="Ова е причината за апсењето",
                lead=Article(url="https://makfax.com.mk/a", outlet="Макфакс", title="Ова е причината"),
                article_count=46, age_minutes=60),
        Cluster(cluster_id="c2" * 10, rank=1, title="Мала вест",
                lead=Article(url="https://x.mk/b", outlet="Икс"), article_count=2),
    ]


@pytest.fixture
def make_bot(tmp_path, cfg):
    def make(auto=False, dry_run=False, model=None, pubs=None, tg=None, now=NOON):
        model = model or Model()
        bot = Bot(
            cfg=cfg,
            store=StateStore(tmp_path / "state.json"),
            router=Router([ModelSpec(id="fake:m")], providers={"fake": model},
                          sleep=lambda s: None),
            publishers=pubs if pubs is not None else [FakePublisher("telegram"),
                                                      FakePublisher("bluesky")],
            telegram=tg if tg is not None else FakeTelegram(),
            admin_chat="111", auto=auto, dry_run=dry_run,
            get_clusters=clusters,
            get_texts=lambda c: [(c.lead, ARTICLE)],
            now=lambda: now,
        )
        return bot
    return make


def test_manual_flow_draft_then_approve_then_publish_once(make_bot):
    tg = FakeTelegram()
    pubs = [FakePublisher("telegram"), FakePublisher("bluesky")]
    bot = make_bot(tg=tg, pubs=pubs)
    bot.run()
    key = "c1" * 10
    item = bot.store.items[key]
    assert item["status"] == "draft"
    assert "c2" * 10 not in bot.store.items  # too few outlets
    assert len(tg.sent()) == 1 and pubs[0].posts == []

    tg.press(key, "ok")
    make_bot(tg=tg, pubs=pubs).run()
    assert [len(p.posts) for p in pubs] == [1, 1]

    bot3 = make_bot(tg=tg, pubs=pubs)
    bot3.run()  # no duplicate on the next run
    assert [len(p.posts) for p in pubs] == [1, 1]
    assert bot3.store.items[key]["status"] == "posted"


def test_one_platform_failing_does_not_stop_the_other(make_bot):
    tg = FakeTelegram()
    good, bad = FakePublisher("telegram"), FakePublisher("bluesky", fail=True)
    bot = make_bot(auto=True, tg=tg, pubs=[bad, good])
    bot.run()
    item = bot.store.items["c1" * 10]
    assert len(good.posts) == 1
    assert item["platforms"]["bluesky"]["errors"] == 1
    assert item["status"] == "approved"  # bluesky is retried next run
    assert any("bluesky" in m["text"] for m in tg.sent() if m["text"].startswith("⚠️"))

    bad.fail = False
    make_bot(auto=True, tg=tg, pubs=[bad, good]).run()
    assert len(good.posts) == 1 and len(bad.posts) == 1  # telegram not reposted


def test_platform_given_up_after_max_attempts(make_bot, cfg):
    bad = FakePublisher("bluesky", fail=True)
    for _ in range(cfg["run"]["max_platform_attempts"]):
        bot = make_bot(auto=True, pubs=[FakePublisher("telegram"), bad])
        bot.run()
    assert bot.store.items["c1" * 10]["status"] == "posted"


def test_auto_mode_posts_without_drafts(make_bot):
    tg = FakeTelegram()
    pub = FakePublisher("telegram")
    make_bot(auto=True, tg=tg, pubs=[pub]).run()
    assert len(pub.posts) == 1
    assert not any("reply_markup" in m for m in tg.sent())


def test_dry_run_never_publishes(make_bot):
    tg = FakeTelegram()
    pub = FakePublisher("telegram")
    bot = make_bot(auto=True, dry_run=True, tg=tg, pubs=[pub])
    bot.run()
    tg.press("c1" * 10, "ok")
    make_bot(auto=True, dry_run=True, tg=tg, pubs=[pub]).run()
    assert pub.posts == []
    assert len([m for m in tg.sent() if "reply_markup" in m]) == 1


def test_invalid_answer_is_skipped_not_posted(make_bot):
    invented = json.loads(ANSWER)
    invented["sentence"] = invented["sentence"].replace("500", "900")
    pub = FakePublisher("telegram")
    bot = make_bot(auto=True, model=Model(json.dumps(invented, ensure_ascii=False)), pubs=[pub])
    bot.run()
    item = bot.store.items["c1" * 10]
    assert item["status"] == "skipped" and "numbers not in article" in item["reason"]
    assert pub.posts == []


def test_models_down_keeps_story_pending_then_gives_up(make_bot, cfg):
    model = Model(ModelError("down"))
    for i in range(cfg["run"]["max_pending_runs"]):
        bot = make_bot(model=model)
        bot.run()
        status = bot.store.items["c1" * 10]["status"]
        assert status == ("skipped" if i == cfg["run"]["max_pending_runs"] - 1 else "pending")


def test_new_cluster_id_for_same_article_is_not_drafted_again(make_bot, tmp_path):
    bot = make_bot()
    bot.run()
    moved = clusters()[0]
    moved.cluster_id = "zz" * 10
    bot2 = make_bot()
    bot2.get_clusters = lambda: [moved]
    bot2.run()
    assert bot2.store.items["zz" * 10]["status"] == "duplicate"


def test_outside_window_only_handles_approvals(make_bot):
    model = Model()
    bot = make_bot(model=model, now=datetime.fromisoformat("2026-10-21T03:00:00+02:00"))
    bot.run()
    assert model.calls == 0 and bot.store.items == {}


def test_daily_limit(make_bot, cfg):
    cfg["run"]["max_posts_per_day"] = 0
    pub = FakePublisher("telegram")
    make_bot(auto=True, pubs=[pub]).run()
    assert pub.posts == []


def test_unsent_draft_is_resent_next_run(make_bot):
    tg = FakeTelegram()
    tg.fail.add("sendMessage")
    bot = make_bot(tg=tg)
    bot.run()
    assert bot.store.items["c1" * 10].get("draft_message_id") is None
    tg.fail.clear()
    bot2 = make_bot(tg=tg)
    bot2.run()
    assert bot2.store.items["c1" * 10]["draft_message_id"]


# ------------------------------------------------------------ robustness

def test_quota_exhausted_keeps_story_pending_without_counting_attempts(make_bot, cfg):
    model = Model(ModelError("quota", retryable=True, retry_after=3600))
    texts_calls = []
    for _ in range(cfg["run"]["max_pending_runs"] + 1):
        bot = make_bot(model=model)
        orig = bot.get_texts
        bot.get_texts = lambda c: texts_calls.append(c) or orig(c)
        bot.run()
    item = bot.store.items["c1" * 10]
    assert item["status"] == "pending" and item["attempts"] == 0
    assert model.calls == 1           # later runs skip the resting model entirely
    assert len(texts_calls) == 1      # ... and don't even download articles
    assert bot.store.data["model_cooldowns"]


def test_one_broken_story_does_not_stop_the_others(make_bot):
    bot = make_bot()
    two = clusters()
    two[1].article_count = 10
    bot.get_clusters = lambda: two

    def texts(c):
        if c.cluster_id == "c1" * 10:
            raise ValueError("broken html")
        return [(c.lead, ARTICLE)]
    bot.get_texts = texts
    bot.run()
    assert bot.store.items["c1" * 10]["status"] == "pending"
    assert bot.store.items["c1" * 10]["attempts"] == 1
    assert bot.store.items["c2" * 10]["status"] == "draft"
    assert any("broken html" in e for e in bot.errors)


def test_same_problem_is_alerted_once_per_cooldown(make_bot):
    tg = FakeTelegram()
    bad = FakePublisher("bluesky", fail=True)

    def alerts():
        return [m for m in tg.sent() if m["text"].startswith("⚠️")]

    make_bot(auto=True, tg=tg, pubs=[FakePublisher("telegram"), bad]).run()
    make_bot(auto=True, tg=tg, pubs=[FakePublisher("telegram"), bad]).run()
    assert len(alerts()) == 1
    later = datetime.fromisoformat("2026-10-21T15:30:00+02:00")
    make_bot(auto=True, tg=tg, pubs=[FakePublisher("telegram"), bad], now=later).run()
    assert len(alerts()) == 2


def test_stale_approval_is_not_published(make_bot):
    tg = FakeTelegram()
    pub = FakePublisher("telegram")
    make_bot(tg=tg, pubs=[pub]).run()                     # draft at 12:00
    tg.press("c1" * 10, "ok")
    next_morning = datetime.fromisoformat("2026-10-22T07:00:00+02:00")
    bot = make_bot(tg=tg, pubs=[pub], now=next_morning)
    bot.get_clusters = lambda: []
    bot.run()
    assert pub.posts == []
    assert bot.store.items["c1" * 10]["status"] == "expired"


def test_skip_categories(make_bot, cfg):
    cfg["source"]["skip_categories"] = ["sport"]
    sport = clusters()
    sport[0].category = "sport"
    bot = make_bot()
    bot.get_clusters = lambda: sport
    bot.run()
    assert bot.store.items == {}


def test_missing_outlet_name_falls_back_to_domain(make_bot):
    nameless = clusters()
    nameless[0].lead.outlet = ""
    pub = FakePublisher("telegram")
    bot = make_bot(auto=True, pubs=[pub])
    bot.get_clusters = lambda: nameless
    bot.run()
    assert pub.posts[0]["outlet"] == "makfax.com.mk"


def test_run_summary_is_written(make_bot, tmp_path):
    bot = make_bot(auto=True)
    bot.summary_path = str(tmp_path / "summary.md")
    bot.run()
    text = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "### habermk run" in text and "posted to telegram: 1" in text


def test_logging_hides_request_urls():
    import logging

    from habermk.logs import setup_logging

    setup_logging()
    assert not logging.getLogger("httpx").isEnabledFor(logging.INFO)
    assert logging.getLogger("habermk").isEnabledFor(logging.INFO)
