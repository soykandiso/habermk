"""One run of the bot (GitHub Actions calls this every 15 minutes).

    1 load state
    2 read your ✅/❌ presses, expire old drafts
    3 collect new stories → full text → model → checks → draft (or approve in auto mode)
    4 publish approved items, each platform on its own, saving state after each post
    5 prune old entries, save, alert you about errors

    python -m habermk.main            # uses environment variables, see .env.example
"""
from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Any, Callable
from zoneinfo import ZoneInfo

import httpx

from habermk import approval
from habermk.cards import card_maker
from habermk.config import load_config
from habermk.dedupe import duplicate_of
from habermk.extract import best_texts
from habermk.formatting import platform_errors
from habermk.llm.router import AllModelsFailed, Router
from habermk.models import Cluster
from habermk.publishers import Publisher, from_env
from habermk.sources.vesti import fetch_clusters
from habermk.state import StateStore
from habermk.telegram import TelegramAPI, TelegramError
from habermk.validate import check, first_word_warning

log = logging.getLogger("habermk")


@dataclass
class Bot:
    cfg: dict[str, Any]
    store: StateStore
    router: Router
    publishers: list[Publisher]
    telegram: TelegramAPI | None = None      # for drafts and alerts
    admin_chat: str = ""
    auto: bool = False
    dry_run: bool = False
    get_clusters: Callable[[], list[Cluster]] | None = None
    get_texts: Callable[[Cluster], list[tuple[Any, str]]] | None = None
    card: Callable[[dict], bytes] | None = None   # image card shown with drafts
    now: Callable[[], datetime] = lambda: datetime.now(ZoneInfo("Europe/Skopje"))
    errors: list[str] = field(default_factory=list)

    # ---------------------------------------------------------------- helpers
    @property
    def run_cfg(self) -> dict[str, Any]:
        return self.cfg["run"]

    def in_window(self, now: datetime) -> bool:
        start = time.fromisoformat(self.run_cfg["window_start"])
        end = time.fromisoformat(self.run_cfg["window_end"])
        return start <= now.time() <= end

    def error(self, msg: str) -> None:
        log.error(msg)
        self.errors.append(msg)

    def save(self, message: str, push: bool = False) -> None:
        try:
            self.store.save(message, push=push)
        except Exception as e:  # keep going: the next save retries the push
            self.error(f"state save: {e}")

    # ------------------------------------------------------------ 2 approvals
    def handle_approvals(self, now: datetime) -> None:
        if not self.telegram:
            return
        try:
            decided = approval.process_updates(self.telegram, self.admin_chat, self.store.data, now)
            log.info("approvals: %d decisions", decided)
        except TelegramError as e:
            self.error(f"telegram approvals: {e}")
        approval.expire_drafts(self.telegram, self.admin_chat, self.store.items, now,
                               self.run_cfg["draft_ttl_hours"])
        # drafts that could not be sent last time
        for key, item in self.store.items.items():
            if item["status"] == "draft" and not item.get("draft_message_id"):
                self.send_draft(key, item)
        self.save("approvals", push=True)

    def send_draft(self, key: str, item: dict[str, Any]) -> None:
        if not self.telegram:
            return
        try:
            item["draft_message_id"] = approval.send_draft(self.telegram, self.admin_chat, key,
                                                           item, card=self.card)
        except TelegramError as e:
            self.error(f"telegram draft {key}: {e}")

    # -------------------------------------------------------------- 3 collect
    def candidates(self, clusters: list[Cluster], now: datetime) -> list[Cluster]:
        src, rc = self.cfg["source"], self.run_cfg
        out = []
        for c in clusters:
            item = self.store.items.get(c.cluster_id)
            if item is not None and item["status"] != "pending":
                continue
            if c.article_count < src["min_outlets"]:
                continue
            if c.age_minutes is not None and c.age_minutes > src["max_age_hours"] * 60:
                continue
            if item is None:
                dup = duplicate_of(c, self.store.items, now, rc["dedupe_title_similarity"],
                                   rc["dedupe_window_hours"])
                if dup:
                    self.store.items[c.cluster_id] = self.new_item(c, now, status="duplicate",
                                                                   reason=f"same story as {dup}")
                    continue
            out.append(c)
            if len(out) >= rc["candidates_per_run"]:
                break
        return out

    @staticmethod
    def new_item(c: Cluster, now: datetime, **extra: Any) -> dict[str, Any]:
        return {"cluster_id": c.cluster_id, "title": c.title, "url": c.lead.url,
                "outlet": c.lead.outlet, "urls": [a.url for a in c.articles],
                "first_seen": now.isoformat(), "status": "pending", "attempts": 0,
                "platforms": {}, **extra}

    def collect(self, now: datetime) -> None:
        clusters = self.get_clusters()
        stories = self.candidates(clusters, now)[: self.run_cfg["max_llm_stories_per_run"]]
        log.info("collect: %d clusters on the page, %d to process", len(clusters), len(stories))
        for c in stories:
            item = self.store.items.setdefault(c.cluster_id, self.new_item(c, now))
            if not self.process(c, item, now):
                self.save(f"collect {c.cluster_id}")
                break  # every model is down: stop calling them this run
            if item["status"] == "draft":
                self.send_draft(c.cluster_id, item)
            self.save(f"collect {c.cluster_id}")

    def process(self, c: Cluster, item: dict[str, Any], now: datetime) -> bool:
        """Fill the item from the model. Returns False when all models failed."""
        texts = self.get_texts(c)
        if not texts:
            item.update(status="skipped", reason="no article text")
            return True
        reasons = []
        for art, text in texts:
            try:
                result, model = self.router.generate(art.title or c.title, art.outlet, text)
            except AllModelsFailed as e:
                item["attempts"] = item.get("attempts", 0) + 1
                if item["attempts"] >= self.run_cfg["max_pending_runs"]:
                    item.update(status="skipped", reason=f"models failed: {e}"[:500])
                self.error(f"all models failed for {c.cluster_id}: {e}"[:500])
                return False
            problems = check(result, text, self.cfg["validation"])
            if not problems:
                problems = platform_errors(result["sentence"], art.outlet, art.url,
                                           self.cfg["platforms"])
            if problems:
                reasons.append(f"{art.outlet}: {'; '.join(problems)}")
                continue
            item.update(
                status="approved" if self.auto and not self.dry_run else "draft",
                sentence=result["sentence"], evidence=result["evidence"],
                scope=result["scope"], model=model, url=art.url, outlet=art.outlet,
                title=art.title or c.title, drafted_at=now.isoformat(),
                warning=first_word_warning(result["sentence"], text),
            )
            if item["status"] == "approved":
                item["decided_at"] = now.isoformat()
            return True
        item.update(status="skipped", reason=" | ".join(reasons)[:1000])
        return True

    # -------------------------------------------------------------- 4 publish
    def posts_today(self, now: datetime) -> int:
        today = now.date().isoformat()
        return sum(
            1 for it in self.store.items.values()
            if any(p.get("posted_at", "").startswith(today) for p in it["platforms"].values())
        )

    def publish(self, now: datetime) -> None:
        if self.dry_run or not self.publishers:
            return
        budget = min(self.run_cfg["max_posts_per_run"],
                     self.run_cfg["max_posts_per_day"] - self.posts_today(now))
        queue = sorted((it for it in self.store.items.values() if it["status"] == "approved"),
                       key=lambda it: it.get("decided_at", ""))
        for item in queue[: max(budget, 0)]:
            self.publish_item(item, now)

    def publish_item(self, item: dict[str, Any], now: datetime) -> None:
        max_attempts = self.run_cfg["max_platform_attempts"]
        for pub in self.publishers:
            rec = item["platforms"].setdefault(pub.name, {})
            if rec.get("id") or rec.get("errors", 0) >= max_attempts:
                continue
            try:
                rec["id"] = pub.post(item)
                rec["posted_at"] = now.isoformat()
                log.info("posted %s to %s: %s", item["cluster_id"], pub.name, rec["id"])
            except Exception as e:  # one platform must never stop the others
                rec["errors"] = rec.get("errors", 0) + 1
                rec["last_error"] = f"{type(e).__name__}: {e}"[:300]
                self.error(f"{pub.name} {item['cluster_id']}: {rec['last_error']}")
            # save + push after each attempt so a crash never causes a repost
            self.save(f"post {item['cluster_id']} {pub.name}", push=True)
        if all(item["platforms"].get(p.name, {}).get("id")
               or item["platforms"].get(p.name, {}).get("errors", 0) >= max_attempts
               for p in self.publishers):
            item["status"] = "posted"

    # ------------------------------------------------------------------ run
    def run(self) -> int:
        now = self.now()
        self.store.load()
        self.handle_approvals(now)
        if self.in_window(now):
            try:
                self.collect(now)
            except Exception as e:
                self.error(f"collect: {type(e).__name__}: {e}")
            self.publish(now)
        else:
            log.info("outside posting window, only approvals handled")
        removed = self.store.prune(now, self.run_cfg["prune_after_days"])
        self.save(f"run {now.isoformat(timespec='minutes')} (pruned {removed})", push=True)
        self.alert()
        return 0

    def alert(self) -> None:
        if not self.errors or not self.telegram:
            return
        text = "⚠️ habermk грешки:\n" + "\n".join(f"• {e}" for e in self.errors[:15])
        try:
            self.telegram.send_message(self.admin_chat, text[:4000])
        except TelegramError as e:
            log.error("could not send alert: %s", e)


