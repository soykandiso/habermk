"""Parse the top story clusters from vesti.mk.

Every story block carries its cluster id in ``data-tv-cluster`` (a number,
e.g. ``255191``), and the same story is rendered more than once (desktop
``tv-item`` and mobile ``tvm-*`` layouts, category blocks). We read each block,
merge the copies, and keep the order of first appearance as the ranking
("Вест #1" first).

Layout seen on 21 Oct 2026::

    <div class="tv-item" data-tv-cluster="255191" data-tv-cat="local">
      <span class="tv-source">360 Степени</span> • <span>8 часа</span>
      <h3><a class="tv-title" href="https://360stepeni.mk/...">Headline</a></h3>
      <div class="tv-excerpt">…</div>
      <div class="tv-sources"><a href="https://puls24.mk/...">Пулс 24</a> | …
        • <a href="https://vesti.mk/c/255191-slug" class="tv-sources-count">31 вести</a>
"""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from selectolax.lexbor import LexborHTMLParser as HTMLParser
from selectolax.lexbor import LexborNode as Node

from habermk.models import Article, Cluster

CLUSTER_ID = re.compile(r"^\d{3,12}$")
# vesti.mk cluster page links: /c/<id>-<slug>
CLUSTER_LINK = re.compile(r"//(?:www\.)?vesti\.mk/c/(\d{3,12})\b")
COUNT_RE = re.compile(r"(\d+)")
AGE_RE = re.compile(
    r"^(\d+)\s*(секунд\w*|минут\w*|час\w*|ден|дена|недел\w*|месец\w*)$"
)
AGE_MINUTES = {"сек": 0, "мин": 1, "час": 60, "ден": 1440, "нед": 10080, "мес": 43200}
VESTI_HOSTS = {"vesti.mk", "www.vesti.mk"}


class SourceLayoutError(RuntimeError):
    """The page no longer looks like we expect. Stop and alert, never guess."""


def clean_url(url: str) -> str:
    """Drop tracking parameters (utm_*) so the same article always has one URL."""
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query) if not k.startswith("utm_")]
    return urlunsplit(parts._replace(query=urlencode(query), fragment=""))


def parse_age_minutes(text: str) -> int | None:
    m = AGE_RE.match(text.strip())
    if not m:
        return None
    return int(m.group(1)) * AGE_MINUTES[m.group(2)[:3]]


def _external(href: str) -> bool:
    """A link to an outlet's article (not to vesti.mk itself)."""
    return href.startswith("http") and urlsplit(href).netloc.lower() not in VESTI_HOSTS


def _text(node: Node | None) -> str:
    return " ".join(node.text().split()) if node is not None else ""


def _parse_block(block: Node, cluster_id: str) -> Cluster | None:
    headline = next((a for a in block.css("h2 a, h3 a")
                     if _external(a.attributes.get("href") or "")), None)
    if headline is None:
        return None
    lead_url = clean_url(headline.attributes["href"])
    title = _text(headline)

    related: list[Article] = []
    for a in block.css(".tv-sources a"):
        href = a.attributes.get("href") or ""
        if not _external(href):
            continue
        url = clean_url(href)
        if url != lead_url and all(r.url != url for r in related):
            related.append(Article(url=url, outlet=_text(a)))

    age = next((m for s in block.css("span") if (m := parse_age_minutes(_text(s))) is not None),
               None)

    # "31 вести" (desktop) or "+ 31" (mobile), both linking to the cluster page
    count = 0
    for a in block.css("a"):
        if CLUSTER_LINK.search(a.attributes.get("href") or ""):
            m = COUNT_RE.search(_text(a))
            count = max(count, int(m.group(1)) if m else 0)

    return Cluster(
        cluster_id=cluster_id,
        rank=0,
        title=title,
        lead=Article(url=lead_url, outlet=_text(block.css_first(".tv-source, .tvm-meta-source")),
                     title=title),
        related=related,
        article_count=count,
        age_minutes=age,
        snippet=_text(block.css_first(".tv-excerpt")),
        category=block.attributes.get("data-tv-cat") or "",
    )


def _merge(a: Cluster, b: Cluster) -> Cluster:
    """Combine two copies of the same story (desktop / mobile / category block)."""
    a.lead.outlet = a.lead.outlet or b.lead.outlet
    a.snippet = a.snippet or b.snippet
    a.category = a.category or b.category
    a.age_minutes = a.age_minutes if a.age_minutes is not None else b.age_minutes
    a.article_count = max(a.article_count, b.article_count)
    known = {r.url for r in a.related} | {a.lead.url}
    a.related += [r for r in b.related if r.url not in known]
    return a


def parse_clusters(html: str) -> list[Cluster]:
    """Return the story clusters in page order (rank 0 = first)."""
    tree = HTMLParser(html)
    clusters: dict[str, Cluster] = {}
    for block in tree.css("[data-tv-cluster]"):
        cid = (block.attributes.get("data-tv-cluster") or "").strip()
        if not CLUSTER_ID.match(cid):
            continue
        parsed = _parse_block(block, cid)
        if parsed is None:
            continue
        clusters[cid] = _merge(clusters[cid], parsed) if cid in clusters else parsed

    # Second, independent check: if the raw HTML still has cluster markers but
    # nothing was parsed, the layout changed. Fail loudly.
    raw_ids = set(re.findall(r'data-tv-cluster="(\d+)"', html)) | set(CLUSTER_LINK.findall(html))
    if raw_ids and not clusters:
        raise SourceLayoutError(
            f"vesti.mk: {len(raw_ids)} cluster ids in HTML but 0 parsed stories"
        )

    result = list(clusters.values())
    for i, c in enumerate(result):
        c.rank = i
    return result


def fetch_clusters(url: str, user_agent: str, timeout: float = 30) -> list[Cluster]:
    resp = httpx.get(
        url, headers={"User-Agent": user_agent}, timeout=timeout, follow_redirects=True
    )
    resp.raise_for_status()
    clusters = parse_clusters(resp.text)
    if not clusters:
        raise SourceLayoutError(f"vesti.mk: no clusters found on the page ({describe_page(resp)})")
    return clusters


def describe_page(resp: httpx.Response) -> str:
    """What we actually got, so a failure can be diagnosed from the log alone."""
    html = resp.text
    title = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    body = re.sub(r"<(script|style)\b.*?</\1>|<[^>]+>", " ", html, flags=re.S | re.I)
    return (
        f"final url {resp.url}, status {resp.status_code}, {len(html)} chars, "
        f"server {resp.headers.get('server', '?')}, "
        f"title {title.group(1).strip()[:80] if title else '-'!r}, "
        f"'data-tv-cluster' occurrences {html.count('data-tv-cluster')}, "
        f"'/c/' occurrences {html.count('/c/')}, "
        f"text start {' '.join(body.split())[:300]!r}"
    )
