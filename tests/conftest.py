from __future__ import annotations

from pathlib import Path

import pytest

from habermk.config import load_config

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def cfg():
    return load_config()


@pytest.fixture
def vesti_html():
    return (FIXTURES / "vesti_top.html").read_text(encoding="utf-8")


@pytest.fixture
def article_html():
    return (FIXTURES / "article.html").read_text(encoding="utf-8")
