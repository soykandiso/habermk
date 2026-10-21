"""Phase 0: run the same prompt on several models and write a table to judge.

    python scripts/eval_models.py                       # models from config.yaml
    python scripts/eval_models.py --stories 10 --models groq:openai/gpt-oss-120b

Output: eval/eval_<time>.csv (opens in Excel; one row per story × model) plus
eval/texts/<cluster>.txt with the full article text each model saw.
"""
from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx

from habermk.config import load_config
from habermk.extract import best_texts
from habermk.formatting import platform_errors
from habermk.llm.providers import ModelError
from habermk.llm.router import Router
from habermk.logs import setup_logging
from habermk.sources.vesti import fetch_clusters
from habermk.validate import LLMFormatError, check, first_word_warning

COLUMNS = [
    "story", "rank", "cluster_id", "articles", "outlet", "headline", "url", "model",
    "status", "sentence", "evidence", "problems",
    "YOUR_macedonian_1to5", "YOUR_correct_Y_N", "YOUR_invented_fact_Y_N", "YOUR_notes",
    "article_start",
]


def main() -> int:
    cfg = load_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--stories", type=int, default=cfg["eval"]["stories"])
    ap.add_argument("--models", default=",".join(cfg["eval"]["models"]),
                    help="comma-separated provider:model list")
    ap.add_argument("--outdir", type=Path, default=Path("eval"))
    args = ap.parse_args()
    setup_logging()

    model_ids = [m.strip() for m in args.models.split(",") if m.strip()]
    router = Router.from_config(cfg["llm"], only=model_ids)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    (args.outdir / "texts").mkdir(parents=True, exist_ok=True)
    out_path = args.outdir / f"eval_{stamp}.csv"

    clusters = fetch_clusters(cfg["source"]["url"], cfg["source"]["user_agent"])
    eligible = [c for c in clusters if c.article_count >= cfg["source"]["min_outlets"]]
    picked = eligible[: args.stories]
    logging.info("%d clusters, %d eligible, evaluating %d", len(clusters), len(eligible), len(picked))

    stats: dict[str, Counter] = {m: Counter() for m in model_ids}
    headers = {"User-Agent": cfg["source"]["user_agent"]}
    # utf-8-sig = UTF-8 with BOM, so Excel shows Cyrillic correctly.
    with httpx.Client(headers=headers, follow_redirects=True) as client, \
            out_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for n, cluster in enumerate(picked, 1):
            found = best_texts(cluster, cfg, client)
            art, text = found[0] if found else (cluster.lead, "")
            (args.outdir / "texts" / f"{cluster.cluster_id}.txt").write_text(
                f"{cluster.title}\n{art.source} — {art.url}\n\n{text}", encoding="utf-8")
            logging.info("[%d/%d] %s (%d chars)", n, len(picked), cluster.title[:70], len(text))
            base = {
                "story": n, "rank": cluster.rank, "cluster_id": cluster.cluster_id,
                "articles": cluster.article_count, "outlet": art.source,
                "headline": art.title or cluster.title, "url": art.url,
                "article_start": text[:1500],
            }
            for spec in router.specs:
                row = dict(base, model=spec.id)
                if not text:
                    row.update(status="NO_TEXT", problems="no article text could be extracted")
                else:
                    try:
                        result = router.call_one(spec, row["headline"], art.source, text)
                        problems = check(result, text, cfg["validation"])
                        if result["status"] == "OK":
                            problems += platform_errors(result["sentence"], art.source, art.url,
                                                        cfg["platforms"])
                        status = result["status"]
                        if status == "OK" and problems:
                            status = "REJECTED"
                        if status == "OK":
                            warning = first_word_warning(result["sentence"], text)
                            problems += [f"warning: {warning}"] if warning else []
                        row.update(status=status, sentence=result["sentence"],
                                   evidence=result["evidence"],
                                   problems="; ".join(problems) or "passed all checks")
                    except (ModelError, LLMFormatError) as e:
                        row.update(status="ERROR", problems=str(e)[:500])
                stats[spec.id][row["status"]] += 1
                writer.writerow(row)
            f.flush()

    summary = [f"## Model evaluation — {len(picked)} stories", "",
               "| model | OK (passed) | REJECTED by checks | SKIP | ERROR | NO_TEXT |",
               "|---|---|---|---|---|---|"]
    for m, c in stats.items():
        summary.append(f"| {m} | {c['OK']} | {c['REJECTED']} | {c['SKIP']} | {c['ERROR']} | {c['NO_TEXT']} |")
    summary += ["", f"Table: `{out_path}` (download the *eval-results* artifact)."]
    text = "\n".join(summary)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
