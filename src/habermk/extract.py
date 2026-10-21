"""Get the full text of an original news article."""
from __future__ import annotations

import json
import logging
import re
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx
import trafilatura
from selectolax.lexbor import LexborHTMLParser as HTMLParser

from habermk.models import Article, Cluster

log = logging.getLogger(__name__)

_robots_cache: dict[str, RobotFileParser | None] = {}


def allowed_by_robots(url: str, user_agent: str, client: httpx.Client) -> bool:
    """Respect each outlet's robots.txt. If it can't be read, assume allowed."""
    parts = urlsplit(url)
    base = f"{parts.scheme}://{parts.netloc}"
    if base not in _robots_cache:
        try:
            resp = client.get(base + "/robots.txt", timeout=10)
            if resp.status_code >= 400:
                _robots_cache[base] = None
            else:
                rp = RobotFileParser()
                rp.parse(resp.text.splitlines())
                _robots_cache[base] = rp
        except httpx.HTTPError:
            _robots_cache[base] = None
    rp = _robots_cache[base]
    return rp is None or rp.can_fetch(user_agent, url)


def _jsonld_body(tree: HTMLParser) -> str:
    for node in tree.css('script[type="application/ld+json"]'):
        try:
            data = json.loads(node.text() or "")
        except ValueError:
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data])
        for item in items:
            if isinstance(item, dict) and isinstance(item.get("articleBody"), str):
                return item["articleBody"]
    return ""


def _meta_description(tree: HTMLParser) -> str:
    for sel in ('meta[property="og:description"]', 'meta[name="description"]'):
        node = tree.css_first(sel)
        if node and node.attributes.get("content"):
            return node.attributes["content"]
    return ""


def extract_text(html: str, url: str = "") -> str:
    """Article body text: trafilatura first, then JSON-LD, then meta description."""
    text = trafilatura.extract(
        html, url=url or None, include_comments=False, include_tables=False,
        favor_precision=True,
    ) or ""
    if len(text) < 250:
        tree = HTMLParser(html)
        text = max([text, _jsonld_body(tree), _meta_description(tree)], key=len)
    return re.sub(r"[ \t]+", " ", text).strip()


def fetch_article_text(url: str, user_agent: str, client: httpx.Client) -> str:
    """Download and extract one article. Returns "" when not allowed / failed."""
    if not allowed_by_robots(url, user_agent, client):
        log.info("robots.txt disallows %s", url)
        return ""
    try:
        resp = client.get(url, timeout=20)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        log.warning("fetch failed %s: %s", url, e)
        return ""
    return extract_text(resp.text, url)


def best_texts(cluster: Cluster, cfg: dict, client: httpx.Client,
               want: int = 1, tries: int = 3) -> list[tuple[Article, str]]:
    """Up to `want` (article, text) pairs long enough for the model, longest first.

    Looks at the lead and then related articles, at most `tries` downloads.
    """
    ua = cfg["source"]["user_agent"]
    found: list[tuple[Article, str]] = []
    for art in cluster.articles[:tries]:
        text = fetch_article_text(art.url, ua, client)
        if len(text) >= cfg["extract"]["min_chars"]:
            if not art.title:
                art = Article(url=art.url, outlet=art.outlet, title=cluster.title)
            found.append((art, text[: cfg["extract"]["max_chars"]]))
            if len(found) >= want:
                break
    return sorted(found, key=lambda p: len(p[1]), reverse=True)
