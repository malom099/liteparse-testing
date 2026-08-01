"""Shared pytest fixtures and lightweight LiteParse-result fakes.

The real result objects passed through this app's evaluate.py/quality_check.py are now
`ochl_document_parsing.models.ParseResult`/`ParsePage`/`TextItem` instances (produced by the
shared library's backend factory) rather than liteparse's native objects directly. `FakeItem`/
`FakePage`/`FakeResult` are thin factory functions returning those exact pydantic model types
(with sensible test defaults, e.g. auto-filling the required `usage` field) so tests both stay
concise AND satisfy the library quality-check functions' `ParseResult` type hints — no
duck-typed stand-ins needed.
"""

from __future__ import annotations

from ochl_document_parsing.models import ParsePage, ParseResult, TextItem, UsageInfo

FakeItem = TextItem


def FakePage(
    *,
    page_no: int = 0,  # 0-based, matching ochl_document_parsing.models.ParsePage
    width: float = 612.0,
    height: float = 792.0,
    text_items: list[TextItem] | None = None,
    text: str = "",
) -> ParsePage:
    return ParsePage(page_no=page_no, width=width, height=height, text_items=text_items or [], text=text)


def FakeResult(*, pages: list[ParsePage] | None = None, text: str = "") -> ParseResult:
    pages = pages or []
    return ParseResult(pages=pages, text=text, usage=UsageInfo(backend="fake", pages_processed=len(pages)))
