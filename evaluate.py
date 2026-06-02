"""
LiteParse Evaluation Script
============================
Evaluates LiteParse on text extraction quality and bounding-box spatial
accuracy across one or more documents.

Usage
-----
    python evaluate.py <file_or_directory> [options]

    # Evaluate all documents in the current folder (default)
    python evaluate.py

    # Evaluate a single PDF (OCR off for speed)
    python evaluate.py report.pdf

    # Evaluate with OCR enabled
    python evaluate.py --ocr

    # Suppress per-file console output and only write JSON reports
    python evaluate.py --json-only --output-dir results/

Options
-------
    --output-dir DIR    Where to save JSON reports (default: ./results)
    --ocr               Enable built-in Tesseract OCR (off by default)
    --tessdata PATH     Path to tessdata folder (overrides TESSDATA_PREFIX)
    --dpi N             Render DPI for screenshot comparison (default: 150)
    --json-only         Skip per-file console output; only write JSON files
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from liteparse import LiteParse

# ---------------------------------------------------------------------------
# Supported file extensions
# ---------------------------------------------------------------------------
SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".doc",
    ".docm",
    ".odt",
    ".rtf",
    ".pptx",
    ".ppt",
    ".pptm",
    ".odp",
    ".xlsx",
    ".xls",
    ".xlsm",
    ".ods",
    ".csv",
    ".tsv",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".tiff",
    ".webp",
}


# ---------------------------------------------------------------------------
# Result data classes
# ---------------------------------------------------------------------------


@dataclass
class TextQualityResult:
    """Per-document text extraction quality metrics."""

    page_count: int
    total_chars: int
    total_words: int
    avg_chars_per_page: float
    char_stddev: float
    empty_pages: int  # pages with 0 characters
    near_empty_pages: int  # pages with 1–49 characters (likely extraction issue)
    min_chars_on_page: int
    max_chars_on_page: int
    chars_per_page: list[int] = field(default_factory=list)


@dataclass
class BBoxResult:
    """Per-document bounding-box spatial accuracy metrics."""

    total_text_items: int
    avg_items_per_page: float
    pages_with_no_items: int
    items_with_zero_size: int  # width or height == 0
    items_out_of_bounds: int  # coordinate exceeds reported page dimensions
    avg_page_coverage: float  # mean fraction of page area covered by text boxes
    min_page_coverage: float
    max_page_coverage: float
    coverage_per_page: list[float] = field(default_factory=list)


@dataclass
class DocumentReport:
    """Full evaluation report for a single document."""

    file_path: str
    file_name: str
    parse_time_seconds: float
    page_count: int
    text_quality: Optional[TextQualityResult] = None
    bbox: Optional[BBoxResult] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Core evaluation helpers
# ---------------------------------------------------------------------------


def _page_text(page) -> str:
    """Safely obtain page text regardless of attribute name."""
    # Try the standard attribute first, then fall back to concatenating text_items
    txt = getattr(page, "text", None)
    if txt is not None:
        return txt
    items = getattr(page, "text_items", []) or []
    return " ".join(getattr(item, "text", "") for item in items)


def evaluate_text_quality(result) -> TextQualityResult:
    pages = result.pages or []
    chars_per_page: list[int] = [len(_page_text(p).strip()) for p in pages]

    total_chars = sum(chars_per_page)
    total_words = len(result.text.split()) if result.text else 0
    page_count = len(pages)

    empty = sum(1 for c in chars_per_page if c == 0)
    near_empty = sum(1 for c in chars_per_page if 0 < c < 50)
    avg = statistics.mean(chars_per_page) if chars_per_page else 0.0
    stddev = statistics.stdev(chars_per_page) if len(chars_per_page) > 1 else 0.0

    return TextQualityResult(
        page_count=page_count,
        total_chars=total_chars,
        total_words=total_words,
        avg_chars_per_page=round(avg, 1),
        char_stddev=round(stddev, 1),
        empty_pages=empty,
        near_empty_pages=near_empty,
        min_chars_on_page=min(chars_per_page, default=0),
        max_chars_on_page=max(chars_per_page, default=0),
        chars_per_page=chars_per_page,
    )


def evaluate_bboxes(result) -> BBoxResult:
    pages = result.pages or []
    total_items = 0
    zero_size = 0
    out_of_bounds = 0
    pages_no_items = 0
    coverage_per_page: list[float] = []

    for page in pages:
        items = getattr(page, "text_items", []) or []
        page_w = getattr(page, "width", 0) or 0
        page_h = getattr(page, "height", 0) or 0
        page_area = page_w * page_h

        total_items += len(items)

        if not items:
            pages_no_items += 1
            coverage_per_page.append(0.0)
            continue

        covered = 0.0
        for item in items:
            iw = getattr(item, "width", 0) or 0
            ih = getattr(item, "height", 0) or 0
            ix = getattr(item, "x", 0) or 0
            iy = getattr(item, "y", 0) or 0

            if iw <= 0 or ih <= 0:
                zero_size += 1
                continue

            if page_w > 0 and page_h > 0:
                if ix < 0 or iy < 0 or (ix + iw) > page_w or (iy + ih) > page_h:
                    out_of_bounds += 1

            covered += iw * ih

        ratio = min(covered / page_area, 1.0) if page_area > 0 else 0.0
        coverage_per_page.append(round(ratio, 4))

    n = len(pages) or 1
    avg_cov = statistics.mean(coverage_per_page) if coverage_per_page else 0.0

    return BBoxResult(
        total_text_items=total_items,
        avg_items_per_page=round(total_items / n, 1),
        pages_with_no_items=pages_no_items,
        items_with_zero_size=zero_size,
        items_out_of_bounds=out_of_bounds,
        avg_page_coverage=round(avg_cov, 4),
        min_page_coverage=round(min(coverage_per_page, default=0.0), 4),
        max_page_coverage=round(max(coverage_per_page, default=0.0), 4),
        coverage_per_page=coverage_per_page,
    )


def evaluate_document(
    path: Path,
    ocr_enabled: bool = False,
    tessdata_path: Optional[str] = None,
    dpi: int = 150,
) -> DocumentReport:
    kwargs: dict = dict(
        ocr_enabled=ocr_enabled,
        dpi=dpi,
        quiet=True,
    )
    if tessdata_path:
        kwargs["tessdata_path"] = tessdata_path

    parser = LiteParse(**kwargs)

    t0 = time.perf_counter()
    try:
        result = parser.parse(str(path))
    except Exception as exc:
        elapsed = round(time.perf_counter() - t0, 3)
        return DocumentReport(
            file_path=str(path),
            file_name=path.name,
            parse_time_seconds=elapsed,
            page_count=0,
            error=str(exc),
        )

    elapsed = round(time.perf_counter() - t0, 3)
    page_count = len(result.pages or [])

    return DocumentReport(
        file_path=str(path),
        file_name=path.name,
        parse_time_seconds=elapsed,
        page_count=page_count,
        text_quality=evaluate_text_quality(result),
        bbox=evaluate_bboxes(result),
    )


# ---------------------------------------------------------------------------
# Console reporting
# ---------------------------------------------------------------------------


def _sep(width: int = 60) -> str:
    return "=" * width


def print_document_report(report: DocumentReport) -> None:
    print(f"\n{_sep()}")
    print(f"File     : {report.file_name}")
    print(f"Pages    : {report.page_count}")
    print(f"Time     : {report.parse_time_seconds:.3f}s", end="")
    if report.page_count > 0 and report.parse_time_seconds > 0:
        speed = report.page_count / report.parse_time_seconds
        print(f"  ({speed:.1f} pages/sec)", end="")
    print()

    if report.error:
        print(f"ERROR    : {report.error}")
        return

    tq = report.text_quality
    if tq:
        print("\n  -- Text Extraction Quality --")
        print(f"  Total chars          : {tq.total_chars:,}")
        print(f"  Total words          : {tq.total_words:,}")
        print(f"  Avg chars/page       : {tq.avg_chars_per_page:,.1f}")
        print(f"  Char stddev          : {tq.char_stddev:,.1f}")
        print(f"  Empty pages          : {tq.empty_pages} of {tq.page_count}")
        print(
            f"  Near-empty pages     : {tq.near_empty_pages}  (<50 chars, possible issue)"
        )
        print(
            f"  Min / Max chars/page : {tq.min_chars_on_page:,} / {tq.max_chars_on_page:,}"
        )

    bb = report.bbox
    if bb:
        print("\n  -- Bounding Box Accuracy --")
        print(f"  Total text items     : {bb.total_text_items:,}")
        print(f"  Avg items/page       : {bb.avg_items_per_page:.1f}")
        print(f"  Pages with no items  : {bb.pages_with_no_items}")
        print(
            f"  Zero-size items      : {bb.items_with_zero_size}  (width or height = 0)"
        )
        print(
            f"  Out-of-bounds items  : {bb.items_out_of_bounds}  (exceed page dimensions)"
        )
        cov = bb.avg_page_coverage
        cov_min = bb.min_page_coverage
        cov_max = bb.max_page_coverage
        print(
            f"  Page coverage        : avg={cov:.1%}  min={cov_min:.1%}  max={cov_max:.1%}"
        )


def print_summary(reports: list[DocumentReport]) -> None:
    ok = [r for r in reports if not r.error]
    failed = [r for r in reports if r.error]

    print(f"\n{_sep()}")
    print(f"SUMMARY  ({len(reports)} document(s))")
    print(f"  Parsed OK : {len(ok)}")
    print(f"  Errors    : {len(failed)}")

    if not ok:
        if failed:
            print("\n  Failed files:")
            for r in failed:
                print(f"    {r.file_name}: {r.error}")
        return

    total_pages = sum(r.page_count for r in ok)
    total_time = sum(r.parse_time_seconds for r in ok)
    total_chars = sum(r.text_quality.total_chars for r in ok if r.text_quality)
    total_words = sum(r.text_quality.total_words for r in ok if r.text_quality)
    avg_speed = total_pages / total_time if total_time > 0 else 0.0

    print(f"\n  Total pages   : {total_pages}")
    print(f"  Total chars   : {total_chars:,}")
    print(f"  Total words   : {total_words:,}")
    print(f"  Total time    : {total_time:.2f}s")
    print(f"  Avg speed     : {avg_speed:.1f} pages/sec")

    all_empty = sum(r.text_quality.empty_pages for r in ok if r.text_quality)
    all_near_empty = sum(r.text_quality.near_empty_pages for r in ok if r.text_quality)
    if all_empty or all_near_empty:
        print(f"\n  Total empty pages      : {all_empty}")
        print(
            f"  Total near-empty pages : {all_near_empty}  (possible OCR/extraction issues)"
        )

    all_cov = [cov for r in ok if r.bbox for cov in r.bbox.coverage_per_page]
    if all_cov:
        print("\n  BBox coverage (all pages across all docs):")
        print(f"    Mean : {statistics.mean(all_cov):.1%}")
        print(f"    Min  : {min(all_cov):.1%}")
        print(f"    Max  : {max(all_cov):.1%}")

    total_zero_size = sum(r.bbox.items_with_zero_size for r in ok if r.bbox)
    total_oob = sum(r.bbox.items_out_of_bounds for r in ok if r.bbox)
    total_items = sum(r.bbox.total_text_items for r in ok if r.bbox)
    if total_items > 0:
        zero_pct = total_zero_size / total_items
        oob_pct = total_oob / total_items
        print("\n  BBox anomalies (across all docs):")
        print(
            f"    Zero-size items    : {total_zero_size:,}  ({zero_pct:.2%} of all items)"
        )
        print(f"    Out-of-bounds items: {total_oob:,}  ({oob_pct:.2%} of all items)")

    if failed:
        print("\n  Failed files:")
        for r in failed:
            print(f"    {r.file_name}: {r.error}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def collect_files(input_path: Path) -> list[Path]:
    if input_path.is_file():
        return [input_path]
    return sorted(
        p
        for p in input_path.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    )


def main() -> None:
    ap = argparse.ArgumentParser(
        description=(
            "Evaluate LiteParse on text-extraction quality and bounding-box accuracy.\n"
            "Supports PDF, DOCX, XLSX, PPTX, and common image formats."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "input",
        nargs="?",
        default=".",
        help="Path to a document file or directory. Defaults to the current directory.",
    )
    ap.add_argument(
        "--output-dir",
        default="results",
        metavar="DIR",
        help="Directory to save JSON reports. Defaults to ./results/",
    )
    ap.add_argument(
        "--ocr",
        action="store_true",
        default=False,
        help=(
            "Enable built-in Tesseract OCR. Disabled by default for speed. "
            "Requires eng.traineddata (downloaded automatically on first run, "
            "or supply --tessdata for offline use)."
        ),
    )
    ap.add_argument(
        "--tessdata",
        default=None,
        metavar="PATH",
        help="Path to a directory containing Tesseract .traineddata files (for offline use).",
    )
    ap.add_argument(
        "--dpi",
        type=int,
        default=150,
        help="Rendering DPI passed to LiteParse (default: 150).",
    )
    ap.add_argument(
        "--json-only",
        action="store_true",
        default=False,
        help="Suppress per-file console output; only write JSON reports.",
    )
    args = ap.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: '{input_path}' does not exist.", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    files = collect_files(input_path)
    if not files:
        print(f"No supported documents found under '{input_path}'.", file=sys.stderr)
        sys.exit(1)

    ocr_label = "on" if args.ocr else "off (pass --ocr to enable)"
    print(f"Found {len(files)} document(s).  OCR={ocr_label}  DPI={args.dpi}")

    reports: list[DocumentReport] = []
    for f in files:
        print(f"Parsing: {f.name} ... ", end="", flush=True)
        report = evaluate_document(
            f,
            ocr_enabled=args.ocr,
            tessdata_path=args.tessdata,
            dpi=args.dpi,
        )
        reports.append(report)

        status = "ERROR" if report.error else f"OK ({report.page_count} pages)"
        print(status)

        if not args.json_only:
            print_document_report(report)

        # Per-file JSON report
        out_file = output_dir / (f.stem + "_liteparse_report.json")
        with out_file.open("w", encoding="utf-8") as fh:
            json.dump(asdict(report), fh, indent=2)

    print_summary(reports)

    # Combined report
    combined_path = output_dir / "combined_report.json"
    with combined_path.open("w", encoding="utf-8") as fh:
        json.dump([asdict(r) for r in reports], fh, indent=2)

    print(f"\nJSON reports saved to: {output_dir.resolve()}/")


if __name__ == "__main__":
    main()
