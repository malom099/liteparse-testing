# Changelog

All notable changes to LiteParse Evaluator.

## [Unreleased]

### Added

- Exit/close button in the header of the NiceGUI UI — opens a confirmation dialog, then
  shuts down the app and terminates the running process (ending the terminal session it
  was launched from) rather than just stopping the browser tab.

### Security

- **Python runtime upgrade 3.11.4 → 3.12.13** — `.venv` recreated on Python 3.12.13;
  dependencies reinstalled (`liteparse` 2.5.1, `nicegui` 3.14.0). `requires-python`,
  `[tool.ruff] target-version`, and `[tool.pyright] pythonVersion` bumped to
  `>=3.12`/`py312`/`"3.12"` in `pyproject.toml`; CI workflow (`.github/workflows/ci.yml`)
  updated to Python 3.12. Verified with a real end-to-end launch (`python app.py`) —
  `GET /` returned 200 on Python 3.12.13, not just a passing test suite.
  - Removed a redundant, conflicting standalone `pyrightconfig.json` (missing
    `venvPath`/`extraPaths`, causing a false `reportMissingImports` on `liteparse`) —
    same root cause and fix as found in prior projects' migrations.
  - `bandit -c pyproject.toml -r .`: 0 issues. `ruff check .` could not be run standalone
    due to the known, pre-existing Windows Defender lock on freshly-extracted `ruff.exe`
    in new `.venv`s (environment issue, unrelated to 3.12 compatibility).

### Added

- **First real automated test suite for this project** — previously had zero tests.
  Added `pytest`/`pytest-cov` as dev dependencies, `[tool.pytest.ini_options]` in
  `pyproject.toml`, and a `tests/` package with 41 real tests covering the project's
  actual business logic (not smoke tests):
  - `tests/test_quality_check.py` (15 tests) — `keyword_check()` (found/missing snippets,
    case-insensitivity, correct page attribution, context-excerpt extraction, empty input)
    and `coherence_check()` (empty-document handling, clean-prose high score, financial
    numeric tokens, broken-word/hyphenation penalty, garbage-symbol penalty, heavily-numeric
    advisory note, low-score advisory note, score bounds).
  - `tests/test_evaluate.py` (21 tests) — `evaluate_text_quality()` and `evaluate_bboxes()`
    (empty/near-empty page classification, zero-size and out-of-bounds bounding-box
    detection, coverage-ratio math including the 100%-cap edge case), plus real file-I/O
    tests (via `tmp_path`) for all three export formats: `write_items_csv()`,
    `write_tabular_csv()` (row/column clustering algorithm), and `write_layout_txt()`
    (character-grid layout reconstruction, including its no-spatial-data fallback path).
  - `tests/test_app_helpers.py` (5 tests) — `list_samples()` (directory auto-creation,
    extension filtering, subdirectories ignored, sorted output, case-insensitive matching).
  - `tests/conftest.py` — lightweight duck-typed `FakeItem`/`FakePage`/`FakeResult`
    dataclasses standing in for real LiteParse result objects, so tests exercise the
    project's own logic directly rather than mocking the whole `liteparse` package.
  - Coverage: `quality_check.py` 98%, `evaluate.py` 55%, `app.py` 9% (the untested ~91% of
    `app.py` is genuine NiceGUI UI-construction code — `ui.button()`/`ui.checkbox()` wiring
    — not meaningfully unit-testable without a live browser runtime; the one testable
    pure-logic helper it contained, `list_samples()`, is fully covered).

### Fixed

- **`ui.run()` called at module level in `app.py` (not guarded by `if __name__ ==
"__main__"`)** — meant simply `import app` (e.g. from a test, or any other tool) started
  a real, blocking NiceGUI web server and never returned. Found while writing
  `test_app_helpers.py` (the import hung indefinitely). Guarded behind
  `if __name__ in {"__main__", "__mp_main__"}:`, matching the standard NiceGUI entry-point
  pattern already used correctly elsewhere in this workspace — `python app.py` behavior is
  unchanged, but the module can now be safely imported for testing or reuse.

---

## [0.2.0] — 2026-06-02

### Added

- **CSV export** — `evaluate.py` now writes a `*_items.csv` file for every parsed document (alongside the JSON report) with columns `page`, `item`, `x`, `y`, `width`, `height`, `text`. Opens directly in Excel; UTF-8 BOM ensures correct encoding auto-detection.
- **`--no-csv` flag** — pass to `evaluate.py` to suppress CSV output when not needed.
- **"Export to CSV" toggle** in the NiceGUI app — on by default; saves `*_items.csv` to `results/` after each run.
- **"Download CSV" button** in each result card — click to download the CSV straight from the browser.

---

## [0.1.0] — 2026-06-02

### Added

- **Initial release** — CLI evaluator (`evaluate.py`) and NiceGUI browser app (`app.py`).
- **Text extraction quality metrics** — total chars/words, avg and stddev chars per page, empty-page and near-empty-page detection.
- **Bounding box accuracy metrics** — total text items, zero-size items, out-of-bounds coordinate detection, per-page coverage ratio.
- **Option B: keyword / snippet verification** (`quality_check.py`) — checks expected text strings against parsed output and reports page location with surrounding context.
- **Option C: reading-order coherence scoring** (`quality_check.py`) — token classification (alphabetic, numeric, broken-word, garbage) → 0–1 score with advisory notes.
- **`samples/` folder** — designated drop zone for test documents; gitignored.
- **`results/` folder** — JSON reports written here after each run; gitignored.
- **`setup-env.ps1`** — one-shot PowerShell venv bootstrap.
- **`pyproject.toml`** — Ruff, Pyright, Bandit, and Vulture configuration.
- **`requirements-dev.txt`** — dev / CI tooling.
- **Pre-commit hooks** — Ruff lint/format + Bandit security scan + changelog reminder.
- **GitHub Actions CI** — lint, format check, type check, security scan, dependency audit.
- **Dependabot** — weekly pip dependency updates.
