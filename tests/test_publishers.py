from types import SimpleNamespace

import httpx
from fakes import FakeTelegram

from habermk.approval import send_draft
from habermk.publishers.bluesky import BlueskyPublisher
from habermk.publishers.facebook import FacebookPublisher
from habermk.publishers.telegram import TelegramPublisher

ITEM = {"sentence": "Владата усвои измени.", "outlet": "СДК", "url": "https://sdk.mk/a",
        "title": "Наслов", "evidence": "Доказ.", "drafted_at": "2026-10-21T12:00:00+02:00"}
CARD = b"\xff\xd8jpeg"


def test_telegram_with_card_sends_photo_with_source_in_caption():
    tg = FakeTelegram()
    TelegramPublisher(tg, "@ch", card=lambda item: CARD).post(ITEM)
    (method, params), = tg.calls
    assert method == "sendPhoto" and params["photo"] == CARD
    assert params["caption"].endswith("— СДК: https://sdk.mk/a")


def test_telegram_without_card_sends_text_with_preview():
    tg = FakeTelegram()
    TelegramPublisher(tg, "@ch").post(ITEM)
    assert tg.calls[0][0] == "sendMessage"


def test_telegram_long_caption_falls_back_to_text():
    tg = FakeTelegram()
    TelegramPublisher(tg, "@ch", card=lambda item: CARD).post({**ITEM, "url": "https://x.mk/" + "a" * 1100})
    assert tg.calls[0][0] == "sendMessage"


class FakeBsky:
    def __init__(self, existing_url=None):
        self.existing_url = existing_url
        self.uploaded, self.posts = [], []

    def get_author_feed(self, actor, limit):
        feed = []
        if self.existing_url:
            ext = SimpleNamespace(uri=self.existing_url)
            feed.append(SimpleNamespace(post=SimpleNamespace(embed=SimpleNamespace(external=ext),
                                                             uri="at://old")))
        return SimpleNamespace(feed=feed)

    def upload_blob(self, data):
        self.uploaded.append(data)
        from atproto_client.models.blob_ref import BlobRef, IpldLink
        return SimpleNamespace(blob=BlobRef(mime_type="image/jpeg", size=len(data),
                                            ref=IpldLink(link="bafkreih" + "a" * 52)))

    def send_post(self, text, embed, langs):
        self.posts.append((text, embed, langs))
        return SimpleNamespace(uri="at://new")


def test_bluesky_card_becomes_link_card_thumbnail():
    client = FakeBsky()
    uri = BlueskyPublisher("h", "p", client=client, card=lambda item: CARD).post(ITEM)
    assert uri == "at://new" and client.uploaded == [CARD]
    text, embed, langs = client.posts[0]
    assert embed.external.uri == "https://sdk.mk/a" and embed.external.thumb is not None
    assert text.endswith("— СДК") and langs == ["mk"]


def test_bluesky_does_not_repost_after_a_crash():
    client = FakeBsky(existing_url="https://sdk.mk/a")
    assert BlueskyPublisher("h", "p", client=client).post(ITEM) == "at://old"
    assert client.posts == []


def test_facebook_posts_link_and_named_source():
    seen = {}

    def handler(request):
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"id": "123_456"})

    pub = FacebookPublisher("123", "tok", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert pub.post(ITEM) == "123_456"
    assert "link=https%3A%2F%2Fsdk.mk%2Fa" in seen["body"]


def test_facebook_error_raises():
    def handler(request):
        return httpx.Response(400, json={"error": {"type": "OAuthException", "message": "bad"}})

    pub = FacebookPublisher("1", "t", client=httpx.Client(transport=httpx.MockTransport(handler)))
    try:
        pub.post(ITEM)
    except RuntimeError as e:
        assert "OAuthException" in str(e)
    else:
        raise AssertionError("expected an error")


def test_draft_shows_card_before_buttons():
    tg = FakeTelegram()
    send_draft(tg, "111", "k", ITEM, card=lambda item: CARD)
    assert [m for m, _ in tg.calls] == ["sendPhoto", "sendMessage"]


def test_draft_still_sent_when_card_fails():
    tg = FakeTelegram()
    tg.fail.add("sendPhoto")
    send_draft(tg, "111", "k", ITEM, card=lambda item: CARD)
    assert tg.calls[-1][0] == "sendMessage"
