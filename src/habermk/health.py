"""Weekly health check: are the source and every configured account still working?

    python -m habermk.health

Problems are sent to your private Telegram chat. Exit code 1 if anything failed.
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Callable

import httpx

from habermk.config import load_config
from habermk.logs import redact, setup_logging
from habermk.sources.vesti import fetch_clusters
from habermk.telegram import TelegramAPI

log = logging.getLogger("habermk.health")


def check_source(cfg: dict) -> str:
    clusters = fetch_clusters(cfg["source"]["url"], cfg["source"]["user_agent"])
    return f"vesti.mk: {len(clusters)} stories"


def check_telegram(env: dict) -> str:
    api = TelegramAPI(env["TELEGRAM_BOT_TOKEN"])
    me = api.call("getMe")
    chat = api.call("getChat", chat_id=env["TELEGRAM_CHANNEL_ID"]) if env.get("TELEGRAM_CHANNEL_ID") else {}
    return f"telegram: @{me['username']}" + (f", channel {chat.get('title', '')}" if chat else "")


def check_bluesky(env: dict) -> str:
    from atproto import Client

    Client().login(env["BLUESKY_HANDLE"], env["BLUESKY_APP_PASSWORD"])
    return f"bluesky: {env['BLUESKY_HANDLE']}"


def check_facebook(env: dict, cfg: dict) -> str:
    """debug_token on the Page token itself: is it still valid, and when does it expire?"""
    v = cfg["platforms"]["facebook_graph_version"]
    token = env["FB_PAGE_TOKEN"]
    data = httpx.get(f"https://graph.facebook.com/{v}/debug_token",
                     params={"input_token": token, "access_token": token}, timeout=30).json()
    info = data.get("data") or {}
    if not info.get("is_valid"):
        raise RuntimeError(f"Page token invalid: {info.get('error', data.get('error', {}))}")
    expires = info.get("expires_at", 0)
    return "facebook: token valid" + (", never expires" if not expires else f", expires at {expires}")


def main() -> int:
    setup_logging()
    env, cfg = dict(os.environ), load_config()
    checks: list[tuple[str, Callable[[], str]]] = [("source", lambda: check_source(cfg))]
    if env.get("TELEGRAM_BOT_TOKEN"):
        checks.append(("telegram", lambda: check_telegram(env)))
    if env.get("BLUESKY_HANDLE") and env.get("BLUESKY_APP_PASSWORD"):
        checks.append(("bluesky", lambda: check_bluesky(env)))
    if env.get("FB_PAGE_TOKEN"):
        checks.append(("facebook", lambda: check_facebook(env, cfg)))

    failures = []
    for name, fn in checks:
        try:
            log.info("OK %s", fn())
        except Exception as e:
            log.error("FAIL %s: %s", name, e)
            failures.append(redact(f"{name}: {type(e).__name__}: {e}")[:300])

    if failures and env.get("TELEGRAM_BOT_TOKEN") and env.get("TELEGRAM_ADMIN_CHAT_ID"):
        try:
            TelegramAPI(env["TELEGRAM_BOT_TOKEN"]).send_message(
                env["TELEGRAM_ADMIN_CHAT_ID"],
                "🩺 habermk health check failed:\n" + "\n".join(f"• {f}" for f in failures))
        except Exception as e:
            log.error("could not send alert: %s", e)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
