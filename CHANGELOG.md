# Changelog

All notable changes to LiteParse Evaluator.

## [Unreleased]

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
