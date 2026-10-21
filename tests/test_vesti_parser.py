import re

import pytest

from habermk.sources.vesti import (
    SourceLayoutError, clean_url, parse_age_minutes, parse_clusters,
)


def test_parses_top_clusters_in_page_order(vesti_html):
    clusters = parse_clusters(vesti_html)
    assert [c.cluster_id for c in clusters] == [
        "yslP7aABy7_6fWyWFLX2", "Ab3dEf6hIj9kLmNoPq12", "ZZtop_story-0000001",
    ]
    assert [c.rank for c in clusters] == [0, 1, 2]


def test_lead_article_outlet_and_clean_url(vesti_html):
    c = parse_clusters(vesti_html)[0]
    assert c.title.startswith("(Фото/Видео) Автоматски пушки")
    assert c.lead.outlet == "Макфакс"
    assert c.lead.url == "https://makfax.com.mk/crna-hronika/avtomatski-pushki-otkrieni-vo-skopje/"
    assert "utm_" not in c.lead.url
    assert c.article_count == 46
    assert c.age_minutes == 120
    assert c.snippet.startswith("Против Б.А. (24)")


def test_mobile_and_desktop_copies_are_merged(vesti_html):
    c = parse_clusters(vesti_html)[0]
    outlets = [a.outlet for a in c.related]
    # ТВ 21 / Денес Магазин only in the mobile copy, Алфа / Денешен only in desktop
    assert outlets == ["ТВ 21", "Денес Магазин", "Алфа", "Денешен"]
    assert len({a.url for a in c.articles}) == len(c.articles)


def test_highest_article_count_wins(vesti_html):
    assert parse_clusters(vesti_html)[1].article_count == 13


@pytest.mark.parametrize("prefix,suffix", [
    ("https://vesti.mk/c/", ""),
    ("https://www.vesti.mk/c/", "/"),
    ("/c/", "/nekoj-slug"),
])
def test_absolute_and_slugged_cluster_links(vesti_html, prefix, suffix):
    html = re.sub(r'href="/c/([^"]+)"', lambda m: f'href="{prefix}{m.group(1)}{suffix}"', vesti_html)
    # vesti.mk's own links inside a card must not count as articles or outlets
    html = html.replace("<h2>", '<a href="https://vesti.mk/category/hronika">Хроника</a><h2>', 1)
    clusters = parse_clusters(html)
    assert [c.cluster_id for c in clusters] == [
        "yslP7aABy7_6fWyWFLX2", "Ab3dEf6hIj9kLmNoPq12", "ZZtop_story-0000001",
    ]
    assert clusters[0].lead.outlet == "Макфакс"
    assert all("vesti.mk" not in a.url for c in clusters for a in c.articles)


def test_layout_change_fails_loudly():
    html = '<div><a href="/c/yslP7aABy7_6fWyWFLX2">46 вести</a></div>'  # no headline
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
    import httpx

    from habermk.sources.vesti import describe_page

    resp = httpx.Response(200, text="<html><title>Just a moment...</title><body>"
                          "<a href='/x'>a</a><script>var x=1</script>Checking</body></html>",
                          request=httpx.Request("GET", "https://vesti.mk/"))
    text = describe_page(resp)
    assert "Just a moment..." in text and "'/c/' occurrences 0" in text and "Checking" in text
    assert "var x" not in text


def test_clean_url_keeps_real_query():
    assert clean_url("https://a.mk/x?id=5&utm_source=vesti.mk#top") == "https://a.mk/x?id=5"
