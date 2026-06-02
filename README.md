# LiteParse Evaluator

A **local, no-API-key document parsing quality bench** built on [LiteParse](https://developers.llamaindex.ai/liteparse/) — the Rust-backed PDF / Office / image parser from LlamaIndex.

Drop documents into `samples/`, launch the NiceGUI browser app, and immediately see text-extraction quality, bounding-box accuracy, and reading-order coherence scores side-by-side.

---

## Features

- **Text extraction quality** — character count, word count, avg chars per page, empty / near-empty page detection
- **Bounding box accuracy** — total text items, zero-size items, out-of-bounds coordinates, page coverage ratio
- **Reading-order coherence (Option C)** — token classification (words, numbers, broken-word artefacts, garbage symbols) → 0–1 score, advisory notes
- **Keyword / snippet verification (Option B)** — paste expected text strings; the app checks each one against the parsed output and shows the surrounding context
- **NiceGUI front-end** — file browser, settings panel, tabbed result cards, live JSON export
- **CLI mode** — `evaluate.py` for headless / batch use

---

## Project layout

```
liteparse_eval/
  app.py                   # NiceGUI browser front-end
  evaluate.py              # CLI batch evaluator
  quality_check.py         # Option B (keywords) + Option C (coherence)
  check_changelog_reminder.py
  pyproject.toml
  requirements.txt         # runtime deps: liteparse, nicegui
  requirements-dev.txt     # dev / CI deps: ruff, bandit, pyright, etc.
  setup-env.ps1            # one-shot venv bootstrap
  samples/                 # drop documents here — gitignored except .gitkeep
  results/                 # JSON reports written here — gitignored
```

---

## Quick start

```powershell
# 1. Create virtual environment and install dependencies
powershell -ExecutionPolicy Bypass -File setup-env.ps1

# 2. Activate the venv
.\.venv\Scripts\Activate.ps1

# 3. Drop one or more documents into samples\

# 4. Launch the browser UI
python app.py
# → open http://localhost:8080
```

### CLI (headless / batch)

```powershell
# Parse all documents in the current folder
python evaluate.py

# Parse a single file with OCR enabled
python evaluate.py samples\report.pdf --ocr

# Point at a specific tessdata folder (offline)
python evaluate.py --ocr --tessdata C:\path\to\tessdata
```

---

## OCR notes

OCR is **disabled by default** for speed. Enable it with the toggle in the UI or `--ocr` on the CLI.

- The first OCR run downloads `eng.traineddata` automatically to `~\AppData\Roaming\tesseract-rs\tessdata`.
- For offline use, download [`eng.traineddata`](https://github.com/tesseract-ocr/tessdata) manually and pass `--tessdata <dir>`.

---

## Development

```powershell
# Install dev tools on top of the runtime venv
pip install -r requirements-dev.txt

# Run linter + formatter
ruff check .
ruff format .

# Run security scan
bandit -r . -c pyproject.toml

# Install pre-commit hooks (runs ruff + bandit on every commit)
pre-commit install
```

---

## CI

GitHub Actions runs on every push / PR to `main`:

1. Ruff lint
2. Ruff format check
3. Pyright type check
4. Security scan (bandit)
5. Dependency audit (pip-audit)
