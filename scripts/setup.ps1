# Windows setup: virtual environment, dependencies, model, demo accounts (development only).
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
if (-not (Test-Path .venv)) { py -3 -m venv .venv }
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path ml\models\active.json)) { .\.venv\Scripts\python.exe ml\train.py }   # ~4 min: dataset + training + evaluation
.\.venv\Scripts\python.exe -m gateway.manage seed-demo
Write-Host "`nStart:  .\.venv\Scripts\python.exe -m gateway.server   then open http://127.0.0.1:8000"
Write-Host "Demo credentials (development only): data\demo_credentials.txt"
