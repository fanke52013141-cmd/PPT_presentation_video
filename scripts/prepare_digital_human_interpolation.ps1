param(
    [string]$AssetsRoot = $(
        if ($env:PPT_DIGITAL_HUMAN_ASSETS_ROOT) { $env:PPT_DIGITAL_HUMAN_ASSETS_ROOT } else { 'D:\PPT_Studio_Assets\InfiniteTalk_TTS' }
    )
)

$ErrorActionPreference = 'Stop'
$comfyRoot = Join-Path ([System.IO.Path]::GetFullPath($AssetsRoot)) 'InfiniteTalk_Runtime\ComfyUI'
$modelDir = Join-Path $comfyRoot 'models\frame_interpolation'
$modelPath = Join-Path $modelDir 'rife426.pth'
$modelUrl = 'https://github.com/Fannovel16/ComfyUI-Frame-Interpolation/releases/download/models/rife426.pth'

if (-not (Test-Path -LiteralPath $comfyRoot)) { throw "ComfyUI runtime not found: $comfyRoot" }
New-Item -ItemType Directory -Force -Path $modelDir | Out-Null
if (-not (Test-Path -LiteralPath $modelPath)) {
    Invoke-WebRequest -Uri $modelUrl -OutFile $modelPath
}
if ((Get-Item -LiteralPath $modelPath).Length -lt 1MB) {
    Remove-Item -LiteralPath $modelPath -Force -ErrorAction SilentlyContinue
    throw 'RIFE model download is incomplete.'
}
Write-Output "RIFE interpolation model is ready: $modelPath"
