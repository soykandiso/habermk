import httpx
import pytest

from habermk.sources.vesti import (
    SourceLayoutError, clean_url, describe_page, parse_age_minutes, parse_clusters,
)

IDS = ["255191", "255160", "256235"]


def test_parses_top_clusters_in_page_order(vesti_html):
    clusters = parse_clusters(vesti_html)
    assert [c.cluster_id for c in clusters] == IDS
    assert [c.rank for c in clusters] == [0, 1, 2]


def test_lead_article_outlet_count_age(vesti_html):
    c = parse_clusters(vesti_html)[0]
    assert c.title.startswith("Почна имунизацијата против сезонски грип")
    assert c.lead.outlet == "360 Степени"
    assert c.lead.url.startswith("https://360stepeni.mk/pochna-imunizatsijata")
    assert c.article_count == 31
    assert c.age_minutes == 480
    assert c.category == "local"
    assert c.snippet.startswith("Министерот за здравство")


def test_related_articles_are_outlet_links_only(vesti_html):
    c = parse_clusters(vesti_html)[0]
    assert [a.outlet for a in c.related] == ["Пулс 24", "Нова Македонија", "Рацин", "МТВ 1", "Алфа"]
    urls = [a.url for a in c.articles]
    assert len(set(urls)) == len(urls)
    assert not any("//vesti.mk/" in u for u in urls)


def test_trending_and_latest_lists_are_not_stories(vesti_html):
    """The trending list links to clusters outside the top three, and the
    "latest" list has no cluster at all: neither may become a story."""
    assert len(parse_clusters(vesti_html)) == 3


def test_mobile_copy_alone_is_enough():
    html = """<div class="tvm-small" data-tv-cluster="255160" data-tv-cat="local">
      <h2 class="tvm-small-title"><a href="https://360stepeni.mk/a?utm_source=vesti.mk">Наслов</a></h2>
      <div class="tvm-meta"><div class="tvm-meta-left">
        <span class="tvm-meta-source">360 Степени</span><span>•</span><span>35 минути</span>
      </div><a href="https://vesti.mk/c/255160-potraga" class="tvm-plus">+ 29</a></div></div>"""
    c = parse_clusters(html)[0]
    assert (c.cluster_id, c.lead.outlet, c.article_count, c.age_minutes) == \
        ("255160", "360 Степени", 29, 35)
    assert c.lead.url == "https://360stepeni.mk/a"


def test_layout_change_fails_loudly():
    html = '<div data-tv-cluster="255191"><a href="https://vesti.mk/c/255191-x">31 вести</a></div>'
    with pytest.raises(SourceLayoutError):
        parse_clusters(html)


def test_page_without_clusters_returns_empty():
    assert parse_clusters("<html><body><a href='/category/x'>x</a></body></html>") == []


@pytest.mark.parametrize("text,minutes", [
    ("35 минути", 35), ("1 минута", 1), ("2 часа", 120), ("1 час", 60),
    ("1 ден", 1440), ("3 дена", 4320), ("20 секунди", 0), ("вчера", None),
])
def test_age(text, minutes):
    assert parse_age_minutes(text) == minutes


def test_describe_page_for_diagnosis():
    resp = httpx.Response(200, text="<html><title>Just a moment...</title><body>"
                          "<a href='/x'>a</a><script>var x=1</script>Checking</body></html>",
                          request=httpx.Request("GET", "https://vesti.mk/"))
    text = describe_page(resp)
    assert "Just a moment..." in text and "'data-tv-cluster' occurrences 0" in text
    assert "Checking" in text and "var x" not in text


def test_clean_url_keeps_real_query():
    assert clean_url("https://a.mk/x?id=5&utm_source=vesti.mk#top") == "https://a.mk/x?id=5"
