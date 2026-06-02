# setup-env.ps1 — creates a virtual environment and installs dependencies

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition

Write-Host "==> Creating virtual environment..." -ForegroundColor Cyan
python -m venv "$ScriptDir\.venv"

Write-Host "==> Activating virtual environment..." -ForegroundColor Cyan
& "$ScriptDir\.venv\Scripts\Activate.ps1"

Write-Host "==> Installing dependencies..." -ForegroundColor Cyan
& "$ScriptDir\.venv\Scripts\python.exe" -m pip install --upgrade pip
& "$ScriptDir\.venv\Scripts\python.exe" -m pip install -r "$ScriptDir\requirements.txt"

Write-Host "==> Pre-downloading Tesseract eng.traineddata..." -ForegroundColor Cyan
# Trigger a lightweight parse of an empty byte string so LiteParse downloads
# eng.traineddata now rather than on the first real document run.
try {
    & "$ScriptDir\.venv\Scripts\python.exe" -c @"
from liteparse import LiteParse
try:
    LiteParse(ocr_enabled=True, quiet=True).parse(b'')
except Exception:
    pass  # empty input is fine — tessdata download is the goal
"@
    Write-Host "   eng.traineddata ready." -ForegroundColor Green
} catch {
    Write-Host "   Could not pre-download tessdata (network issue?). It will download on first use." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Setup complete. OCR is enabled by default." -ForegroundColor Green
Write-Host "To evaluate documents:"
Write-Host "  python app.py              # browser UI at http://localhost:8080"
Write-Host "  python evaluate.py         # CLI batch mode (all files in current folder)"
Write-Host "  python evaluate.py --no-ocr  # skip OCR for speed on native-text PDFs"
