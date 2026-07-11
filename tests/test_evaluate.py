"""Real tests for evaluate.py's pure-logic functions: text-quality metrics,
bounding-box accuracy metrics, and the three file-export formats (CSV items,
tabular CSV, spatial-layout text). All exercised against lightweight fake
LiteParse-result objects (see conftest.py) rather than mocks, plus real
file I/O against tmp_path for the exporters.
"""

from __future__ import annotations

import csv

from evaluate import (
    evaluate_bboxes,
    evaluate_text_quality,
    write_items_csv,
    write_layout_txt,
    write_tabular_csv,
)
from tests.conftest import FakeItem, FakePage, FakeResult


class TestEvaluateTextQuality:
    def test_basic_metrics_computed_correctly(self):
        pages = [
            FakePage(text="Hello world this is page one, with enough content to exceed the near-empty threshold."),
            FakePage(text="Page two has more content than page one and is also long enough to not be near-empty."),
        ]
        result = FakeResult(pages=pages, text=" ".join(p.text or "" for p in pages))

        tq = evaluate_text_quality(result)

        assert tq.page_count == 2
        assert tq.total_chars == sum(len(p.text or "") for p in pages)
        assert tq.total_words == len(result.text.split())
        assert tq.empty_pages == 0
        assert tq.near_empty_pages == 0

    def test_empty_and_near_empty_pages_counted_separately(self):
        pages = [
            FakePage(text=""),  # empty
            FakePage(text="short"),  # near-empty (< 50 chars)
            FakePage(text="x" * 60),  # normal
        ]
        result = FakeResult(pages=pages, text="short " + "x" * 60)

        tq = evaluate_text_quality(result)

        assert tq.empty_pages == 1
        assert tq.near_empty_pages == 1
        assert tq.min_chars_on_page == 0
        assert tq.max_chars_on_page == 60

    def test_no_pages_returns_zeroed_result(self):
        result = FakeResult(pages=[], text="")

        tq = evaluate_text_quality(result)

        assert tq.page_count == 0
        assert tq.total_chars == 0
        assert tq.total_words == 0
        assert tq.min_chars_on_page == 0
        assert tq.max_chars_on_page == 0
        assert tq.char_stddev == 0.0

    def test_single_page_has_zero_stddev(self):
        result = FakeResult(pages=[FakePage(text="only one page")], text="only one page")

        tq = evaluate_text_quality(result)

        assert tq.char_stddev == 0.0

    def test_falls_back_to_text_items_when_page_text_is_none(self):
        page = FakePage(
            text=None,
            text_items=[FakeItem(text="Alpha"), FakeItem(text="Beta")],
        )
        result = FakeResult(pages=[page], text="Alpha Beta")

        tq = evaluate_text_quality(result)

        assert tq.chars_per_page == [len("Alpha Beta")]


class TestEvaluateBboxes:
    def test_counts_items_and_computes_coverage(self):
        page = FakePage(
            width=100.0,
            height=100.0,
            text_items=[
                FakeItem(text="A", x=0, y=0, width=50, height=50),
                FakeItem(text="B", x=50, y=50, width=50, height=50),
            ],
        )
        result = FakeResult(pages=[page])

        bb = evaluate_bboxes(result)

        assert bb.total_text_items == 2
        assert bb.pages_with_no_items == 0
        assert bb.items_with_zero_size == 0
        assert bb.items_out_of_bounds == 0
        # Two 50x50 boxes cover 5000 of 10000 page area == 0.5
        assert bb.avg_page_coverage == 0.5

    def test_zero_size_items_are_flagged_and_excluded_from_coverage(self):
        page = FakePage(
            width=100.0,
            height=100.0,
            text_items=[
                FakeItem(text="Good", x=0, y=0, width=10, height=10),
                FakeItem(text="ZeroWidth", x=20, y=20, width=0, height=10),
            ],
        )
        result = FakeResult(pages=[page])

        bb = evaluate_bboxes(result)

        assert bb.items_with_zero_size == 1
        # Only the 10x10 good item contributes: 100 / 10000
        assert bb.avg_page_coverage == 0.01

    def test_out_of_bounds_items_are_flagged(self):
        page = FakePage(
            width=100.0,
            height=100.0,
            text_items=[FakeItem(text="Overflow", x=90, y=90, width=50, height=50)],
        )
        result = FakeResult(pages=[page])

        bb = evaluate_bboxes(result)

        assert bb.items_out_of_bounds == 1

    def test_negative_coordinates_are_out_of_bounds(self):
        page = FakePage(
            width=100.0,
            height=100.0,
            text_items=[FakeItem(text="Negative", x=-5, y=0, width=10, height=10)],
        )
        result = FakeResult(pages=[page])

        bb = evaluate_bboxes(result)

        assert bb.items_out_of_bounds == 1

    def test_page_with_no_items_counted_and_zero_coverage(self):
        result = FakeResult(pages=[FakePage(width=100, height=100, text_items=[])])

        bb = evaluate_bboxes(result)

        assert bb.pages_with_no_items == 1
        assert bb.coverage_per_page == [0.0]

    def test_zero_area_page_reports_zero_coverage_without_error(self):
        page = FakePage(width=0, height=0, text_items=[FakeItem(text="X", x=0, y=0, width=10, height=10)])
        result = FakeResult(pages=[page])

        bb = evaluate_bboxes(result)

        assert bb.coverage_per_page == [0.0]

    def test_coverage_is_capped_at_one(self):
        # Overlapping/oversized items could sum to more than the page area;
        # coverage must still be reported as at most 1.0 (100%).
        page = FakePage(
            width=10.0,
            height=10.0,
            text_items=[
                FakeItem(text="Big1", x=0, y=0, width=10, height=10),
                FakeItem(text="Big2", x=0, y=0, width=10, height=10),
            ],
        )
        result = FakeResult(pages=[page])

        bb = evaluate_bboxes(result)

        assert bb.coverage_per_page == [1.0]


