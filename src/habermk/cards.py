"""Phase 3: our own 1080×1080 image card for a post.

Only our template and our sentence: never the outlet's photo. The font is
Noto Sans (SIL Open Font License, see fonts/OFL.txt), bundled with the package.

    ┌──────────────────────────────┐
    │ ▬▬▬                          │
    │ БАДИЈАЛА КЛИК                │
    │                              │
    │  The sentence, as large as   │
    │  fits, wrapped by words.     │
    │                              │
    │ ──────────────────────────── │
    │ Извор: Outlet     21.10.2026 │
    └──────────────────────────────┘
"""
from __future__ import annotations

import io
from datetime import datetime
from functools import lru_cache
from importlib.resources import files
from typing import Any, Callable

from PIL import Image, ImageDraw, ImageFont

SIZE = 1080
MARGIN = 84
TEXT_TOP, TEXT_BOTTOM = 220, 870      # area for the sentence
FOOTER_Y = 905
MAX_BYTES = 950_000                   # Bluesky thumbnails must stay under 1 MB

COLORS = {"bg": "#10141C", "fg": "#F4F1EA", "accent": "#F5C518", "muted": "#9AA3B2"}


@lru_cache(maxsize=64)
def font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    path = files("habermk") / "fonts" / f"NotoSans-{weight}.ttf"
    return ImageFont.truetype(str(path), size)


def wrap(text: str, fnt: ImageFont.FreeTypeFont, width: int) -> list[str]:
    """Greedy word wrap. A single word wider than `width` stays on its own line."""
    lines: list[str] = []
    line = ""
    for word in text.split():
        candidate = f"{line} {word}".strip()
        if line and fnt.getlength(candidate) > width:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    return lines


def fit(text: str, width: int, height: int,
        sizes: range = range(78, 33, -2)) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    """The largest bold size at which the wrapped text fits the box."""
    for size in sizes:
        fnt = font("Bold", size)
        lines = wrap(text, fnt, width)
        line_h = round(size * 1.28)
        if len(lines) * line_h <= height and all(fnt.getlength(ln) <= width for ln in lines):
            return fnt, lines, line_h
    fnt = font("Bold", sizes[-1])
    return fnt, wrap(text, fnt, width), round(sizes[-1] * 1.28)


def render(sentence: str, outlet: str, when: datetime, brand: str) -> Image.Image:
    img = Image.new("RGB", (SIZE, SIZE), COLORS["bg"])
    d = ImageDraw.Draw(img)
    width = SIZE - 2 * MARGIN

    d.rectangle((MARGIN, 96, MARGIN + 120, 108), fill=COLORS["accent"])
    d.text((MARGIN, 128), brand.upper(), font=font("Bold", 34), fill=COLORS["accent"])

    fnt, lines, line_h = fit(sentence, width, TEXT_BOTTOM - TEXT_TOP)
    y = TEXT_TOP + (TEXT_BOTTOM - TEXT_TOP - len(lines) * line_h) // 2
    for ln in lines:
        d.text((MARGIN, y), ln, font=fnt, fill=COLORS["fg"])
        y += line_h

    d.line((MARGIN, FOOTER_Y, SIZE - MARGIN, FOOTER_Y), fill=COLORS["muted"], width=2)
    small = font("Regular", 34)
    date = when.strftime("%d.%m.%Y")
    date_w = small.getlength(date)
    source = f"Извор: {outlet}"
    while small.getlength(source) > width - date_w - 40 and len(source) > 10:
        source = source[:-2].rstrip() + "…"
    d.text((MARGIN, FOOTER_Y + 28), source, font=small, fill=COLORS["fg"])
    d.text((SIZE - MARGIN - date_w, FOOTER_Y + 28), date, font=small, fill=COLORS["muted"])
    return img


def to_jpeg(img: Image.Image) -> bytes:
    for quality in (90, 80, 70, 60):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=quality, optimize=True)
        if buf.tell() <= MAX_BYTES:
            break
    return buf.getvalue()


def card_for_item(item: dict[str, Any], brand: str) -> bytes:
    when = datetime.fromisoformat(item.get("drafted_at") or item["first_seen"])
    return to_jpeg(render(item["sentence"], item["outlet"], when, brand))


def card_maker(cfg: dict[str, Any], platform: str | None = None) -> Callable[[dict], bytes] | None:
    """The card function for a platform, or None when cards are off for it."""
    cards = cfg.get("cards") or {}
    if not cards.get("enabled"):
        return None
    if platform is not None and platform not in cards.get("platforms", []):
        return None
    brand = cards.get("brand", "")
    return lambda item: card_for_item(item, brand)
