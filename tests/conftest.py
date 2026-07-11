"""Shared pytest fixtures and lightweight LiteParse-result fakes.

The real `LiteParse.parse()` result objects are attribute-based (page.text,
page.text_items, item.x/y/width/height/text, etc.) rather than dicts, so all
the fakes here are simple objects exposing exactly those attributes. Using
duck-typed fakes instead of mocking the whole `liteparse` package lets the
tests exercise the real logic in `evaluate.py` / `quality_check.py` / `app.py`
without needing an actual document or the (slow, native) LiteParse parser.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FakeItem:
    text: str = ""
    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0


@dataclass
class FakePage:
    page_num: int = 1
    width: float = 612.0
    height: float = 792.0
    text_items: list[FakeItem] = field(default_factory=list)
    text: str | None = None  # if set, _page_text() prefers this over text_items


@dataclass
class FakeResult:
    pages: list[FakePage] = field(default_factory=list)
    text: str = ""