def build(env: dict[str, str] | None = None) -> Bot:
    env = dict(os.environ) if env is None else env
    cfg = load_config()
    src = cfg["source"]
    http = httpx.Client(headers={"User-Agent": src["user_agent"]}, follow_redirects=True)
    tg = TelegramAPI(env["TELEGRAM_BOT_TOKEN"]) if env.get("TELEGRAM_BOT_TOKEN") else None
    want = cfg["extract"]["articles_per_cluster"]
    return Bot(
        cfg=cfg,
        store=StateStore(env.get("STATE_FILE", "state.json"), env.get("STATE_GIT_DIR") or None),
        router=Router.from_config(cfg["llm"]),
        publishers=from_env(cfg, env),
        telegram=tg if env.get("TELEGRAM_ADMIN_CHAT_ID") else None,
        admin_chat=env.get("TELEGRAM_ADMIN_CHAT_ID", ""),
        auto=env.get("APPROVAL_MODE", "manual").strip().lower() == "auto",
        dry_run=env.get("DRY_RUN", "0").strip().lower() in ("1", "true", "yes"),
        get_clusters=lambda: fetch_clusters(src["url"], src["user_agent"]),
        get_texts=lambda c: best_texts(c, cfg, http, want=want),
        card=card_maker(cfg),
        now=lambda: datetime.now(ZoneInfo(cfg["run"]["timezone"])),
    )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    bot = build()
    if not bot.telegram and not bot.auto:
        log.error("manual mode needs TELEGRAM_BOT_TOKEN and TELEGRAM_ADMIN_CHAT_ID")
        return 1
    log.info("mode=%s dry_run=%s platforms=%s", "auto" if bot.auto else "manual",
             bot.dry_run, [p.name for p in bot.publishers])
    return bot.run()


if __name__ == "__main__":
    sys.exit(main())
