"""Real tests for app.py's list_samples() helper.

Importing `app` triggers NiceGUI's `@ui.page("/")` decoration, which only
registers a route (no server, no browser) and is safe at import time.
"""

from __future__ import annotations

import app


class TestListSamples:
    def test_creates_samples_dir_if_missing(self, tmp_path, monkeypatch):
        samples_dir = tmp_path / "samples"
        monkeypatch.setattr(app, "SAMPLES_DIR", samples_dir)

        assert not samples_dir.exists()
        result = app.list_samples()

        assert samples_dir.exists()
        assert result == []

    def test_lists_only_supported_extensions(self, tmp_path, monkeypatch):
        samples_dir = tmp_path / "samples"
        samples_dir.mkdir()
        (samples_dir / "report.pdf").write_bytes(b"%PDF-1.4")
        (samples_dir / "notes.txt").write_text("not supported")
        (samples_dir / "data.xlsx").write_bytes(b"fake xlsx")
        monkeypatch.setattr(app, "SAMPLES_DIR", samples_dir)

        result = app.list_samples()

        names = {p.name for p in result}
        assert names == {"report.pdf", "data.xlsx"}

    def test_ignores_subdirectories(self, tmp_path, monkeypatch):
        samples_dir = tmp_path / "samples"
        samples_dir.mkdir()
        (samples_dir / "report.pdf").write_bytes(b"%PDF-1.4")
        (samples_dir / "subfolder").mkdir()
        monkeypatch.setattr(app, "SAMPLES_DIR", samples_dir)

        result = app.list_samples()

        assert len(result) == 1
        assert result[0].name == "report.pdf"

    def test_results_are_sorted(self, tmp_path, monkeypatch):
        samples_dir = tmp_path / "samples"
        samples_dir.mkdir()
        (samples_dir / "zeta.pdf").write_bytes(b"%PDF-1.4")
        (samples_dir / "alpha.pdf").write_bytes(b"%PDF-1.4")
        monkeypatch.setattr(app, "SAMPLES_DIR", samples_dir)

        result = app.list_samples()

        assert [p.name for p in result] == ["alpha.pdf", "zeta.pdf"]

    def test_extension_matching_is_case_insensitive(self, tmp_path, monkeypatch):
        samples_dir = tmp_path / "samples"
        samples_dir.mkdir()
        (samples_dir / "REPORT.PDF").write_bytes(b"%PDF-1.4")
        monkeypatch.setattr(app, "SAMPLES_DIR", samples_dir)

        result = app.list_samples()

        assert len(result) == 1
