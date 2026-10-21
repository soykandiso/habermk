"""Logging setup shared by every entry point.

The Actions logs of this public repo are public. httpx logs every request URL
at INFO, and Telegram URLs contain the bot token (/bot<TOKEN>/...), so the
HTTP libraries are kept at WARNING. GitHub also masks secrets, but we never
rely on that alone.
"""
from __future__ import annotations

import logging

QUIET = ("httpx", "httpcore", "trafilatura", "htmldate", "courlan", "urllib3",
         "google_genai", "groq", "anthropic", "atproto")


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger().setLevel(level)  # basicConfig is a no-op if handlers exist
    for name in QUIET:
        logging.getLogger(name).setLevel(logging.WARNING)
