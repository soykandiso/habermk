import httpx

from habermk import extract
from habermk.extract import best_texts, extract_text, fetch_article_text
from habermk.models import Article, Cluster


def test_extracts_article_body_without_menus(article_html):
    text = extract_text(article_html)
    assert "над 500 парчиња муниција" in text
    assert "Б.А. (24)" in text
    assert "Најчитано" not in text
    assert "Сите права задржани" not in text


def test_jsonld_fallback_for_script_rendered_pages():
    body = "Владата усвои измени на уредбата за минимална плата. " * 10
    html = ('<html><head><script type="application/ld+json">'
            '{"@type":"NewsArticle","articleBody":"%s"}</script></head>'
            '<body><div id="app"></div></body></html>' % body)
    assert extract_text(html).startswith("Владата усвои измени")


def _client(pages: dict[str, tuple[int, str]]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        status, body = pages.get(str(request.url), (404, ""))
        return httpx.Response(status, text=body)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_robots_txt_is_respected(article_html):
    extract._robots_cache.clear()
    client = _client({
        "https://blocked.mk/robots.txt": (200, "User-agent: *\nDisallow: /\n"),
        "https://blocked.mk/a": (200, article_html),
    })
    assert fetch_article_text("https://blocked.mk/a", "habermk-bot", client) == ""


def test_best_texts_skips_short_articles(article_html, cfg):
    extract._robots_cache.clear()
    client = _client({
        "https://short.mk/a": (200, "<html><body><p>Видео.</p></body></html>"),
        "https://makfax.com.mk/a": (200, article_html),
    })
    cluster = Cluster(cluster_id="x" * 20, rank=0, title="Наслов",
                      lead=Article(url="https://short.mk/a", outlet="Кратко"),
                      related=[Article(url="https://makfax.com.mk/a", outlet="Макфакс")])
    found = best_texts(cluster, cfg, client, want=2)
    assert [a.outlet for a, _ in found] == ["Макфакс"]
    assert found[0][0].title == "Наслов"
