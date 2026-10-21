import json
import subprocess
from datetime import datetime, timedelta

from habermk.dedupe import duplicate_of
from habermk.models import Article, Cluster
from habermk.state import StateStore

NOW = datetime.fromisoformat("2026-10-21T12:00:00+02:00")


def cluster(cid, title, url):
    return Cluster(cluster_id=cid, rank=0, title=title, lead=Article(url=url, outlet="СДК"))


def item(title, urls, hours_ago=1, status="posted"):
    return {"title": title, "urls": urls, "status": status,
            "first_seen": (NOW - timedelta(hours=hours_ago)).isoformat()}


def test_same_article_url_under_new_cluster_id_is_duplicate():
    items = {"old": item("Сосема друг наслов", ["https://sdk.mk/a"])}
    assert duplicate_of(cluster("new", "Нов наслов", "https://sdk.mk/a"), items, NOW, 0.8, 48) == "old"


def test_retitled_story_is_duplicate():
    items = {"old": item("Владата ја донесе одлуката – ова се промените", ["https://x.mk/1"])}
    c = cluster("new", "Владата ја донесе одлуката: ова се промените!", "https://y.mk/2")
    assert duplicate_of(c, items, NOW, 0.8, 48) == "old"


def test_old_similar_title_is_not_duplicate():
    items = {"old": item("Владата ја донесе одлуката", ["https://x.mk/1"], hours_ago=72)}
    assert duplicate_of(cluster("new", "Владата ја донесе одлуката", "https://y.mk/2"),
                        items, NOW, 0.8, 48) is None


def test_different_story_is_not_duplicate():
    items = {"old": item("Пожар во Тетово", ["https://x.mk/1"])}
    assert duplicate_of(cluster("new", "Нова плата за учителите", "https://y.mk/2"),
                        items, NOW, 0.8, 48) is None


def test_state_roundtrip_and_prune(tmp_path):
    store = StateStore(tmp_path / "state.json")
    store.load()
    store.items["a"] = item("A", [], hours_ago=24 * 20)
    store.items["b"] = item("B", [], hours_ago=1)
    store.items["c"] = item("C", [], hours_ago=24 * 20, status="approved")
    store.data["tg_offset"] = 42
    store.save()
    again = StateStore(tmp_path / "state.json").load()
    assert again.data["tg_offset"] == 42
    assert again.prune(NOW, 14) == 1
    assert set(again.items) == {"b", "c"}


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_save_with_push_commits_to_state_branch(tmp_path):
    remote, work = tmp_path / "remote.git", tmp_path / "wt"
    git("init", "-q", "--bare", str(remote), cwd=tmp_path)
    git("init", "-q", "-b", "state", str(work), cwd=tmp_path)
    git("config", "user.email", "t@t", cwd=work)
    git("config", "user.name", "t", cwd=work)
    git("remote", "add", "origin", str(remote), cwd=work)

    store = StateStore(work / "state.json", git_dir=work)
    store.items["a"] = item("A", [])
    store.save("post a telegram", push=True)
    store.save("no change", push=True)  # nothing to commit: no error

    out = subprocess.run(["git", "--git-dir", str(remote), "show", "state:state.json"],
                         capture_output=True, text=True, check=True).stdout
    assert json.loads(out)["items"]["a"]["title"] == "A"
    log = subprocess.run(["git", "--git-dir", str(remote), "log", "--format=%s", "state"],
                         capture_output=True, text=True, check=True).stdout.split("\n")
    assert log[0] == "post a telegram"
