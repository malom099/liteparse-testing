# setup-env.ps1 — creates a virtual environment and installs dependencies

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition

Write-Host "==> Creating virtual environment..." -ForegroundColor Cyan
python -m venv "$ScriptDir\.venv"

Write-Host "==> Activating virtual environment..." -ForegroundColor Cyan
& "$ScriptDir\.venv\Scripts\Activate.ps1"

Write-Host "==> Installing dependencies..." -ForegroundColor Cyan
pip install --upgrade pip
pip install -r "$ScriptDir\requirements.txt"

Write-Host ""
Write-Host "Setup complete. To evaluate documents:" -ForegroundColor Green
Write-Host "  python evaluate.py <file_or_folder> [--ocr] [--output-dir results]"
