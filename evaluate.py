"""
LiteParse Evaluation Script
============================
Evaluates LiteParse on text extraction quality and bounding-box spatial
accuracy across one or more documents.

Usage
-----
    python evaluate.py <file_or_directory> [options]

    # Evaluate all documents in the current folder (OCR on by default)
    python evaluate.py

    # Evaluate a single PDF
    python evaluate.py report.pdf

    # Disable OCR for speed on known native-text PDFs
    python evaluate.py --no-ocr

    # Suppress per-file console output and only write JSON reports
    python evaluate.py --json-only --output-dir results/

    # Skip CSV export
    python evaluate.py --no-csv

Options
-------
    --output-dir DIR    Where to save JSON reports (default: ./results)
    --no-ocr            Disable Tesseract OCR (OCR is on by default)
    --no-csv            Skip CSV export (CSV is written by default)
    --tessdata PATH     Path to tessdata folder (overrides TESSDATA_PREFIX)
    --dpi N             Render DPI (default: 150)
    --json-only         Skip per-file console output; only write JSON files
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from ochl_document_parsing.backends.factory import get_backend
from ochl_document_parsing.quality import (
    BBoxResult,
    TextQualityResult,
    evaluate_bboxes,
    evaluate_text_quality,
)

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
#
# TextQualityResult and BBoxResult are no longer defined here — they, and the
# evaluate_text_quality()/evaluate_bboxes() functions that compute them, now live in
# ochl_document_parsing.quality (shared with OCHLInvestmentAnalystAgent) and are imported
# above. Re-exported here so existing `from evaluate import TextQualityResult` etc. call
# sites (app.py, tests) keep working unchanged.


@dataclass
class DocumentReport:
    """Full evaluation report for a single document."""

    file_path: str
    file_name: str
    parse_time_seconds: float
    page_count: int
    text_quality: TextQualityResult | None = None
    bbox: BBoxResult | None = None
    error: str | None = None


def document_report_dict(report: DocumentReport) -> dict:
    """JSON-serializable dict for a `DocumentReport`.

    `dataclasses.asdict()` alone doesn't know how to serialize the nested `TextQualityResult`/
    `BBoxResult` fields since those are pydantic models (from the shared library), not
    dataclasses — it leaves them as-is, which then fails `json.dump()`. This converts those
    two fields via `model_dump()` first.
    """
    d = asdict(report)
    if report.text_quality is not None:
        d["text_quality"] = report.text_quality.model_dump()
    if report.bbox is not None:
        d["bbox"] = report.bbox.model_dump()
    return d


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------


def write_items_csv(result, out_path: Path) -> None:
    """
    Write every parsed text item to a CSV with spatial coordinates.

    Columns: page, item, x, y, width, height, text

    Opens cleanly in Excel and shows the exact parsed text alongside its
    position (in PDF points, origin top-left) for each page.  The file is
    saved with a UTF-8 BOM so Excel auto-detects the encoding.
    """
    pages = getattr(result, "pages", []) or []
    with out_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(["page", "item", "x", "y", "width", "height", "text"])
        for page in pages:
            page_num = page.page_no + 1
            items = getattr(page, "text_items", []) or []
            for idx, item in enumerate(items, start=1):
                writer.writerow(
                    [
                        page_num,
                        idx,
                        round(getattr(item, "x", 0) or 0, 2),
                        round(getattr(item, "y", 0) or 0, 2),
                        round(getattr(item, "width", 0) or 0, 2),
                        round(getattr(item, "height", 0) or 0, 2),
                        getattr(item, "text", ""),
                    ]
                )


def write_tabular_csv(result, out_path: Path, row_tolerance: float = 4.0) -> None:
    """
    Write a tabular CSV that reconstructs the row/column structure of the document.

    Algorithm
    ---------
    For each page:
      1. Cluster text items into logical rows by grouping items whose Y centres
         are within *row_tolerance* points of each other.
      2. Identify column boundaries by collecting every item's X-centre across
         all rows on the page, then merging centres that are within a gap
         threshold (default: 20 pt).  Each merged cluster becomes one column.
      3. Write one CSV row per logical document row, placing each item's text
         into the column whose centre is nearest to the item's X centre.
         Empty cells are written as blank strings.

    The result opens directly in Excel with rows and columns that mirror the
    layout of the original report — partner rows, header columns, numeric
    values — all aligned as they appear on the page.

    The file is saved with a UTF-8 BOM so Excel auto-detects the encoding.
    """
    COL_MERGE_GAP = 20.0  # pt — two X centres closer than this share a column

    pages = getattr(result, "pages", []) or []
    with out_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)

        for page in pages:
            page_num = page.page_no + 1
            items = getattr(page, "text_items", []) or []
            if not items:
                continue

            # ── Step 1: cluster into rows ──────────────────────────────────
            # Sort by Y then X
            def _y_centre(item) -> float:
                y = getattr(item, "y", 0) or 0
                h = getattr(item, "height", 0) or 0
                return y + h / 2

            def _x_centre(item) -> float:
                x = getattr(item, "x", 0) or 0
                w = getattr(item, "width", 0) or 0
                return x + w / 2

            sorted_items = sorted(items, key=lambda i: (_y_centre(i), _x_centre(i)))

            rows: list[list] = []
            for item in sorted_items:
                yc = _y_centre(item)
                placed = False
                for row in rows:
                    if abs(_y_centre(row[0]) - yc) <= row_tolerance:
                        row.append(item)
                        placed = True
                        break
                if not placed:
                    rows.append([item])

            # Sort items within each row by X
            for row in rows:
                row.sort(key=_x_centre)

            # ── Step 2: detect column boundaries ──────────────────────────
            all_xc = sorted({round(_x_centre(i), 1) for row in rows for i in row})
            col_centres: list[float] = []
            for xc in all_xc:
                if not col_centres or xc - col_centres[-1] > COL_MERGE_GAP:
                    col_centres.append(xc)
                else:
                    # Merge: keep the average
                    col_centres[-1] = (col_centres[-1] + xc) / 2

            num_cols = len(col_centres)

            # ── Step 3: write header separator then rows ───────────────────
            writer.writerow([f"--- PAGE {page_num} ---"] + [""] * (num_cols - 1))

            for row in rows:
                cells = [""] * num_cols
                for item in row:
                    xc = _x_centre(item)
                    # Find nearest column
                    col_idx = min(range(num_cols), key=lambda c: abs(col_centres[c] - xc))
                    text = getattr(item, "text", "") or ""
                    # Append if two items land on the same column in one row
                    cells[col_idx] = (cells[col_idx] + " " + text).strip() if cells[col_idx] else text
                writer.writerow(cells)

            writer.writerow([])  # blank row between pages


def write_layout_txt(result, out_path: Path, grid_cols: int = 120) -> None:
    """
    Write a spatial text-layout file that approximates the visual arrangement
    of the original document.

    Each page is rendered as a fixed-width character grid with text items
    placed at positions proportional to their bounding boxes.  Character-cell
    aspect ratio (approx. 2:1 height:width) is accounted for when computing
    the number of grid rows so vertical and horizontal spacing look natural
    in a monospace viewer.

    Opens cleanly in any plain-text editor set to a monospace font.
    """
    CHAR_ASPECT = 2.0  # typical monospace char height / width ratio
    pages = getattr(result, "pages", []) or []
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        for page in pages:
            page_num = page.page_no + 1
            page_w = getattr(page, "width", 0) or 0
            page_h = getattr(page, "height", 0) or 0
            items = getattr(page, "text_items", []) or []

            fh.write("=" * grid_cols + "\n")
            fh.write(f"  PAGE {page_num}\n")
            fh.write("=" * grid_cols + "\n")

            if not items or page_w <= 0 or page_h <= 0:
                # No spatial data — fall back to raw text lines
                for item in items:
                    text = getattr(item, "text", "") or ""
                    if text.strip():
                        fh.write(text + "\n")
                fh.write("\n")
                continue

            # Derive grid rows from page aspect ratio, corrected for char aspect
            grid_rows = max(20, int(grid_cols * (page_h / page_w) / CHAR_ASPECT))

            # Build an empty character grid
            grid: list[list[str]] = [[" "] * grid_cols for _ in range(grid_rows)]

            for item in items:
                text = getattr(item, "text", "") or ""
                if not text.strip():
                    continue
                ix = getattr(item, "x", 0) or 0
                iy = getattr(item, "y", 0) or 0

                col = int(ix / page_w * grid_cols)
                row = int(iy / page_h * grid_rows)
                col = max(0, min(col, grid_cols - 1))
                row = max(0, min(row, grid_rows - 1))

                for i, ch in enumerate(text):
                    dest = col + i
                    if dest >= grid_cols:
                        break
                    grid[row][dest] = ch

            for grid_row in grid:
                fh.write("".join(grid_row).rstrip() + "\n")

            fh.write("\n")


def write_markdown(result, out_path: Path) -> None:
    """Write the whole-document Markdown produced by LiteParse (one block per page,
    separated by a `---` rule). Empty/no-op if the backend didn't produce Markdown."""
    markdown = getattr(result, "markdown", "") or ""
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        fh.write(markdown)


