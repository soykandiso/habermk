"""Plain data classes shared across the pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Article:
    url: str
    outlet: str
    title: str = ""


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

    @property
    def articles(self) -> list[Article]:
        return [self.lead, *self.related]
