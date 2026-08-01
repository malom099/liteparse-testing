"""
quality_check.py
================
Option B: Keyword / snippet verification
Option C: Reading-order coherence

The actual implementations now live in `ochl_document_parsing.quality` (shared with
OCHLInvestmentAnalystAgent) — this module just re-exports them so existing
`from quality_check import ...` call sites (app.py, tests) keep working unchanged.
"""

from __future__ import annotations

from ochl_document_parsing.quality import (
    CoherenceReport,
    KeywordCheckReport,
    KeywordResult,
    coherence_check,
    keyword_check,
)

__all__ = [
    "CoherenceReport",
    "KeywordCheckReport",
    "KeywordResult",
    "coherence_check",
    "keyword_check",
]
