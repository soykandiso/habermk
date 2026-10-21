"""Per-platform post text. The source outlet is always named (copyright Art. 52)."""
from __future__ import annotations

from habermk.validate import count_graphemes


def telegram_text(sentence: str, outlet: str, url: str) -> str:
    return f"{sentence}\n\n— {outlet}: {url}"


def bluesky_text(sentence: str, outlet: str) -> str:
    """The link goes in a link card, so it does not count toward the 300 limit."""
    return f"{sentence}\n— {outlet}"


def facebook_text(sentence: str, outlet: str) -> str:
    """The link is sent separately and shown as a preview under the text."""
    return f"{sentence}\n\n— {outlet}"


def platform_errors(sentence: str, outlet: str, url: str, cfg: dict) -> list[str]:
    errors = []
    bsky = count_graphemes(bluesky_text(sentence, outlet))
    if bsky > cfg["bluesky_max_graphemes"]:
        errors.append(f"Bluesky text too long ({bsky} > {cfg['bluesky_max_graphemes']})")
    tg = len(telegram_text(sentence, outlet, url))
    if tg > cfg["telegram_max_chars"]:
        errors.append(f"Telegram text too long ({tg} > {cfg['telegram_max_chars']})")
    return errors
