"""Parse the "топ.ВЕСТИ" story clusters from vesti.mk.

The page renders every top story twice (a mobile and a desktop layout) with
Tailwind utility classes that change often. So we do not rely on CSS classes:
each story is found through its stable cluster link ``/c/<id>`` and we read the
smallest block of HTML around that link that belongs to this story only.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from selectolax.lexbor import LexborHTMLParser as HTMLParser
from selectolax.lexbor import LexborNode as Node

from habermk.models import Article, Cluster

# "/c/<id>", also absolute ("https://vesti.mk/c/<id>") and with a slug or slash.
CLUSTER_HREF = re.compile(
    r"^(?:https?://(?:www\.)?vesti\.mk)?/c/([A-Za-z0-9_-]{8,40})(?:/[^?#]*)?(?:[?#].*)?$"
)
RAW_CLUSTER = re.compile(
    r"""href=["'](?:https?://(?:www\.)?vesti\.mk)?/c/([A-Za-z0-9_-]{8,40})"""
)
COUNT_RE = re.compile(r"(\d+)\s*вест")
AGE_RE = re.compile(
    r"^(\d+)\s*(секунд\w*|минут\w*|час\w*|ден|дена|недел\w*|месец\w*)$"
)
AGE_MINUTES = {"сек": 0, "мин": 1, "час": 60, "ден": 1440, "нед": 10080, "мес": 43200}


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


def cluster_id(href: str) -> str | None:
    m = CLUSTER_HREF.match(href.strip())
    return m.group(1) if m else None


def _cluster_ids_in(node: Node) -> set[str]:
    return {cid for a in node.css('a[href*="/c/"]')
            if (cid := cluster_id(a.attributes.get("href") or ""))}


def _card_for(link: Node) -> Node:
    """Climb from the /c/ link to the largest ancestor holding only this story."""
    card = link
    while card.parent is not None and len(_cluster_ids_in(card.parent)) == 1:
        card = card.parent
    return card


def _is_vesti(href: str) -> bool:
    return urlsplit(href).netloc.lower().removeprefix("www.") == "vesti.mk"


def _is_homepage(href: str) -> bool:
    parts = urlsplit(href)
    return parts.scheme.startswith("http") and parts.path in ("", "/") and not parts.query


def _parse_card(card: Node, cluster_id: str, count_text: str) -> Cluster | None:
    headline = next(
        (a for h2 in card.css("h2") for a in h2.css('a[href^="http"]')
         if not _is_vesti(a.attributes.get("href") or "")), None
    )
    if headline is None:
        return None
    lead_url = clean_url(headline.attributes["href"])
    title = headline.text(strip=True)

    lead_outlet = ""
    related: list[Article] = []
    for a in card.css('a[href^="http"]'):
        href = a.attributes.get("href") or ""
        if _is_vesti(href):
            continue
        if _is_homepage(href):
            lead_outlet = lead_outlet or a.text(strip=True)
        elif a.attributes.get("title"):
            url = clean_url(href)
            if url == lead_url:
                lead_outlet = lead_outlet or a.attributes["title"]
            elif all(r.url != url for r in related):
                related.append(Article(url=url, outlet=a.attributes["title"].strip()))

    age = None
    for span in card.css("span"):
        age = parse_age_minutes(span.text(strip=True))
        if age is not None:
            break

    snippet = next((p.text(strip=True) for p in card.css("p") if p.text(strip=True)), "")
    m = COUNT_RE.search(count_text)
    return Cluster(
        cluster_id=cluster_id,
        rank=0,
        title=title,
        lead=Article(url=lead_url, outlet=lead_outlet, title=title),
        related=related,
        article_count=int(m.group(1)) if m else 0,
        age_minutes=age,
        snippet=snippet,
    )


def _merge(a: Cluster, b: Cluster) -> Cluster:
    """Combine the mobile and desktop copies of the same story."""
    a.lead.outlet = a.lead.outlet or b.lead.outlet
    a.snippet = a.snippet or b.snippet
    a.age_minutes = a.age_minutes if a.age_minutes is not None else b.age_minutes
    a.article_count = max(a.article_count, b.article_count)
    known = {r.url for r in a.related} | {a.lead.url}
    a.related += [r for r in b.related if r.url not in known]
    return a


def parse_clusters(html: str) -> list[Cluster]:
    """Return the top-story clusters in page order (rank 0 = first)."""
    tree = HTMLParser(html)
    clusters: dict[str, Cluster] = {}
    for link in tree.css('a[href*="/c/"]'):
        cid = cluster_id(link.attributes.get("href") or "")
        if not cid:
            continue
        parsed = _parse_card(_card_for(link), cid, link.text(strip=True))
        if parsed is None:
            continue
        cid = parsed.cluster_id
        clusters[cid] = _merge(clusters[cid], parsed) if cid in clusters else parsed

    # Second, independent check: if the raw HTML still has cluster links but
    # the card parser found none, the layout changed. Fail loudly.
    raw_ids = set(RAW_CLUSTER.findall(html))
    if raw_ids and not clusters:
        raise SourceLayoutError(
            f"vesti.mk: {len(raw_ids)} cluster links in HTML but 0 parsed cards"
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
    hrefs = re.findall(r"""href=["'](?:https?://[^/"']+)?(/[a-z]+)/""", html)
    common = sorted({h: hrefs.count(h) for h in hrefs}.items(), key=lambda kv: -kv[1])[:6]
    body = re.sub(r"<(script|style)\b.*?</\1>|<[^>]+>", " ", html, flags=re.S | re.I)
    return (
        f"final url {resp.url}, status {resp.status_code}, {len(html)} chars, "
        f"server {resp.headers.get('server', '?')}, title {title.group(1).strip()[:80] if title else '-'!r}, "
        f"'/c/' occurrences {html.count('/c/')}, top link paths {common}, "
        f"'/c/' samples {[html[max(i - 80, 0):i + 60] for i in _find_all(html, '/c/')[:3]]}, "
        f"text start {' '.join(body.split())[:300]!r}"
    )


def _find_all(text: str, needle: str) -> list[int]:
    return [m.start() for m in re.finditer(re.escape(needle), text)]
