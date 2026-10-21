"""Load non-secret settings from config.yaml."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]


def config_path() -> Path:
    """HABERMK_CONFIG, else ./config.yaml (repo checkout), else next to the source.

    The last one only exists for an editable install; a normal `pip install .`
    copies the package into site-packages without config.yaml.
    """
    if os.environ.get("HABERMK_CONFIG"):
        return Path(os.environ["HABERMK_CONFIG"])
    for candidate in (Path.cwd() / "config.yaml", ROOT / "config.yaml"):
        if candidate.exists():
            return candidate
    raise FileNotFoundError("config.yaml not found: run from the repo folder or set HABERMK_CONFIG")


def load_config(path: Path | str | None = None) -> dict[str, Any]:
    with open(path or config_path(), encoding="utf-8") as f:
        return yaml.safe_load(f)
