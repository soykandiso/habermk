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


def test_extraction_check_report(tmp_path, monkeypatch):
    import check_extraction

    from habermk.models import Article, Cluster

    clusters = [
        Cluster(cluster_id="1", rank=0, title="А", article_count=10,
                lead=Article(url="https://bad.mk/a", outlet="Лошо"),
                related=[Article(url="https://good.mk/b", outlet="Добро")]),
        Cluster(cluster_id="2", rank=1, title="Б", article_count=10,
                lead=Article(url="https://bad.mk/c", outlet="Лошо")),
        Cluster(cluster_id="3", rank=2, title="В", article_count=1,  # too few outlets
                lead=Article(url="https://good.mk/d", outlet="Добро")),
    ]
    texts = {"https://good.mk/b": "Текст. " * 100}
    monkeypatch.setattr(check_extraction, "fetch_clusters", lambda *a: clusters)
    monkeypatch.setattr(check_extraction, "fetch_article_text", lambda url, *a: texts.get(url, ""))
    monkeypatch.setattr(check_extraction.time, "sleep", lambda s: None)
    out = tmp_path / "EXTRACT.md"
    monkeypatch.setattr(sys, "argv", ["x", "--out", str(out)])
    assert check_extraction.main() == 0
    text = out.read_text(encoding="utf-8")
    assert "**1 of 2**" in text
    assert "Outlets that gave no usable text: Лошо" in text
