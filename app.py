"""
LiteParse Evaluator — NiceGUI Front-End
========================================
Provides a browser-based UI to:
  • Browse and select documents from the samples/ folder
  • Configure parse settings (OCR, DPI)
  • Enter expected keywords for Option-B verification
  • Run evaluation and view per-document results in tabbed cards

Run with:
    python app.py
Then open http://localhost:8080 in your browser.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path

from liteparse import LiteParse
from nicegui import run, ui

from evaluate import (
    DocumentReport,
    evaluate_bboxes,
    evaluate_text_quality,
    write_items_csv,
    write_layout_txt,
    write_tabular_csv,
)
from quality_check import (
    CoherenceReport,
    KeywordCheckReport,
    coherence_check,
    keyword_check,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent
SAMPLES_DIR = BASE_DIR / "samples"
RESULTS_DIR = BASE_DIR / "results"

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
    ".png",
    ".jpg",
    ".jpeg",
    ".tiff",
    ".bmp",
    ".webp",
}


# ---------------------------------------------------------------------------
# Module-level parse + evaluate function (runs in a thread via run.io_bound)
# ---------------------------------------------------------------------------


def _parse_and_evaluate(
    path: Path,
    ocr: bool,
    dpi: int,
    keywords: list[str],
    csv_enabled: bool = True,
    txt_enabled: bool = False,
    tabular_enabled: bool = True,
    results_dir: Path | None = None,
) -> tuple[DocumentReport, KeywordCheckReport | None, CoherenceReport, Path | None, Path | None, Path | None]:
    """
    Parse the document once and run all quality checks.
    Designed to be called via run.io_bound() so the UI stays responsive.
    Returns (doc_report, kw_report, co_report, csv_path_or_None, txt_path_or_None, tabular_csv_path_or_None).
    """
    parser = LiteParse(ocr_enabled=ocr, dpi=dpi, quiet=True)
    t0 = time.perf_counter()
    try:
        result = parser.parse(str(path))
    except Exception as exc:
        return (
            DocumentReport(
                file_path=str(path),
                file_name=path.name,
                parse_time_seconds=round(time.perf_counter() - t0, 3),
                page_count=0,
                error=str(exc),
            ),
            None,
            CoherenceReport(
                total_tokens=0,
                real_word_ratio=0.0,
                broken_word_ratio=0.0,
                numeric_ratio=0.0,
                score=0.0,
            ),
            None,
            None,
            None,
        )

    elapsed = round(time.perf_counter() - t0, 3)
    doc_report = DocumentReport(
        file_path=str(path),
        file_name=path.name,
        parse_time_seconds=elapsed,
        page_count=len(result.pages or []),
        text_quality=evaluate_text_quality(result),
        bbox=evaluate_bboxes(result),
    )
    kw_report = keyword_check(result, keywords) if keywords else None
    co_report = coherence_check(result)

    csv_out: Path | None = None
    if csv_enabled and results_dir is not None:
        csv_out = results_dir / (path.stem + "_items.csv")
        write_items_csv(result, csv_out)

    txt_out: Path | None = None
    if txt_enabled and results_dir is not None:
        txt_out = results_dir / (path.stem + "_layout.txt")
        write_layout_txt(result, txt_out)

    tabular_out: Path | None = None
    if tabular_enabled and results_dir is not None:
        tabular_out = results_dir / (path.stem + "_tabular.csv")
        write_tabular_csv(result, tabular_out)

    return doc_report, kw_report, co_report, csv_out, txt_out, tabular_out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def list_samples() -> list[Path]:
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(p for p in SAMPLES_DIR.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------


@ui.page("/")
def page() -> None:
    selected: set[str] = set()
    file_checkbox_map: dict[str, ui.checkbox] = {}

    # ── Header ────────────────────────────────────────────────────────────
    with ui.header(elevated=True).classes("bg-blue-700 text-white items-center px-6 py-3 gap-3"):
        ui.icon("description").classes("text-2xl")
        ui.label("LiteParse Evaluator").classes("text-xl font-bold")
        ui.space()
        ui.label("Text Extraction & Bounding Box Quality Testing").classes("text-sm opacity-70")

    # ── Body ──────────────────────────────────────────────────────────────
    with ui.row().classes("w-full gap-0 items-start"):
        # ── LEFT SIDEBAR ──────────────────────────────────────────────────
        with ui.column().classes("w-80 min-h-screen bg-gray-50 border-r border-gray-200 p-4 gap-4 shrink-0"):
            # --- File browser ---
            with ui.card().classes("w-full"):
                with ui.row().classes("items-center justify-between w-full mb-1"):
                    ui.label("Documents").classes("font-semibold text-gray-700 text-base")
                    ui.button(icon="refresh", on_click=lambda: _refresh()).props("flat dense round").tooltip(
                        "Rescan samples/ folder"
                    )

                ui.separator()

                with ui.scroll_area().classes("h-52 w-full"):
                    file_list_col = ui.column().classes("w-full gap-0 pr-2")

                with ui.row().classes("gap-2 mt-2"):
                    ui.button("Select all", on_click=lambda: _select_all(True)).props("flat dense size=sm outline")
                    ui.button("Clear", on_click=lambda: _select_all(False)).props("flat dense size=sm outline")

                ui.label("Drop files into the samples/ folder, then refresh.").classes(
                    "text-xs text-gray-400 mt-2 leading-snug"
                )

            # --- Settings ---
            with ui.card().classes("w-full"):
                ui.label("Settings").classes("font-semibold text-gray-700 text-base mb-2")

                ocr_switch = ui.switch("Enable Tesseract OCR", value=True).tooltip(
                    "OCR is on by default — LiteParse only runs Tesseract on pages where "
                    "native text extraction returns nothing, so the cost on digital PDFs is negligible. "
                    "Disable for maximum speed on known native-text documents."
                )
                dpi_input = (
                    ui.number("Render DPI", value=150, min=72, max=600, step=50, format="%.0f")
                    .classes("w-full mt-3")
                    .tooltip("Higher DPI improves OCR accuracy but increases parse time.")
                )
                csv_switch = (
                    ui.switch("Export to CSV", value=True)
                    .classes("mt-2")
                    .tooltip(
                        "Save a *_items.csv file alongside each JSON report. "
                        "Opens in Excel with columns: page, item, x, y, width, height, text."
                    )
                )
                txt_switch = (
                    ui.switch("Export Layout TXT", value=True)
                    .classes("mt-2")
                    .tooltip(
                        "Save a *_layout.txt file that reproduces the visual layout of each page in plain text. "
                        "Text items are placed at their bounding-box positions on a character grid — "
                        "best viewed in a monospace editor."
                    )
                )
                tabular_switch = (
                    ui.switch("Export Tabular CSV (Excel)", value=True)
                    .classes("mt-2")
                    .tooltip(
                        "Save a *_tabular.csv file where rows and columns are clustered from bounding-box "
                        "positions — open directly in Excel to see the report reconstructed as a table "
                        "with partner rows, header columns, and numeric values aligned."
                    )
                )

            # --- Keywords ---
            with ui.card().classes("w-full"):
                ui.label("Expected Keywords").classes("font-semibold text-gray-700 text-base")
                ui.label("One snippet per line — verified against every selected document.").classes(
                    "text-xs text-gray-400 mb-2 leading-snug"
                )

                keywords_area = (
                    ui.textarea(placeholder="Net Asset Value\n31 December 2025\nTotal Return")
                    .classes("w-full")
                    .props("outlined dense rows=5")
                )

            # --- Run button ---
            run_btn = (
                ui.button("Run Evaluation", icon="play_circle", on_click=lambda: _run())
                .classes("w-full mt-1")
                .props("color=blue size=lg")
            )

        # ── RIGHT MAIN AREA ────────────────────────────────────────────────
        with ui.column().classes("flex-1 p-5 gap-4 min-w-0"):
            # Status bar
            with ui.row().classes("items-center gap-3 w-full"):
                spinner = ui.spinner(size="sm")
                spinner.set_visibility(False)
                status_label = ui.label("Select documents from the sidebar and click Run Evaluation.").classes(
                    "text-gray-500 text-sm"
                )

            results_col = ui.column().classes("w-full gap-4")

    # ── Inner functions (closures) ─────────────────────────────────────────

    def _get_keywords() -> list[str]:
        raw = keywords_area.value or ""
        return [ln.strip() for ln in raw.splitlines() if ln.strip()]

    def _populate_files() -> None:
        file_list_col.clear()
        file_checkbox_map.clear()
        files = list_samples()
        if not files:
            with file_list_col:
                ui.label("No supported files found.").classes("text-xs text-gray-400 italic p-2")
            return
        for f in files:
            with file_list_col:
                chk = ui.checkbox(f.name, value=f.name in selected).classes("w-full text-sm")
                chk.on_value_change(lambda e, name=f.name: _toggle(name, e.value))  # pyright: ignore[reportArgumentType]
                file_checkbox_map[f.name] = chk

    def _toggle(name: str, checked: bool) -> None:
        if checked:
            selected.add(name)
        else:
            selected.discard(name)

    def _refresh() -> None:
        _populate_files()
        ui.notify("File list refreshed", type="positive", timeout=1200)

    def _select_all(state: bool) -> None:
        if state:
            selected.update(f.name for f in list_samples())
        else:
            selected.clear()
        _populate_files()

    async def _run() -> None:
        paths = [SAMPLES_DIR / n for n in sorted(selected)]
        if not paths:
            ui.notify("No documents selected.", type="warning")
            return

        keywords = _get_keywords()
        ocr = bool(ocr_switch.value)
        dpi = int(dpi_input.value or 150)
        csv_enabled = bool(csv_switch.value)
        txt_enabled = bool(txt_switch.value)
        tabular_enabled = bool(tabular_switch.value)

        run_btn.props("loading disable")
        spinner.set_visibility(True)
        results_col.clear()
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)

        all_results = []
        for path in paths:
            status_label.set_text(f"Parsing: {path.name} …")
            doc_report, kw_report, co_report, csv_path, txt_path, tabular_path = await run.io_bound(  # pyright: ignore[reportGeneralTypeIssues]
                _parse_and_evaluate, path, ocr, dpi, keywords, csv_enabled, txt_enabled, tabular_enabled, RESULTS_DIR
            )
            all_results.append((doc_report, kw_report, co_report))

            # Save JSON report
            out = RESULTS_DIR / (path.stem + "_report.json")
            with out.open("w", encoding="utf-8") as fh:
                json.dump(asdict(doc_report), fh, indent=2)

            _render_result_card(results_col, doc_report, kw_report, co_report, csv_path, txt_path, tabular_path)

        ok = sum(1 for r, _, __ in all_results if not r.error)
        extra_notes = []
        if csv_enabled:
            extra_notes.append("CSV")
        if txt_enabled:
            extra_notes.append("Layout TXT")
        if tabular_enabled:
            extra_notes.append("Tabular CSV")
        exports_note = ("  · " + " & ".join(extra_notes) + " saved to results/") if extra_notes else ""
        status_label.set_text(
            f"Done — {ok} / {len(paths)} document(s) parsed OK.  JSON reports saved to results/{exports_note}"
        )
        spinner.set_visibility(False)
        run_btn.props(remove="loading disable")
        ui.notify(
            f"Evaluation complete: {ok} / {len(paths)} OK",
            type="positive" if ok == len(paths) else "warning",
        )

    # ── Card rendering ─────────────────────────────────────────────────────

    def _render_result_card(
        container,
        doc: DocumentReport,
        kw: KeywordCheckReport | None,
        co: CoherenceReport | None,
        csv_path: Path | None = None,
        txt_path: Path | None = None,
        tabular_path: Path | None = None,
    ) -> None:
        icon = "error" if doc.error else "check_circle"
        subtitle_color = "text-red-500" if doc.error else "text-green-600"
        subtitle = f"ERROR: {doc.error}" if doc.error else f"{doc.page_count} page(s) · {doc.parse_time_seconds:.2f}s"

        with (
            container,
            ui.expansion(doc.file_name, icon=icon)
            .classes("w-full shadow-sm rounded-lg border border-gray-200")
            .props("default-opened"),
        ):
            ui.label(subtitle).classes(f"text-sm {subtitle_color} mb-3")

            if doc.error:
                return

            if csv_path is not None and csv_path.exists():
                ui.button(
                    "Download CSV",
                    icon="download",
                    on_click=lambda p=csv_path: ui.download(p.read_bytes(), filename=p.name),  # pyright: ignore[reportAttributeAccessIssue]
                ).props("flat dense size=sm outline").classes("mb-3").tooltip(
                    "Download the parsed text items as a CSV file — "
                    "open in Excel to review page, x/y position, and extracted text for every item."
                )

            if txt_path is not None and txt_path.exists():
                ui.button(
                    "Download Layout TXT",
                    icon="text_snippet",
                    on_click=lambda p=txt_path: ui.download(p.read_bytes(), filename=p.name),  # pyright: ignore[reportAttributeAccessIssue]
                ).props("flat dense size=sm outline").classes("mb-3").tooltip(
                    "Download the spatial layout text file — open in a monospace editor "
                    "to see text items placed at their bounding-box positions on a character grid."
                )

            if tabular_path is not None and tabular_path.exists():
                ui.button(
                    "Download Tabular CSV (Excel)",
                    icon="table_chart",
                    on_click=lambda p=tabular_path: ui.download(p.read_bytes(), filename=p.name),  # pyright: ignore[reportAttributeAccessIssue]
                ).props("flat dense size=sm outline color=green").classes("mb-3").tooltip(
                    "Download the tabular CSV — open in Excel to see the report reconstructed "
                    "as a table with rows and columns matching the original document layout."
                )

            with ui.tabs().classes("w-full") as tabs:
                tab_text = ui.tab("Text Quality", icon="text_fields")
                tab_bbox = ui.tab("Bounding Boxes", icon="crop_free")
                tab_coh = ui.tab("Coherence", icon="spellcheck")
                if kw is not None:
                    tab_kw = ui.tab("Keywords", icon="search")

            with ui.tab_panels(tabs, value=tab_text).classes("w-full pt-2"):
                with ui.tab_panel(tab_text):
                    _panel_text_quality(doc)
                with ui.tab_panel(tab_bbox):
                    _panel_bbox(doc)
                with ui.tab_panel(tab_coh):
                    _panel_coherence(co)
                if kw is not None:
                    with ui.tab_panel(tab_kw):
                        _panel_keywords(kw)

    def _metric_grid(rows: list[tuple[str, str, str]]) -> None:
        """Render a two-column label/value grid. rows = (label, value, tailwind_color)."""
        with ui.grid(columns=2).classes("w-full gap-x-8 gap-y-1 text-sm max-w-lg"):
            for label, value, color in rows:
                ui.label(label).classes("text-gray-500")
                ui.label(value).classes(f"font-medium {color or 'text-gray-800'}")

    def _panel_text_quality(doc: DocumentReport) -> None:
        tq = doc.text_quality
        if not tq:
            ui.label("No data available.").classes("text-gray-400 text-sm")
            return

        def issue_color(n, threshold):
            return "text-red-500" if n > threshold else ""

        rows = [
            ("Total characters", f"{tq.total_chars:,}", ""),
            ("Total words", f"{tq.total_words:,}", ""),
            ("Avg chars / page", f"{tq.avg_chars_per_page:,.1f}", ""),
            ("Char std-dev", f"{tq.char_stddev:,.1f}", ""),
            (
                "Empty pages",
                f"{tq.empty_pages} of {tq.page_count}",
                issue_color(tq.empty_pages, 0),
            ),
            (
                "Near-empty pages (<50 chars)",
                str(tq.near_empty_pages),
                issue_color(tq.near_empty_pages, 0),
            ),
            (
                "Min / Max chars on a page",
                f"{tq.min_chars_on_page:,} / {tq.max_chars_on_page:,}",
                "",
            ),
        ]
        _metric_grid(rows)

        bad = tq.empty_pages + tq.near_empty_pages
        if bad:
            ui.label(
                f"⚠ {bad} page(s) may have extraction issues — consider enabling OCR if these are scanned pages."
            ).classes("text-amber-600 text-xs mt-3")

    def _panel_bbox(doc: DocumentReport) -> None:
        bb = doc.bbox
        if not bb:
            ui.label("No data available.").classes("text-gray-400 text-sm")
            return

        def warn(n):
            return "text-amber-600" if n > 0 else ""

        rows = [
            ("Total text items", f"{bb.total_text_items:,}", ""),
            ("Avg items / page", f"{bb.avg_items_per_page:.1f}", ""),
            (
                "Pages with no items",
                str(bb.pages_with_no_items),
                warn(bb.pages_with_no_items),
            ),
            (
                "Zero-size items",
                str(bb.items_with_zero_size),
                warn(bb.items_with_zero_size),
            ),
            (
                "Out-of-bounds items",
                str(bb.items_out_of_bounds),
                warn(bb.items_out_of_bounds),
            ),
            ("Coverage avg", f"{bb.avg_page_coverage:.1%}", ""),
            (
                "Coverage min / max",
                f"{bb.min_page_coverage:.1%} / {bb.max_page_coverage:.1%}",
                "",
            ),
        ]
        _metric_grid(rows)

    def _panel_coherence(co: CoherenceReport | None) -> None:
        if not co:
            ui.label("No data available.").classes("text-gray-400 text-sm")
            return

        score_color = "text-green-600" if co.score >= 0.75 else "text-amber-500" if co.score >= 0.50 else "text-red-500"
        rows = [
            ("Overall coherence score", f"{co.score:.0%}", score_color),
            ("Valid token ratio (words + numbers)", f"{co.real_word_ratio:.0%}", ""),
            ("Numeric token ratio", f"{co.numeric_ratio:.0%}", ""),
            (
                "Broken-word ratio",
                f"{co.broken_word_ratio:.0%}",
                "text-amber-600" if co.broken_word_ratio > 0.05 else "",
            ),
            ("Total tokens analysed", f"{co.total_tokens:,}", ""),
        ]
        _metric_grid(rows)

        for note in co.notes or []:
            ui.label(f"⚠ {note}").classes("text-amber-600 text-xs mt-1 leading-snug")

    def _panel_keywords(kw: KeywordCheckReport) -> None:
        total = kw.snippets_tested
        found = kw.snippets_found
        pct = found / total if total else 0
        summary_color = "text-green-600" if pct == 1.0 else "text-amber-600" if pct > 0 else "text-red-500"
        ui.label(f"{found} / {total} snippets found").classes(f"font-semibold {summary_color} mb-3 text-base")

        for r in kw.results:
            with ui.row().classes("items-start gap-2 mb-2"):
                icon_name = "check_circle" if r.found else "cancel"
                icon_color = "text-green-600" if r.found else "text-red-500"
                ui.icon(icon_name).classes(f"{icon_color} text-lg mt-0.5 shrink-0")
                with ui.column().classes("gap-0 min-w-0"):
                    page_info = f"  (page {r.page_found})" if r.page_found else ""
                    ui.label(f'"{r.snippet}"{page_info}').classes("text-sm font-mono break-all")
                    if r.found and r.context:
                        ui.label(f"…{r.context}…").classes("text-xs text-gray-400 leading-snug break-all")

    # ── Initial population ────────────────────────────────────────────────
    _populate_files()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        title="LiteParse Evaluator",
        port=8080,
        reload=False,
        favicon="📄",
    )
