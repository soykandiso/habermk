import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import probe_sources  # noqa: E402


def snap(ts, clusters):
    return json.dumps({"ts": ts, "clusters": clusters}, ensure_ascii=False)


def test_report_detects_retitles_and_split_urls(tmp_path):
    data = tmp_path / "s.jsonl"
    data.write_text("\n".join([
        snap("2026-10-21T10:00:00+00:00", [{"id": "1", "title": "А", "urls": ["https://a.mk/1"]}]),
        snap("2026-10-21T12:00:00+00:00", [{"id": "1", "title": "Б", "urls": ["https://a.mk/1"]},
                                           {"id": "2", "title": "В", "urls": ["https://a.mk/1"]}]),
    ]), encoding="utf-8")
    text = probe_sources.report(data)
    assert "Snapshots: **2**" in text
    assert "headline changed but ID stayed the same: **1**" in text
    assert "more than one cluster ID: **1**" in text
    assert "new per hour" in text


def test_single_snapshot_has_no_rate(tmp_path):
    data = tmp_path / "s.jsonl"
    data.write_text(snap("2026-10-21T10:00:00+00:00", [{"id": "1", "title": "А", "urls": []}]),
                    encoding="utf-8")
    assert "new per hour" not in probe_sources.report(data)
