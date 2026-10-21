"""Phase 0: is the vesti.mk cluster ID stable over time?

    python scripts/probe_sources.py snapshot --data probe/snapshots.jsonl
    python scripts/probe_sources.py report   --data probe/snapshots.jsonl --out probe/REPORT.md

Run `snapshot` every 15 minutes for ~24 h (GitHub workflow probe.yml does this),
then read the report.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from habermk.config import load_config
from habermk.sources.vesti import fetch_clusters


def snapshot(data: Path, max_snapshots: int) -> None:
    lines = data.read_text(encoding="utf-8").splitlines() if data.exists() else []
    if len(lines) >= max_snapshots:
        print(f"already {len(lines)} snapshots, nothing to do")
        return
    cfg = load_config()["source"]
    clusters = fetch_clusters(cfg["url"], cfg["user_agent"])
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "clusters": [
            {"id": c.cluster_id, "rank": c.rank, "title": c.title, "count": c.article_count,
             "age": c.age_minutes, "urls": [a.url for a in c.articles]}
            for c in clusters
        ],
    }
    data.parent.mkdir(parents=True, exist_ok=True)
    with data.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"snapshot {len(lines) + 1}: {len(clusters)} clusters")


def report(data: Path) -> str:
    snaps = [json.loads(line) for line in data.read_text(encoding="utf-8").splitlines() if line]
    if not snaps:
        return "No snapshots yet."
    titles: dict[str, set[str]] = defaultdict(set)
    seen: dict[str, list[str]] = defaultdict(list)
    url_to_ids: dict[str, set[str]] = defaultdict(set)
    for s in snaps:
        for c in s["clusters"]:
            titles[c["id"]].add(c["title"])
            seen[c["id"]].append(s["ts"])
            for u in c["urls"]:
                url_to_ids[u].add(c["id"])

    first, last = snaps[0]["ts"], snaps[-1]["ts"]
    hours = max((datetime.fromisoformat(last) - datetime.fromisoformat(first)).total_seconds() / 3600, 1e-9)
    retitled = {cid: t for cid, t in titles.items() if len(t) > 1}
    split_urls = {u: ids for u, ids in url_to_ids.items() if len(ids) > 1}
    lifetimes = [
        (datetime.fromisoformat(v[-1]) - datetime.fromisoformat(v[0])).total_seconds() / 3600
        for v in seen.values()
    ]

    out = [
        "# vesti.mk cluster-ID stability report",
        "",
        f"- Snapshots: **{len(snaps)}** from {first} to {last} ({hours:.1f} h)",
        f"- Distinct cluster IDs: **{len(titles)}** (≈ {len(titles) / hours:.1f} new per hour)",
        f"- Average time a cluster stays in the top list: **{sum(lifetimes) / len(lifetimes):.1f} h**",
        f"- Clusters whose headline changed but ID stayed the same: **{len(retitled)}** "
        "(good: the ID survives headline changes)",
        f"- Article URLs that appeared under more than one cluster ID: **{len(split_urls)}** "
        f"of {len(url_to_ids)} (bad if high: the same story got a new ID)",
        "",
    ]
    if split_urls:
        out += ["## Examples of URLs under several cluster IDs", ""]
        for u, ids in list(split_urls.items())[:15]:
            out.append(f"- {u} → {', '.join(sorted(ids))}")
        out.append("")
    if retitled:
        out += ["## Examples of headline changes under one ID", ""]
        for cid, t in list(retitled.items())[:10]:
            out.append(f"- `{cid}`: " + " | ".join(sorted(t))[:300])
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["snapshot", "report"])
    ap.add_argument("--data", type=Path, default=Path("probe/snapshots.jsonl"))
    ap.add_argument("--out", type=Path)
    ap.add_argument("--max-snapshots", type=int, default=120, help="stop after ~30 h")
    args = ap.parse_args()
    if args.command == "snapshot":
        snapshot(args.data, args.max_snapshots)
    else:
        text = report(args.data)
        if args.out:
            args.out.write_text(text, encoding="utf-8")
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
