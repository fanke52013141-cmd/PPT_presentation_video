param(
  [string]$RunId = "demo",
  [string]$Composition = "ArticleVideo",
  [string]$OutFile = "runs/demo/video/final.mp4"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RemotionDir = Join-Path $ScriptDir "remotion"

Push-Location $RemotionDir
try {
  if (-not (Test-Path "node_modules")) {
    npm install
  }
  npx remotion render src/index.tsx $Composition "../../$OutFile"
}
finally {
  Pop-Location
}