class TestWriteItemsCsv:
    def test_writes_header_and_all_items(self, tmp_path):
        page = FakePage(
            page_num=1,
            text_items=[
                FakeItem(text="Alpha", x=1.234, y=5.678, width=10, height=20),
                FakeItem(text="Beta", x=2, y=3, width=4, height=5),
            ],
        )
        result = FakeResult(pages=[page])
        out_path = tmp_path / "items.csv"

        write_items_csv(result, out_path)

        with out_path.open(encoding="utf-8-sig") as fh:
            rows = list(csv.reader(fh))

        assert rows[0] == ["page", "item", "x", "y", "width", "height", "text"]
        assert rows[1] == ["1", "1", "1.23", "5.68", "10", "20", "Alpha"]
        assert rows[2] == ["1", "2", "2", "3", "4", "5", "Beta"]

    def test_multi_page_document_writes_all_pages(self, tmp_path):
        pages = [
            FakePage(page_num=1, text_items=[FakeItem(text="P1")]),
            FakePage(page_num=2, text_items=[FakeItem(text="P2")]),
        ]
        result = FakeResult(pages=pages)
        out_path = tmp_path / "items.csv"

        write_items_csv(result, out_path)

        with out_path.open(encoding="utf-8-sig") as fh:
            rows = list(csv.reader(fh))

        page_col = [r[0] for r in rows[1:]]
        assert page_col == ["1", "2"]

    def test_empty_document_writes_only_header(self, tmp_path):
        result = FakeResult(pages=[])
        out_path = tmp_path / "items.csv"

        write_items_csv(result, out_path)

        with out_path.open(encoding="utf-8-sig") as fh:
            rows = list(csv.reader(fh))

        assert rows == [["page", "item", "x", "y", "width", "height", "text"]]


class TestWriteTabularCsv:
    def test_groups_items_into_rows_and_columns(self, tmp_path):
        # Two rows of two columns each, well-separated so clustering is unambiguous.
        page = FakePage(
            page_num=1,
            text_items=[
                FakeItem(text="Name", x=0, y=0, width=40, height=10),
                FakeItem(text="Value", x=100, y=0, width=40, height=10),
                FakeItem(text="Alice", x=0, y=50, width=40, height=10),
                FakeItem(text="100", x=100, y=50, width=40, height=10),
            ],
        )
        result = FakeResult(pages=[page])
        out_path = tmp_path / "tabular.csv"

        write_tabular_csv(result, out_path)

        content = out_path.read_text(encoding="utf-8-sig")
        assert "--- PAGE 1 ---" in content
        # Both rows should appear with their two columns preserved.
        rows = [line for line in content.splitlines() if line and "PAGE" not in line]
        assert any("Name" in r and "Value" in r for r in rows)
        assert any("Alice" in r and "100" in r for r in rows)

    def test_items_within_row_tolerance_share_a_row(self, tmp_path):
        page = FakePage(
            page_num=1,
            text_items=[
                FakeItem(text="A", x=0, y=10.0, width=10, height=10),
                FakeItem(text="B", x=100, y=11.5, width=10, height=10),  # within default 4pt tolerance
            ],
        )
        result = FakeResult(pages=[page])
        out_path = tmp_path / "tabular.csv"

        write_tabular_csv(result, out_path)

        content = out_path.read_text(encoding="utf-8-sig")
        rows = [line for line in content.splitlines() if line and "PAGE" not in line and line.strip()]
        assert any("A" in r and "B" in r for r in rows)

    def test_empty_page_produces_no_output(self, tmp_path):
        result = FakeResult(pages=[FakePage(page_num=1, text_items=[])])
        out_path = tmp_path / "tabular.csv"

        write_tabular_csv(result, out_path)

        content = out_path.read_text(encoding="utf-8-sig")
        assert "PAGE" not in content


class TestWriteLayoutTxt:
    def test_writes_page_header_and_positions_text(self, tmp_path):
        page = FakePage(
            page_num=1,
            width=120.0,
            height=240.0,
            text_items=[FakeItem(text="Hello", x=0, y=0, width=10, height=10)],
        )
        result = FakeResult(pages=[page])
        out_path = tmp_path / "layout.txt"

        write_layout_txt(result, out_path)

        content = out_path.read_text(encoding="utf-8")
        assert "PAGE 1" in content
        assert "Hello" in content

    def test_falls_back_to_raw_lines_when_no_spatial_data(self, tmp_path):
        page = FakePage(
            page_num=1,
            width=0,
            height=0,
            text_items=[FakeItem(text="Just some text", x=0, y=0, width=0, height=0)],
        )
        result = FakeResult(pages=[page])
        out_path = tmp_path / "layout.txt"

        write_layout_txt(result, out_path)

        content = out_path.read_text(encoding="utf-8")
        assert "Just some text" in content

    def test_empty_text_items_are_skipped(self, tmp_path):
        page = FakePage(
            page_num=1,
            width=100.0,
            height=100.0,
            text_items=[FakeItem(text="   ", x=0, y=0, width=10, height=10)],
        )
        result = FakeResult(pages=[page])
        out_path = tmp_path / "layout.txt"

        write_layout_txt(result, out_path)

        content = out_path.read_text(encoding="utf-8")
        assert "PAGE 1" in content
