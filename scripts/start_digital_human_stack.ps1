param(
    [string]$AssetsRoot = $(
        if ($env:PPT_DIGITAL_HUMAN_ASSETS_ROOT) {
            $env:PPT_DIGITAL_HUMAN_ASSETS_ROOT
        } else {
            'D:\PPT_Studio_Assets\InfiniteTalk_TTS'
        }
    )
)

$ErrorActionPreference = 'Stop'
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$assetsRoot = [System.IO.Path]::GetFullPath($AssetsRoot)
$comfyRoot = Join-Path $assetsRoot 'InfiniteTalk_Runtime\ComfyUI'
$comfyPython = Join-Path $assetsRoot 'InfiniteTalk_Runtime\venv\Scripts\python.exe'
$servicePython = Join-Path $repoRoot '.venv\Scripts\python.exe'
$workflow = Join-Path $assetsRoot 'InfiniteTalk\workflow\infinitetalk-数字人_api_windows-compatible.json'
$logRoot = Join-Path $assetsRoot 'logs'

foreach ($requiredPath in @($comfyRoot, $comfyPython, $servicePython, $workflow)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Digital-human startup dependency is missing: $requiredPath"
    }
}
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null

function Test-LocalPort([int]$Port) {
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Test-ComfyUiReady {
    try {
        return (Invoke-RestMethod -Uri 'http://127.0.0.1:8188/system_stats' -TimeoutSec 3).system -ne $null
    } catch {
        return $false
    }
}

function Test-DigitalHumanReady {
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:9001/api/digital-human/health' -TimeoutSec 3
        return $health.success -and $health.model_ready -and $health.inference_backend -eq 'comfyui'
    } catch {
        return $false
    }
}

if (-not (Test-LocalPort 8188)) {
    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    Start-Process -FilePath $comfyPython `
        -ArgumentList @('main.py', '--listen', '127.0.0.1', '--port', '8188', '--disable-auto-launch') `
        -WorkingDirectory $comfyRoot `
        -RedirectStandardOutput (Join-Path $logRoot 'comfyui_stdout.log') `
        -RedirectStandardError (Join-Path $logRoot 'comfyui_stderr.log') `
        -WindowStyle Hidden
}

if (-not (Test-LocalPort 9001)) {
    $env:PPT_DIGITAL_HUMAN_BACKEND = 'comfyui'
    $env:PPT_DIGITAL_HUMAN_COMFYUI_WORKFLOW = $workflow
    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    Start-Process -FilePath $servicePython `
        -ArgumentList 'digital_human_service.py' `
        -WorkingDirectory $repoRoot `
        -RedirectStandardOutput (Join-Path $logRoot 'digital_human_stdout.log') `
        -RedirectStandardError (Join-Path $logRoot 'digital_human_stderr.log') `
        -WindowStyle Hidden
}

$deadline = [DateTime]::UtcNow.AddSeconds(60)
do {
    if ((Test-ComfyUiReady) -and (Test-DigitalHumanReady)) {
        Write-Output 'Digital-human services are ready: http://127.0.0.1:8188 + http://127.0.0.1:9001'
        exit 0
    }
    Start-Sleep -Milliseconds 500
} while ([DateTime]::UtcNow -lt $deadline)

throw 'Digital-human startup timed out. Check the assets/logs directory.'
