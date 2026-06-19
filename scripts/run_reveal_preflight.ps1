param(
  [Parameter(Mandatory=$true)]
  [string]$RunId,

  [string]$RepoRoot = ".",
  [switch]$Overwrite,
  [switch]$SkipContractGeneration,
  [switch]$SkipPromptGeneration,
  [switch]$SkipNarrationGeneration,
  [switch]$SkipPreview,
  [switch]$RequireReviewedManifest
)

$ErrorActionPreference = "Stop"

function Run-Step {
  param(
    [Parameter(Mandatory=$true)][string]$Name,
    [Parameter(Mandatory=$true)][scriptblock]$Command
  )
  Write-Host "`n==> $Name" -ForegroundColor Cyan
  & $Command
  if ($LASTEXITCODE -ne 0) {
    throw "Step failed: $Name"
  }
}

$RunDir = Join-Path $RepoRoot "runs/$RunId"
$Contract = Join-Path $RunDir "planning/visual_contract.json"
$Manifest = Join-Path $RunDir "reveal_manifest.json"
$PreviewDir = Join-Path $RunDir "review"

if (-not (Test-Path $RunDir)) {
  throw "Run directory does not exist: $RunDir"
}

$overwriteFlag = @()
if ($Overwrite) {
  $overwriteFlag = @("--overwrite")
}

if (-not $SkipContractGeneration) {
  Run-Step "Generate visual contract" {
    python (Join-Path $RepoRoot "scripts/write_visual_contract.py") --run-dir $RunDir @overwriteFlag
  }
}

Run-Step "Validate visual contract" {
  python (Join-Path $RepoRoot "scripts/validate_visual_contract.py") --contract $Contract
}

if (-not $SkipPromptGeneration) {
  Run-Step "Write visual prompts" {
    python (Join-Path $RepoRoot "scripts/write_visual_prompts.py") --run-dir $RunDir @overwriteFlag
  }
}

if (-not (Test-Path $Manifest)) {
  Run-Step "Create reveal manifest template" {
    python (Join-Path $RepoRoot "scripts/write_reveal_manifest_template.py") --run-dir $RunDir @overwriteFlag
  }
  Write-Host "`nReveal manifest template created: $Manifest" -ForegroundColor Yellow
  Write-Host "Paint optional Masks in the web editor, then re-run this script." -ForegroundColor Yellow
  exit 0
}

$anyVisualDraft = Get-ChildItem -Path (Join-Path $RunDir "slides") -Filter "visual_draft.png" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
if (($null -ne $anyVisualDraft) -and (-not $SkipPreview)) {
  Run-Step "Draw reveal manifest preview" {
    python (Join-Path $RepoRoot "scripts/draw_reveal_manifest_preview.py") --manifest $Manifest --repo-root $RepoRoot --out-dir $PreviewDir
  }
}

$manifestReviewFlag = @()
if ($RequireReviewedManifest) {
  $manifestReviewFlag = @("--require-reviewed")
}

Run-Step "Validate reveal manifest" {
  python (Join-Path $RepoRoot "scripts/validate_reveal_manifest.py") --manifest $Manifest --contract $Contract @manifestReviewFlag
}

if ($null -ne $anyVisualDraft) {
  Run-Step "Build reveal scene" {
    python (Join-Path $RepoRoot "scripts/build_reveal_scene.py") --manifest $Manifest --repo-root $RepoRoot
  }

  Run-Step "Validate reveal scene" {
    python (Join-Path $RepoRoot "scripts/validate_reveal_scene.py") --run-dir $RunDir --repo-root $RepoRoot
  }
} else {
  Write-Host "`nNo visual_draft.png found yet. Skipping reveal scene build." -ForegroundColor Yellow
}

if (-not $SkipNarrationGeneration) {
  Run-Step "Write narration from visual contract" {
    python (Join-Path $RepoRoot "scripts/write_narration_from_visual_contract.py") --run-dir $RunDir @overwriteFlag
  }
}

Run-Step "Validate narration grounding" {
  python (Join-Path $RepoRoot "scripts/validate_narration_grounding.py") --run-dir $RunDir
}

Write-Host "`nReveal preflight completed." -ForegroundColor Green
if (Test-Path $PreviewDir) {
  Write-Host "Preview images: $PreviewDir" -ForegroundColor Green
}
