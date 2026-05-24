# Start the Call Reviewer application (backend + frontend + Redis + Celery worker)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "Starting Celery worker..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root\backend'; py -m celery -A celery_app worker --loglevel=info --pool=solo"

Write-Host "Starting backend (FastAPI on http://localhost:8000)..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root\backend'; py -m uvicorn main:app --reload"

Write-Host "Starting frontend (Vite on http://localhost:5173)..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root\frontend'; npm run dev"

Write-Host "All services are starting. Open http://localhost:5173 in your browser."
