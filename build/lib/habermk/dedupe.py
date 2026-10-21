"""Never post one story twice, even when the aggregator gives it a new cluster id."""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Any

from habermk.models import Cluster
from habermk.validate import normalize


def _title_key(title: str) -> str:
    return re.sub(r"[^\w ]", "", normalize(title))


def title_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _title_key(a), _title_key(b)).ratio()


def duplicate_of(cluster: Cluster, items: dict[str, dict[str, Any]], now: datetime,
                 min_similarity: float, window_hours: int) -> str | None:
    """The cluster id of an earlier item for the same story, or None.

    The cluster's own id is not checked here; the caller handles known ids.
    """
    urls = {a.url for a in cluster.articles}
    cutoff = now - timedelta(hours=window_hours)
    for cid, item in items.items():
        if cid == cluster.cluster_id:
            continue
        if urls & set(item.get("urls", [])):
            return cid
        if datetime.fromisoformat(item["first_seen"]) >= cutoff and \
                title_similarity(cluster.title, item.get("title", "")) >= min_similarity:
            return cid
    return None
