"""Phase 0: does full-text extraction work on the outlets vesti.mk links today?

    python scripts/check_extraction.py --out probe/EXTRACT.md --stories 10

Uses exactly what the bot uses (robots.txt respected, honest User-Agent, up to
3 articles per story) and writes a table: which outlet, how much text, and the
first words, so a broken outlet shows up before the bot depends on it.
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from habermk.config import load_config
from habermk.extract import fetch_article_text
from habermk.sources.vesti import fetch_clusters


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("probe/EXTRACT.md"))
    ap.add_argument("--stories", type=int, default=10)
    args = ap.parse_args()
    cfg = load_config()
    src, min_chars = cfg["source"], cfg["extract"]["min_chars"]

    clusters = [c for c in fetch_clusters(src["url"], src["user_agent"])
                if c.article_count >= src["min_outlets"]][: args.stories]
    rows, per_outlet, stories_ok = [], Counter(), 0
    with httpx.Client(headers={"User-Agent": src["user_agent"]}, follow_redirects=True) as client:
        for c in clusters:
            story_ok = False
            for art in c.articles[:3]:
                text = fetch_article_text(art.url, src["user_agent"], client)
                ok = len(text) >= min_chars
                per_outlet[(art.outlet or urlsplit(art.url).netloc, ok)] += 1
                rows.append((c.rank, art.outlet, urlsplit(art.url).netloc, len(text), ok,
                             " ".join(text.split())[:120]))
                time.sleep(1)  # be gentle with the outlets
                if ok:
                    story_ok = True
                    break
            stories_ok += story_ok

    stamp = datetime.now(timezone.utc).isoformat(timespec="minutes")
    out = [
        "# Full-text extraction check",
        "",
        f"- Run: {stamp}",
        f"- Stories with usable text (≥{min_chars} chars from one of the first 3 articles): "
        f"**{stories_ok} of {len(clusters)}**",
        "",
        "| rank | outlet | host | chars | ok | text start |",
        "|---|---|---|---|---|---|",
    ]
    for rank, outlet, host, n, ok, start in rows:
        out.append(f"| {rank} | {outlet} | {host} | {n} | {'✅' if ok else '❌'} | "
                   f"{start.replace('|', '/')} |")
    failing = sorted({o for (o, ok) in per_outlet if not ok} - {o for (o, ok) in per_outlet if ok})
    if failing:
        out += ["", "Outlets that gave no usable text: " + ", ".join(failing)]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
