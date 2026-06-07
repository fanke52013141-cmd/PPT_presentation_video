param(
  [string]$RunId = "demo",
  [string]$Composition = "ArticleVideo",
  [string]$OutFile = "runs/demo/video/final.mp4",
  [string]$PropsFile = "runs/demo/remotion_props.json"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RemotionDir = Join-Path $ScriptDir "remotion"

Push-Location $RemotionDir
try {
  if (-not (Test-Path "node_modules")) {
    if (Test-Path "package-lock.json") {
      npm ci
    }
    else {
      npm install
    }
    if ($LASTEXITCODE -ne 0) {
      throw "npm dependency installation failed with exit code $LASTEXITCODE"
    }
  }
  $OutPath = Join-Path "..\.." $OutFile
  $PropsPath = Join-Path "..\.." $PropsFile
  $OutDir = Split-Path -Parent $OutPath
  if ($OutDir -and -not (Test-Path $OutDir)) {
    New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
  }
  npx remotion render src/index.tsx $Composition $OutPath --props=$PropsPath
  if ($LASTEXITCODE -ne 0) {
    throw "Remotion render failed with exit code $LASTEXITCODE"
  }
}
finally {
  Pop-Location
}

