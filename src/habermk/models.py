"""Plain data classes shared across the pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass
class Article:
    url: str
    outlet: str
    title: str = ""

    @property
    def source(self) -> str:
        """The name to credit: the outlet, or its domain if the name is missing.
        A post must never go out without a named source (copyright Art. 52)."""
        if self.outlet.strip():
            return self.outlet.strip()
        return urlsplit(self.url).netloc.lower().removeprefix("www.")


@dataclass
class Cluster:
    """One story on the aggregator: the lead article plus related ones."""

    cluster_id: str          # stable aggregator id, e.g. vesti.mk "/c/<id>"
    rank: int                # 0 = top story
    title: str               # lead headline (may change over time)
    lead: Article
    related: list[Article] = field(default_factory=list)
    article_count: int = 0   # "46 вести"
    age_minutes: int | None = None
    snippet: str = ""
    category: str = ""       # vesti.mk data-tv-cat: local, world, sport, ...

    @property
    def articles(self) -> list[Article]:
        return [self.lead, *self.related]
