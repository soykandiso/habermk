from pathlib import Path

import pytest

from habermk import config

REPO_CONFIG = Path(__file__).resolve().parents[1] / "config.yaml"


def test_finds_config_in_working_directory(tmp_path, monkeypatch):
    """A normal (non-editable) install has no config.yaml next to the package."""
    (tmp_path / "config.yaml").write_text(REPO_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "ROOT", tmp_path / "site-packages")
    monkeypatch.delenv("HABERMK_CONFIG", raising=False)
    assert config.config_path() == tmp_path / "config.yaml"
    assert config.load_config()["source"]["url"] == "https://vesti.mk/"


def test_env_variable_wins(tmp_path, monkeypatch):
    custom = tmp_path / "other.yaml"
    custom.write_text("source: {url: x}\n", encoding="utf-8")
    monkeypatch.setenv("HABERMK_CONFIG", str(custom))
    assert config.load_config()["source"]["url"] == "x"


def test_missing_config_is_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "ROOT", tmp_path / "nowhere")
    monkeypatch.delenv("HABERMK_CONFIG", raising=False)
    with pytest.raises(FileNotFoundError, match="config.yaml not found"):
        config.config_path()
