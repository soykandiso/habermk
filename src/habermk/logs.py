"""Logging setup and secret redaction shared by every entry point.

The Actions logs and the state branch of this public repo are public. httpx
logs every request URL at INFO, and Telegram URLs contain the bot token
(/bot<TOKEN>/...), so the HTTP libraries are kept at WARNING, and every log
line, stored error and alert goes through redact(). GitHub's own masking of
secrets in logs is a second layer, never the only one.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Mapping

QUIET = ("httpx", "httpcore", "trafilatura", "htmldate", "courlan", "urllib3",
         "google_genai", "groq", "anthropic", "atproto")

_SECRET_NAME = re.compile(r"(TOKEN|KEY|PASSWORD|SECRET)$")
_PATTERNS = [
    (re.compile(r"bot\d{5,}:[A-Za-z0-9_-]{20,}"), "bot***"),           # Telegram token in a URL
    (re.compile(r"((?:access|input)_token=)[^&\s\"']+"), r"\1***"),     # Facebook token in a URL
]


def redact(text: str, env: Mapping[str, str] | None = None) -> str:
    """Remove secret values (from *_TOKEN/_KEY/_PASSWORD/_SECRET variables) and
    token-shaped URL parts from a message."""
    env = os.environ if env is None else env
    for name, value in env.items():
        if _SECRET_NAME.search(name) and len(value) >= 8:
            text = text.replace(value, "***")
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        clean = redact(message)
        if clean != message:
            record.msg, record.args = clean, ()
        return True


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(level)  # basicConfig is a no-op if handlers exist
    for handler in root.handlers:
        if not any(isinstance(f, RedactFilter) for f in handler.filters):
            handler.addFilter(RedactFilter())
    for name in QUIET:
        logging.getLogger(name).setLevel(logging.WARNING)
