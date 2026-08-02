<#
.SYNOPSIS
    Activates .venv and runs the LiteParse Evaluator web app.
.EXAMPLE
    .\run.ps1
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Push-Location $PSScriptRoot
try {
    if (-not (Test-Path '.venv\Scripts\python.exe')) {
        Write-Host 'ERROR: .venv not found. Run setup-env.ps1 first.' -ForegroundColor Red
        exit 1
    }

    $uiPort = if ($env:LITEPARSE_EVAL_PORT) { $env:LITEPARSE_EVAL_PORT } else { '8080' }
    Write-Host "Launching LiteParse Evaluator at http://localhost:$uiPort ..." -ForegroundColor Cyan
    & .\.venv\Scripts\python.exe app.py
} finally {
    Pop-Location
}
