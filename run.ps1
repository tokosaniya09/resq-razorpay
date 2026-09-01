# ResQ-Pay one-command launcher (Windows PowerShell).
# Opens backend + frontend in separate windows, then streams a demo with an outage.
# Usage:  .\run.ps1
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

Write-Host "Starting ResQ-Pay..." -ForegroundColor Cyan

# Backend (uses the venv if present)
$backendCmd = "cd '$root\backend'; if (Test-Path .venv\Scripts\Activate.ps1) { .\.venv\Scripts\Activate.ps1 }; uvicorn app.main:app --reload --port 8000"
Start-Process powershell -ArgumentList "-NoExit","-Command",$backendCmd

# Frontend
$frontendCmd = "cd '$root\frontend'; npm run dev"
Start-Process powershell -ArgumentList "-NoExit","-Command",$frontendCmd

Write-Host "Waiting 6s for the backend to come up..." -ForegroundColor DarkGray
Start-Sleep -Seconds 6

# Demo stream with an outage (in this window)
Write-Host "Streaming demo events (with an outage on UPI-SBI)..." -ForegroundColor Green
cd "$root\backend"
if (Test-Path .venv\Scripts\Activate.ps1) { .\.venv\Scripts\Activate.ps1 }
python scripts/generate_events.py --count 140 --rate 5 --outage --outage-at 30 --outage-len 20 --seed 7

Write-Host "`nOpen the dashboard at http://localhost:5173" -ForegroundColor Cyan
