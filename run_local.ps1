Write-Host "===================================================" -ForegroundColor Cyan
Write-Host "  PPT Visualization Studio - Local Web Service" -ForegroundColor Cyan
Write-Host "  Hand-drawn Sketch Style" -ForegroundColor Cyan
Write-Host "===================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "[1/3] Checking Python dependencies..." -ForegroundColor Green
py -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to install Python dependencies. Please ensure Python is installed and added to PATH."
    Read-Host "Press Enter to exit..."
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "[2/3] Starting backend FastAPI server..." -ForegroundColor Green
Start-Process "http://localhost:8000"
py server.py
