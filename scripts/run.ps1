$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $ProjectRoot "src"
& (Join-Path $ProjectRoot ".venv\Scripts\python.exe") -m wealth_monitor
