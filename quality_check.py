"""
quality_check.py
================
Option B: Keyword / snippet verification
    - Check whether expected text strings appear in the parsed output.
    - Report which page each snippet was found on and show a surrounding
      context excerpt.

Option C: Reading-order coherence
    - Tokenise the full extracted text and classify each token.
    - Compute ratios of valid words, financial numbers, broken-word
      artefacts (line-break hyphenation), and garbage symbols.
    - Produce a 0–1 coherence score with plain-English advisory notes.

Both functions accept a raw LiteParse result object so the caller only
needs to parse the document once.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Shared data classes
# ---------------------------------------------------------------------------


@dataclass
class KeywordResult:
    snippet: str
    found: bool
    page_found: int | None  # 1-based page number, None if not found
    context: str | None  # ~160-char excerpt around the match


@dataclass
class KeywordCheckReport:
    snippets_tested: int
    snippets_found: int
    snippets_missing: int
    results: list[KeywordResult] = field(default_factory=list)


@dataclass
class CoherenceReport:
    total_tokens: int
    real_word_ratio: float  # (alphabetic + financial numeric) / total
    broken_word_ratio: float  # tokens ending with hyphen (line-break artefacts)
    numeric_ratio: float  # purely numeric / financial tokens
    score: float  # 0–1 overall quality score
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_CONTEXT_WINDOW = 80  # chars to show on each side of a keyword match


def _page_text(page) -> str:
    """Return the text for a liteparse page object."""
    txt = getattr(page, "text", None)
    if txt is not None:
        return txt
    items = getattr(page, "text_items", []) or []
    return " ".join(getattr(item, "text", "") for item in items)


# ---------------------------------------------------------------------------
# Option B — Keyword / snippet verification
# ---------------------------------------------------------------------------


def keyword_check(result, snippets: list[str]) -> KeywordCheckReport:
    """
    Check whether each expected snippet appears in the parsed document text.

    Args:
        result:   LiteParse parse result object (returned by LiteParse.parse()).
        snippets: List of expected text strings to search for.

    Returns:
        KeywordCheckReport with per-snippet hit / miss detail and context.
    """
    full_text: str = getattr(result, "text", "") or ""
    pages = getattr(result, "pages", []) or []

    kw_results: list[KeywordResult] = []

    for snippet in snippets:
        needle = snippet.lower()
        haystack = full_text.lower()
        idx = haystack.find(needle)

        if idx == -1:
            kw_results.append(KeywordResult(snippet=snippet, found=False, page_found=None, context=None))
            continue

        # Build a readable context excerpt
        start = max(0, idx - _CONTEXT_WINDOW)
        end = min(len(full_text), idx + len(snippet) + _CONTEXT_WINDOW)
        raw_ctx = full_text[start:end].replace("\n", " ").strip()
        context = re.sub(r" {2,}", " ", raw_ctx)

        # Find the first page that contains the snippet
        page_found: int | None = None
        for page in pages:
            if needle in _page_text(page).lower():
                page_found = getattr(page, "page_num", None) or getattr(page, "page", None)
                break

        kw_results.append(KeywordResult(snippet=snippet, found=True, page_found=page_found, context=context))

    found_count = sum(1 for r in kw_results if r.found)
    return KeywordCheckReport(
        snippets_tested=len(snippets),
        snippets_found=found_count,
        snippets_missing=len(snippets) - found_count,
        results=kw_results,
    )


# ---------------------------------------------------------------------------
# Option C — Reading-order coherence
# ---------------------------------------------------------------------------

# Token classification patterns
_RE_PURE_ALPHA = re.compile(r"^[A-Za-zÀ-ÖØ-öø-ÿ]{2,}$")
# Covers: integers, decimals, commas, percentages, currency symbols, +/-
_RE_FINANCIAL_NUM = re.compile(r"^[\d,\.%\$€£¥\+\-]{1,}$")
# A token that ends with a bare hyphen after at least two word chars
# indicates a line-break hyphenation artefact (e.g. "invest-")
_RE_BROKEN_WORD = re.compile(r"^[A-Za-z]{2,}-$")
# Two or more consecutive non-text symbols → extraction garbage
_RE_GARBAGE = re.compile(r"[|#^{}<>~`\[\]\\]{2,}")


def coherence_check(result) -> CoherenceReport:
    """
    Score the reading-order coherence of the extracted text.

    No external word list is required. Tokens are classified by regex:
    - Alphabetic (≥2 chars)           → valid word
    - Numeric / financial             → valid data token
    - Hyphen-terminated               → broken line-wrap artefact
    - Symbol-cluster                  → extraction garbage

    Score formula:
        base   = (alphabetic + numeric) / total
        score  = base × (1 – broken_ratio × 3) × (1 – garbage_ratio × 2)

    The score is intentionally lenient on financial documents that contain
    many numbers, dates, and abbreviations.

    Args:
        result: LiteParse parse result object.

    Returns:
        CoherenceReport with ratios, score, and advisory notes.
    """
    full_text: str = getattr(result, "text", "") or ""
    tokens = [t for t in full_text.split() if t]

    if not tokens:
        return CoherenceReport(
            total_tokens=0,
            real_word_ratio=0.0,
            broken_word_ratio=0.0,
            numeric_ratio=0.0,
            score=0.0,
            notes=[
                "No text extracted — document may be empty or image-only. Ensure OCR is enabled (it is on by default)."
            ],
        )

    n = len(tokens)
    alphabetic = 0
    numeric = 0
    broken = 0
    garbage = 0

    for tok in tokens:
        # Strip common surrounding punctuation before classifying
        core = tok.strip(".,;:!?\"'()[]{}")
        if not core:
            garbage += 1
            continue

        if _RE_PURE_ALPHA.match(core):
            alphabetic += 1
        elif _RE_FINANCIAL_NUM.match(core):
            numeric += 1
        elif _RE_GARBAGE.search(core):
            garbage += 1
        # Short mixed tokens like "Q4", "p.12", "UK", "NAV" are left neutral

        if _RE_BROKEN_WORD.match(tok):
            broken += 1

    valid = alphabetic + numeric
    real_word_ratio = round(valid / n, 4)
    broken_ratio = round(broken / n, 4)
    garbage_ratio = garbage / n
    numeric_ratio = round(numeric / n, 4)

    # Score: high base penalised by broken-word and garbage proportions
    score = real_word_ratio * max(0.0, 1.0 - broken_ratio * 3) * max(0.0, 1.0 - garbage_ratio * 2)
    score = round(min(max(score, 0.0), 1.0), 4)

    notes: list[str] = []
    if score < 0.50:
        notes.append("Low coherence — possible OCR failures, complex table layouts, or charts.")
    if broken_ratio > 0.05:
        notes.append(f"{broken_ratio:.0%} broken-word tokens — hyphenation artefacts in layout.")
    if garbage_ratio > 0.05:
        notes.append(f"{garbage_ratio:.0%} garbage tokens — may include table borders or header/footer noise.")
    if numeric_ratio > 0.50:
        notes.append(
            "Document is heavily numeric — expected for financial statements; score may appear lower than actual quality."
        )

    return CoherenceReport(
        total_tokens=n,
        real_word_ratio=real_word_ratio,
        broken_word_ratio=broken_ratio,
        numeric_ratio=numeric_ratio,
        score=score,
        notes=notes,
    )
