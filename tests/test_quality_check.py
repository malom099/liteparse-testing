"""Real tests for quality_check.py — keyword verification and coherence scoring.

No mocking of the parser itself: these tests build lightweight fake
LiteParse-result objects (see conftest.py) and exercise the real
classification/scoring logic against them.
"""

from __future__ import annotations

from quality_check import coherence_check, keyword_check
from tests.conftest import FakePage, FakeResult


class TestKeywordCheck:
    def test_all_snippets_found_reports_correct_counts(self):
        result = FakeResult(
            text="Total Return 12.5% for the quarter ending March 2026.",
            pages=[FakePage(page_no=0, text="Total Return 12.5% for the quarter ending March 2026.")],
        )

        report = keyword_check(result, ["Total Return", "March 2026"])

        assert report.snippets_tested == 2
        assert report.snippets_found == 2
        assert report.snippets_missing == 0
        assert all(r.found for r in report.results)

    def test_missing_snippet_reports_not_found_with_no_context(self):
        result = FakeResult(text="Nothing relevant here.", pages=[FakePage(text="Nothing relevant here.")])

        report = keyword_check(result, ["Sherritt International"])

        assert report.snippets_found == 0
        assert report.snippets_missing == 1
        r = report.results[0]
        assert r.found is False
        assert r.page_found is None
        assert r.context is None

    def test_search_is_case_insensitive(self):
        result = FakeResult(text="THE FUND RETURNED 5%.", pages=[FakePage(text="THE FUND RETURNED 5%.")])

        report = keyword_check(result, ["the fund returned"])

        assert report.snippets_found == 1
        assert report.results[0].found is True

    def test_page_found_identifies_correct_page(self):
        pages = [
            FakePage(page_no=0, text="Introduction and overview."),
            FakePage(page_no=1, text="Performance summary: NAV increased 3%."),
            FakePage(page_no=2, text="Disclosures and appendix."),
        ]
        result = FakeResult(text=" ".join(p.text or "" for p in pages), pages=pages)

        report = keyword_check(result, ["NAV increased"])

        assert report.results[0].page_found == 2

    def test_context_excerpt_includes_surrounding_text(self):
        full_text = "A" * 100 + "TARGET_SNIPPET" + "B" * 100
        result = FakeResult(text=full_text, pages=[FakePage(text=full_text)])

        report = keyword_check(result, ["TARGET_SNIPPET"])

        ctx = report.results[0].context
        assert ctx is not None
        assert "target_snippet" in ctx.lower()
        # Context window is +/-80 chars, so it should be shorter than the full text
        assert len(ctx) < len(full_text)

    def test_empty_snippet_list_returns_zeroed_report(self):
        result = FakeResult(text="some text", pages=[FakePage(text="some text")])

        report = keyword_check(result, [])

        assert report.snippets_tested == 0
        assert report.snippets_found == 0
        assert report.snippets_missing == 0
        assert report.results == []

    def test_result_with_no_pages_and_empty_text_reports_all_missing(self):
        """A ParseResult with no pages and empty text (e.g. a failed/empty parse) must not
        raise, and reports every snippet missing."""
        empty_result = FakeResult(pages=[], text="")

        report = keyword_check(empty_result, ["anything"])

        assert report.snippets_found == 0
        assert report.results[0].found is False


class TestCoherenceCheck:
    def test_no_text_extracted_returns_zero_score_with_advisory_note(self):
        result = FakeResult(text="", pages=[])

        report = coherence_check(result)

        assert report.total_tokens == 0
        assert report.score == 0.0
        assert any("No text extracted" in note for note in report.notes)

    def test_clean_prose_scores_highly(self):
        text = "The fund returned strong performance across all strategies this quarter."
        result = FakeResult(text=text, pages=[])

        report = coherence_check(result)

        assert report.total_tokens == len(text.split())
        assert report.real_word_ratio == 1.0
        assert report.broken_word_ratio == 0.0
        assert report.score > 0.9

    def test_financial_numbers_count_as_valid_tokens(self):
        text = "NAV $1,234.56 +2.5% -1.2% 100"
        result = FakeResult(text=text, pages=[])

        report = coherence_check(result)

        # All tokens except "NAV" (alphabetic, 3 chars) classify as either
        # alphabetic or financial-numeric, so real_word_ratio should be 1.0.
        assert report.real_word_ratio == 1.0
        assert report.numeric_ratio > 0.0

    def test_broken_word_hyphenation_lowers_score_and_adds_note(self):
        # Many hyphen-terminated tokens simulate line-wrap artefacts.
        text = "invest- ment strat- egy port- folio alloc- ation manag- ement"
        result = FakeResult(text=text, pages=[])

        report = coherence_check(result)

        assert report.broken_word_ratio > 0.05
        assert any("broken-word" in note for note in report.notes)

    def test_garbage_symbol_clusters_lower_score_and_add_note(self):
        text = "Normal text here ||||#### <<>> more normal text words here today"
        result = FakeResult(text=text, pages=[])

        report = coherence_check(result)

        assert any("garbage" in note for note in report.notes)

    def test_heavily_numeric_document_adds_advisory_note(self):
        text = " ".join(["123.45"] * 20 + ["word"] * 5)
        result = FakeResult(text=text, pages=[])

        report = coherence_check(result)

        assert report.numeric_ratio > 0.5
        assert any("heavily numeric" in note for note in report.notes)

    def test_low_score_document_adds_low_coherence_note(self):
        # Mostly garbage/symbol tokens with almost no real words.
        text = " ".join(["@#$%", "^&*(", "){}[]", "<<>>"] * 10)
        result = FakeResult(text=text, pages=[])

        report = coherence_check(result)

        assert report.score < 0.50
        assert any("Low coherence" in note for note in report.notes)

    def test_score_bounded_between_zero_and_one(self):
        text = "word " * 500
        result = FakeResult(text=text, pages=[])

        report = coherence_check(result)

        assert 0.0 <= report.score <= 1.0
