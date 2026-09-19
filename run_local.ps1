Write-Host "===================================================" -ForegroundColor Cyan
Write-Host "  PPT Visualization Studio - Local Web Service" -ForegroundColor Cyan
Write-Host "  Soft Pastel Studio" -ForegroundColor Cyan
Write-Host "===================================================" -ForegroundColor Cyan
Write-Host ""

function Add-FfmpegPathIfComplete {
    param([string]$Dir)
    if (-not $Dir) { return $false }
    $ffmpeg = Join-Path $Dir "ffmpeg.exe"
    $ffprobe = Join-Path $Dir "ffprobe.exe"
    if ((Test-Path $ffmpeg) -and (Test-Path $ffprobe)) {
        if ($env:PATH -notlike "*$Dir*") {
            $env:PATH = "$Dir;$env:PATH"
        }
        $env:PPT_STUDIO_FFMPEG_DIR = $Dir
        Write-Host "Using ffmpeg tools: $Dir" -ForegroundColor DarkGreen
        return $true
    }
    return $false
}

Write-Host "[1/4] Checking ffmpeg/ffprobe..." -ForegroundColor Green
$ffmpegReady = $false
$ffmpegCandidates = @(
    $env:PPT_STUDIO_FFMPEG_DIR,
    (Join-Path $PSScriptRoot "tools\ffmpeg\bin"),
    (Join-Path $PSScriptRoot "runtime\ffmpeg\bin"),
    (Join-Path $PSScriptRoot "..\work\runtime\ffmpeg\bin"),
    (Join-Path $PSScriptRoot "..\work\runtime\ffmpeg"),
    (Join-Path $env:APPDATA "TRAE SOLO CN\ModularData\ai-agent\vm\tools\app\ffmpeg")
)
foreach ($candidate in $ffmpegCandidates) {
    if (Add-FfmpegPathIfComplete $candidate) {
        $ffmpegReady = $true
        break
    }
}
if (-not $ffmpegReady -and (Get-Command ffmpeg -ErrorAction SilentlyContinue) -and (Get-Command ffprobe -ErrorAction SilentlyContinue)) {
    $ffmpegReady = $true
}
if (-not $ffmpegReady) {
    Write-Warning "ffmpeg/ffprobe not found. Video render color validation will fail unless they are installed or PPT_STUDIO_FFMPEG_DIR is set."
}

# Remotion resolves subtitle fonts by CSS family NAME only, so the bundled design
# fonts must be present in the Windows font table or rendering silently falls
# back to Microsoft YaHei.  Idempotent; failures never block startup.
$fontInstaller = Join-Path $PSScriptRoot "scripts\portable_install_fonts.ps1"
if (Test-Path $fontInstaller) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File $fontInstaller -Quiet
}

Write-Host ""
Write-Host "[2/4] Checking Python dependencies..." -ForegroundColor Green
$pythonExe = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    py -m venv (Join-Path $PSScriptRoot ".venv")
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to create Python virtual environment. Please ensure Python is installed and added to PATH."
        Read-Host "Press Enter to exit..."
        exit $LASTEXITCODE
    }
}
& $pythonExe -m pip install -r (Join-Path $PSScriptRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to install Python dependencies. Please ensure Python is installed and added to PATH."
    Read-Host "Press Enter to exit..."
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "[3/4] Starting backend FastAPI server..." -ForegroundColor Green
# Keep ComfyUI outside the project.  The digital-human service receives only
# the external workflow path and talks to ComfyUI over localhost HTTP.
$assetsRoot = if ($env:PPT_STUDIO_ASSETS_DIR) { $env:PPT_STUDIO_ASSETS_DIR } else { "D:\PPT_Studio_Assets" }
$infiniteTalkWorkflow = Join-Path $assetsRoot "InfiniteTalk_TTS\InfiniteTalk\workflow\infinitetalk-数字人_api_windows-compatible.json"
if (Test-Path $infiniteTalkWorkflow) {
    $env:PPT_DIGITAL_HUMAN_BACKEND = "comfyui"
    $env:PPT_DIGITAL_HUMAN_MOCK = "0"
    $env:PPT_DIGITAL_HUMAN_COMFYUI_WORKFLOW = $infiniteTalkWorkflow
    if (-not (Get-NetTCPConnection -ComputerName 127.0.0.1 -Port 9001 -State Listen -ErrorAction SilentlyContinue)) {
        Start-Process -FilePath $pythonExe -ArgumentList @((Join-Path $PSScriptRoot "digital_human_service.py")) -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
        Write-Host "Using external InfiniteTalk workflow: $infiniteTalkWorkflow" -ForegroundColor DarkGreen
    }
} else {
    Write-Warning "InfiniteTalk workflow not found at $infiniteTalkWorkflow; digital-human service will use its fallback mode."
}
Start-Process "http://localhost:8000"
$env:PYTHONPATH = "$PSScriptRoot;$env:PYTHONPATH"
& $pythonExe (Join-Path $PSScriptRoot "start_server.py")
