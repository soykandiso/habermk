"""One run of the bot (GitHub Actions calls this every 15 minutes).

    1 load state
    2 read your ✅/❌ presses, expire old drafts
    3 collect new stories → full text → model → checks → draft (or approve in auto mode)
    4 publish approved items, each platform on its own, saving state after each post
    5 prune old entries, alert you about new problems, save, write a run summary

    python -m habermk.main            # uses environment variables, see .env.example
"""
from __future__ import annotations

import logging
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

import httpx

from habermk import approval
from habermk.cards import card_maker
from habermk.config import load_config
from habermk.dedupe import duplicate_of
from habermk.extract import best_texts
from habermk.formatting import platform_errors
from habermk.llm.router import AllModelsCooling, AllModelsFailed, Router
from habermk.logs import setup_logging
from habermk.models import Cluster
from habermk.publishers import Publisher, from_env
from habermk.sources.vesti import fetch_clusters
from habermk.state import StateStore
from habermk.telegram import TelegramAPI, TelegramError
from habermk.validate import check, first_word_warning

log = logging.getLogger("habermk")


def alert_signature(message: str) -> str:
    """Same problem, same signature: numbers (story ids, counts) don't matter."""
    return re.sub(r"\d+", "#", message)[:120]


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
    summary_path: str | None = None          # GitHub job summary file
    errors: list[str] = field(default_factory=list)
    stats: Counter = field(default_factory=Counter)

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
            self.stats["decisions"] += decided
        except TelegramError as e:
            self.error(f"telegram approvals: {e}")
        self.stats["drafts expired"] += approval.expire_drafts(
            self.telegram, self.admin_chat, self.store.items, now, self.run_cfg["draft_ttl_hours"])
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
        skip_categories = set(src.get("skip_categories") or [])
        out = []
        for c in clusters:
            item = self.store.items.get(c.cluster_id)
            if item is not None and item["status"] != "pending":
                continue
            if c.article_count < src["min_outlets"] or c.category in skip_categories:
                continue
            if c.age_minutes is not None and c.age_minutes > src["max_age_hours"] * 60:
                continue
            if item is None:
                dup = duplicate_of(c, self.store.items, now, rc["dedupe_title_similarity"],
                                   rc["dedupe_window_hours"])
                if dup:
                    self.store.items[c.cluster_id] = self.new_item(c, now, status="duplicate",
                                                                   reason=f"same story as {dup}")
                    self.stats["duplicates"] += 1
                    continue
            out.append(c)
            if len(out) >= rc["candidates_per_run"]:
                break
        return out

    @staticmethod
    def new_item(c: Cluster, now: datetime, **extra: Any) -> dict[str, Any]:
        return {"cluster_id": c.cluster_id, "title": c.title, "url": c.lead.url,
                "outlet": c.lead.source, "urls": [a.url for a in c.articles],
                "category": c.category, "first_seen": now.isoformat(), "status": "pending",
                "attempts": 0, "platforms": {}, **extra}

    def collect(self, now: datetime) -> None:
        if not self.router.available():
            log.info("collect: every model is resting after a rate limit, skipping")
            self.stats["runs without models"] += 1
            return
        clusters = self.get_clusters()
        stories = self.candidates(clusters, now)[: self.run_cfg["max_llm_stories_per_run"]]
        log.info("collect: %d clusters on the page, %d to process", len(clusters), len(stories))
        for c in stories:
            item = self.store.items.setdefault(c.cluster_id, self.new_item(c, now))
            try:
                models_ok = self.process(c, item, now)
            except Exception as e:  # one broken article must not stop the others
                self.error(f"story {c.cluster_id}: {type(e).__name__}: {e}"[:400])
                self.count_failed_attempt(item, f"{type(e).__name__}: {e}")
                models_ok = True
            if item["status"] == "draft":
                self.send_draft(c.cluster_id, item)
            self.stats[f"stories {item['status']}"] += 1
            self.save(f"collect {c.cluster_id}")
            if not models_ok:
                break  # every model is down: stop calling them this run

    def count_failed_attempt(self, item: dict[str, Any], reason: str) -> None:
        item["attempts"] = item.get("attempts", 0) + 1
        if item["attempts"] >= self.run_cfg["max_pending_runs"]:
            item.update(status="skipped", reason=reason[:500])

    def process(self, c: Cluster, item: dict[str, Any], now: datetime) -> bool:
        """Fill the item from the model. Returns False when no model can answer."""
        texts = self.get_texts(c)
        if not texts:
            item.update(status="skipped", reason="no article text")
            return True
        reasons = []
        for art, text in texts:
            try:
                result, model = self.router.generate(art.title or c.title, art.source, text)
            except AllModelsCooling as e:
                log.warning("all models resting, %s stays pending: %s", c.cluster_id, e)
                return False  # quota, not the story: no attempt counted
            except AllModelsFailed as e:
                self.count_failed_attempt(item, f"models failed: {e}")
                self.error(f"all models failed for {c.cluster_id}: {e}"[:500])
                return False
            problems = check(result, text, self.cfg["validation"])
            if not problems:
                problems = platform_errors(result["sentence"], art.source, art.url,
                                           self.cfg["platforms"])
            if problems:
                reasons.append(f"{art.source}: {'; '.join(problems)}")
                continue
            item.update(
                status="approved" if self.auto and not self.dry_run else "draft",
                sentence=result["sentence"], evidence=result["evidence"],
                scope=result["scope"], model=model, url=art.url, outlet=art.source,
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

    def expire_late_approvals(self, now: datetime) -> None:
        """Don't publish news that went stale while waiting (e.g. approved at night)."""
        cutoff = now - timedelta(hours=self.run_cfg["max_publish_delay_hours"])
        for item in self.store.items.values():
            if item["status"] == "approved" \
                    and not any(p.get("id") for p in item["platforms"].values()) \
                    and datetime.fromisoformat(item["drafted_at"]) < cutoff:
                item.update(status="expired", reason="approved but too old to publish")
                self.stats["approvals expired"] += 1

    def publish(self, now: datetime) -> None:
        if self.dry_run or not self.publishers:
            return
        self.expire_late_approvals(now)
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
                self.stats[f"posted to {pub.name}"] += 1
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
        self.router.cooldown_until.update(self.store.data.get("model_cooldowns", {}))
        self.handle_approvals(now)
        if self.in_window(now):
            try:
                self.collect(now)
            except Exception as e:
                self.error(f"collect: {type(e).__name__}: {e}"[:400])
            self.publish(now)
        else:
            log.info("outside posting window, only approvals handled")
        self.store.data["model_cooldowns"] = self.router.active_cooldowns()
        removed = self.store.prune(now, self.run_cfg["prune_after_days"])
        self.alert(now)
        self.save(f"run {now.isoformat(timespec='minutes')} (pruned {removed})", push=True)
        self.write_summary(now)
        return 0

    def alert(self, now: datetime) -> None:
        """Tell the admin about problems, but the same problem at most once per
        alert_cooldown_hours (an outage must not send a message every 15 min)."""
        if not self.errors or not self.telegram:
            return
        sent: dict[str, str] = self.store.data.setdefault("alerts", {})
        cooldown = timedelta(hours=self.run_cfg["alert_cooldown_hours"])
        for sig in [s for s, t in sent.items() if now - datetime.fromisoformat(t) > 2 * cooldown]:
            del sent[sig]
        fresh = [e for e in self.errors
                 if alert_signature(e) not in sent
                 or now - datetime.fromisoformat(sent[alert_signature(e)]) >= cooldown]
        if not fresh:
            return
        text = "⚠️ habermk грешки:\n" + "\n".join(f"• {e}" for e in fresh[:15])
        try:
            self.telegram.send_message(self.admin_chat, text[:4000])
        except TelegramError as e:
            log.error("could not send alert: %s", e)
            return
        for e in fresh:
            sent[alert_signature(e)] = now.isoformat()

    def write_summary(self, now: datetime) -> None:
        lines = [f"### habermk run {now.isoformat(timespec='minutes')}",
                 f"mode: {'auto' if self.auto else 'manual'}"
                 f"{' (dry run)' if self.dry_run else ''}, "
                 f"platforms: {', '.join(p.name for p in self.publishers) or 'none'}", ""]
        lines += [f"- {k}: {v}" for k, v in sorted(self.stats.items())] or ["- nothing to do"]
        if self.errors:
            lines += ["", f"**{len(self.errors)} error(s)**", *[f"- {e}" for e in self.errors[:20]]]
        log.info("summary: %s", "; ".join(f"{k}={v}" for k, v in sorted(self.stats.items())))
        if self.summary_path:
            with open(self.summary_path, "a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")


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
        summary_path=env.get("GITHUB_STEP_SUMMARY") or None,
    )


def main() -> int:
    setup_logging()
    bot = build()
    if not bot.telegram and not bot.auto:
        log.error("manual mode needs TELEGRAM_BOT_TOKEN and TELEGRAM_ADMIN_CHAT_ID")
        return 1
    log.info("mode=%s dry_run=%s platforms=%s", "auto" if bot.auto else "manual",
             bot.dry_run, [p.name for p in bot.publishers])
    return bot.run()


if __name__ == "__main__":
    sys.exit(main())
