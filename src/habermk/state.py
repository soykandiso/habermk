"""Run state: one JSON file, kept on the `state` git branch in GitHub Actions.

The repository is public, so the state is **encrypted** with the STATE_KEY
secret (Fernet: AES + HMAC; the key is derived from your passphrase with
PBKDF2). Drafts you reject or posts you delete must not be readable by anyone.
The branch keeps a single commit that is replaced on every save: no history of
old states, and no repository bloat from ciphertext that never compresses.

Layout (after decryption)::

    {"version": 1, "tg_offset": 0, "items": {"<cluster_id>": {...}}}

An item's "status" is one of:
    pending   every model failed; retried next run (up to max_pending_runs)
    skipped   no text / model said SKIP / validation failed. Never retried.
    duplicate same story as an earlier item under a new cluster id
    draft     waiting for your ✅/❌ in Telegram
    approved  will be published (by you, or automatically in auto mode)
    rejected  you pressed ❌
    expired   nobody answered in time, or approved too late to publish
    posted    done on every platform (or given up on some, see "platforms")
    failed    every platform gave up after max_platform_attempts
    deleted   taken down with the 🗑 button
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

log = logging.getLogger(__name__)

MIN_KEY_CHARS = 20
_SALT = b"habermk-state-v1"


class StateKeyError(RuntimeError):
    """The state can't be read with the configured STATE_KEY."""


def fernet_for(secret: str) -> Fernet:
    if len(secret) < MIN_KEY_CHARS:
        raise StateKeyError(f"STATE_KEY must be at least {MIN_KEY_CHARS} characters")
    raw = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), _SALT, 200_000)
    return Fernet(base64.urlsafe_b64encode(raw))


class StateStore:
    def __init__(self, path: Path | str, git_dir: Path | str | None = None,
                 branch: str = "state", secret: str | None = None):
        self.path = Path(path)
        self.git_dir = Path(git_dir) if git_dir else None
        self.branch = branch
        self._fernet = fernet_for(secret) if secret else None
        self._saved_digest: str | None = None   # what is on disk, to skip no-op writes
        self.data: dict[str, Any] = {"version": 1, "tg_offset": 0, "items": {}}

    @property
    def items(self) -> dict[str, dict[str, Any]]:
        return self.data["items"]

    @staticmethod
    def _serialize(data: dict[str, Any]) -> str:
        return json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True)

    def load(self) -> "StateStore":
        if not self.path.exists():
            return self
        raw = self.path.read_bytes().strip()
        if raw.startswith(b"{"):
            text = raw.decode("utf-8")
            encrypted_on_disk = False
        else:
            if self._fernet is None:
                raise StateKeyError("the saved state is encrypted but STATE_KEY is not set")
            try:
                text = self._fernet.decrypt(raw).decode("utf-8")
            except InvalidToken:
                raise StateKeyError("STATE_KEY does not match the saved state") from None
            encrypted_on_disk = True
        self.data = json.loads(text)
        self.data.setdefault("items", {})
        self.data.setdefault("tg_offset", 0)
        # A plain file with a key set gets encrypted on the next save.
        needs_rewrite = self._fernet is not None and not encrypted_on_disk
        self._saved_digest = None if needs_rewrite else self._digest(self._serialize(self.data))
        return self

    @staticmethod
    def _digest(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def save(self, message: str = "update state", push: bool = False) -> None:
        """Write atomically (only if something changed); with push=True also
        replace the single commit on the state branch."""
        text = self._serialize(self.data)
        digest = self._digest(text)
        if digest != self._saved_digest or not self.path.exists():
            payload = self._fernet.encrypt(text.encode("utf-8")) if self._fernet else text.encode("utf-8")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_bytes(payload)
            os.replace(tmp, self.path)
            self._saved_digest = digest
        if push and self.git_dir:
            self._git_push(message)

    def _git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(self.git_dir), *args],
                              capture_output=True, text=True, check=False)

    def _git_push(self, message: str) -> None:
        """One parentless commit, force-pushed: the branch never keeps history."""
        self._git("add", self.path.name)
        tree = self._git("write-tree").stdout.strip()
        head_tree = self._git("rev-parse", "-q", "--verify", "HEAD^{tree}").stdout.strip()
        if tree == head_tree:
            return  # nothing changed
        commit = self._git("commit-tree", tree, "-m", message)
        if commit.returncode != 0:
            raise RuntimeError(f"state commit failed: {commit.stderr.strip()}")
        self._git("update-ref", "HEAD", commit.stdout.strip())
        for _ in range(3):
            if self._git("push", "-q", "--force", "origin", f"HEAD:{self.branch}").returncode == 0:
                return
        raise RuntimeError("state push failed 3 times")

    def prune(self, now: datetime, days: int) -> int:
        """Forget items older than `days`, except approved ones still waiting to be
        published. Returns how many were removed."""
        cutoff = now - timedelta(days=days)
        old = [k for k, v in self.items.items()
               if v.get("status") != "approved" and datetime.fromisoformat(v["first_seen"]) < cutoff]
        for k in old:
            del self.items[k]
        return len(old)
