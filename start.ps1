# Start the Call Reviewer application (backend + frontend)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "Starting backend (FastAPI on http://localhost:8000)..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root\backend'; py -m uvicorn main:app --reload"

Write-Host "Starting frontend (Vite on http://localhost:5173)..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root\frontend'; npm run dev"

Write-Host "Both servers are starting. Open http://localhost:5173 in your browser."