def evaluate_document(
    path: Path,
    ocr_enabled: bool = True,
    tessdata_path: str | None = None,
    dpi: int = 150,
    csv_path: Path | None = None,
    tabular_csv_path: Path | None = None,
    txt_path: Path | None = None,
) -> DocumentReport:
    kwargs: dict = dict(
        ocr_enabled=ocr_enabled,
        dpi=dpi,
        quiet=True,
    )
    if tessdata_path:
        kwargs["tessdata_path"] = tessdata_path

    backend = get_backend("liteparse", **kwargs)

    t0 = time.perf_counter()
    try:
        result = backend.parse(str(path))
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

    if csv_path is not None:
        write_items_csv(result, csv_path)

    if tabular_csv_path is not None:
        write_tabular_csv(result, tabular_csv_path)

    if txt_path is not None:
        write_layout_txt(result, txt_path)

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
        print(f"  Near-empty pages     : {tq.near_empty_pages}  (<50 chars, possible issue)")
        print(f"  Min / Max chars/page : {tq.min_chars_on_page:,} / {tq.max_chars_on_page:,}")

    bb = report.bbox
    if bb:
        print("\n  -- Bounding Box Accuracy --")
        print(f"  Total text items     : {bb.total_text_items:,}")
        print(f"  Avg items/page       : {bb.avg_items_per_page:.1f}")
        print(f"  Pages with no items  : {bb.pages_with_no_items}")
        print(f"  Zero-size items      : {bb.items_with_zero_size}  (width or height = 0)")
        print(f"  Out-of-bounds items  : {bb.items_out_of_bounds}  (exceed page dimensions)")
        cov = bb.avg_page_coverage
        cov_min = bb.min_page_coverage
        cov_max = bb.max_page_coverage
        print(f"  Page coverage        : avg={cov:.1%}  min={cov_min:.1%}  max={cov_max:.1%}")


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
        print(f"  Total near-empty pages : {all_near_empty}  (possible OCR/extraction issues)")

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
        print(f"    Zero-size items    : {total_zero_size:,}  ({zero_pct:.2%} of all items)")
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
    return sorted(p for p in input_path.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS)


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
        "--no-ocr",
        action="store_true",
        default=False,
        help="Disable Tesseract OCR. OCR is on by default; use this flag for faster runs on native-text PDFs.",
    )
    ap.add_argument(
        "--no-csv",
        action="store_true",
        default=False,
        help="Skip writing per-file CSV exports. CSV is written by default alongside JSON reports.",
    )
    ap.add_argument(
        "--txt",
        action="store_true",
        default=False,
        help="Write a *_layout.txt file for each document that spatially reproduces the page layout in plain text.",
    )
    ap.add_argument(
        "--tabular-csv",
        action="store_true",
        default=False,
        help="Write a *_tabular.csv file per document: rows and columns clustered from bounding-box positions, ready to open in Excel as a structured table.",
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

    ocr_enabled = not args.no_ocr
    ocr_label = "on" if ocr_enabled else "off (--no-ocr)"
    print(f"Found {len(files)} document(s).  OCR={ocr_label}  DPI={args.dpi}")

    reports: list[DocumentReport] = []
    for f in files:
        print(f"Parsing: {f.name} ... ", end="", flush=True)
        csv_path = None if args.no_csv else output_dir / (f.stem + "_items.csv")
        txt_path = output_dir / (f.stem + "_layout.txt") if args.txt else None
        tabular_csv_path = output_dir / (f.stem + "_tabular.csv") if args.tabular_csv else None
        report = evaluate_document(
            f,
            ocr_enabled=ocr_enabled,
            tessdata_path=args.tessdata,
            dpi=args.dpi,
            csv_path=csv_path,
            tabular_csv_path=tabular_csv_path,
            txt_path=txt_path,
        )
        reports.append(report)

        status = "ERROR" if report.error else f"OK ({report.page_count} pages)"
        print(status)

        if not args.json_only:
            print_document_report(report)

        # Per-file JSON report
        out_file = output_dir / (f.stem + "_liteparse_report.json")
        with out_file.open("w", encoding="utf-8") as fh:
            json.dump(document_report_dict(report), fh, indent=2)

    print_summary(reports)

    # Combined report
    combined_path = output_dir / "combined_report.json"
    with combined_path.open("w", encoding="utf-8") as fh:
        json.dump([document_report_dict(r) for r in reports], fh, indent=2)

    print(f"\nJSON reports saved to: {output_dir.resolve()}/")
    if not args.no_csv:
        csv_count = sum(1 for r in reports if not r.error)
        print(f"CSV exports saved to:  {output_dir.resolve()}/  ({csv_count} file(s), *_items.csv)")
    if args.txt:
        txt_count = sum(1 for r in reports if not r.error)
        print(f"Layout TXT saved to:   {output_dir.resolve()}/  ({txt_count} file(s), *_layout.txt)")
    if args.tabular_csv:
        tab_count = sum(1 for r in reports if not r.error)
        print(f"Tabular CSV saved to:  {output_dir.resolve()}/  ({tab_count} file(s), *_tabular.csv)")


if __name__ == "__main__":
    main()
