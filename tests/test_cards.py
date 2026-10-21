import io
from datetime import datetime

import pytest
from PIL import Image

from habermk import cards

WHEN = datetime.fromisoformat("2026-10-21T12:00:00+02:00")
SHORT = "Владата ја зголеми минималната плата на 24.000 денари од јануари."
LONG = ("Полицијата во Скопје пронашла две автоматски пушки и над 500 парчиња муниција кај "
        "Б.А. (24), кој според МВР е член на ИСИС и врбувал млади лица преку мрежите.")


def item(sentence=SHORT, outlet="Телма"):
    return {"sentence": sentence, "outlet": outlet, "drafted_at": WHEN.isoformat()}


def test_card_is_a_square_jpeg_under_the_bluesky_limit():
    data = cards.card_for_item(item(LONG), "Бадијала клик")
    img = Image.open(io.BytesIO(data))
    assert img.format == "JPEG" and img.size == (1080, 1080)
    assert len(data) < 1_000_000


def test_longer_sentence_gets_smaller_text_that_still_fits():
    width, height = 1080 - 2 * cards.MARGIN, cards.TEXT_BOTTOM - cards.TEXT_TOP
    f_short, lines_short, _ = cards.fit(SHORT, width, height)
    f_long, lines_long, line_h = cards.fit(LONG, width, height)
    assert f_long.size < f_short.size
    assert all(f_long.getlength(ln) <= width for ln in lines_long)
    assert len(lines_long) * line_h <= height


def test_max_length_sentence_fits(cfg):
    sentence = ("Министерството " * 30)[: cfg["validation"]["max_sentence_chars"] - 1] + "."
    width, height = 1080 - 2 * cards.MARGIN, cards.TEXT_BOTTOM - cards.TEXT_TOP
    fnt, lines, line_h = cards.fit(sentence, width, height)
    assert len(lines) * line_h <= height


@pytest.mark.parametrize("letter", list("ЃЌЉЊЏЅЈѓќљњџѕј"))
def test_macedonian_letters_have_real_glyphs(letter):
    """A missing glyph renders as the same 'tofu' box for every letter."""
    fnt = cards.font("Bold", 60)
    tofu = fnt.getmask("\U0010FFFD").getbbox()
    assert fnt.getmask(letter).getbbox() != tofu


def test_same_input_same_card():
    assert cards.card_for_item(item(), "Б") == cards.card_for_item(item(), "Б")


def test_card_maker_respects_config():
    on = {"cards": {"enabled": True, "brand": "Б", "platforms": ["telegram"]}}
    assert cards.card_maker(on, "telegram") is not None
    assert cards.card_maker(on, "bluesky") is None
    assert cards.card_maker(on) is not None  # drafts
    assert cards.card_maker({"cards": {"enabled": False}}, "telegram") is None
