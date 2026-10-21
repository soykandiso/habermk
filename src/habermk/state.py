"""Run state: one JSON file, kept on the `state` git branch in GitHub Actions.

Layout::

    {"version": 1, "tg_offset": 0, "items": {"<cluster_id>": {...}}}

An item's "status" is one of:
    pending   every model failed; retried next run (up to max_pending_runs)
    skipped   no text / model said SKIP / validation failed. Never retried.
    duplicate same story as an earlier item under a new cluster id
    draft     waiting for your ✅/❌ in Telegram
    approved  will be published (by you, or automatically in auto mode)
    rejected  you pressed ❌
    expired   nobody answered within draft_ttl_hours
    posted    done on every platform (or given up on some, see "platforms")
    failed    every platform gave up after max_platform_attempts
    deleted   taken down with the 🗑 button
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class StateStore:
    def __init__(self, path: Path | str, git_dir: Path | str | None = None,
                 branch: str = "state"):
        self.path = Path(path)
        self.git_dir = Path(git_dir) if git_dir else None
        self.branch = branch
        self.data: dict[str, Any] = {"version": 1, "tg_offset": 0, "items": {}}

    @property
    def items(self) -> dict[str, dict[str, Any]]:
        return self.data["items"]

    def load(self) -> "StateStore":
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
            self.data.setdefault("items", {})
            self.data.setdefault("tg_offset", 0)
        return self

    def save(self, message: str = "update state", push: bool = False) -> None:
        """Write atomically; with push=True also commit and push the state branch."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1, sort_keys=True),
                       encoding="utf-8")
        os.replace(tmp, self.path)
        if push and self.git_dir:
            self._git_push(message)

    def _git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(self.git_dir), *args],
                              capture_output=True, text=True, check=False)

    def _git_push(self, message: str) -> None:
        self._git("add", self.path.name)
        if self._git("diff", "--cached", "--quiet").returncode == 0:
            return  # nothing changed
        commit = self._git("commit", "-q", "-m", message)
        if commit.returncode != 0:
            raise RuntimeError(f"state commit failed: {commit.stderr.strip()}")
        for _ in range(3):
            if self._git("push", "-q", "origin", f"HEAD:{self.branch}").returncode == 0:
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
