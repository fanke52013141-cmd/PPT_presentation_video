# Register bundled open-source CJK design fonts for the CURRENT USER only.
# No administrator rights required (writes HKCU + %LOCALAPPDATA% only).
#
# WHY THIS IS REQUIRED
# --------------------
# Remotion renders subtitles by CSS font NAME only (see subtitleFontFamily in
# scripts/remotion/src/Video.tsx).  There is no @font-face / FontFace /
# staticFile font-loading path anywhere in the renderer, so a font must exist in
# the Windows font table to be used.  Without it the render silently falls back
# to Microsoft YaHei, which looks like "I picked a design font but the video
# never changed".
#
# WHERE THE FONTS LIVE
# --------------------
# Tried in order: <root>\static\fonts\portable, <root>\fonts, <root>\static\fonts.
# Historically this script only looked at <root>\fonts while packaging placed the
# fonts in static\fonts\portable, so nothing was ever registered.
#
# This file is intentionally ASCII-only: Windows PowerShell 5.1 decodes .ps1
# files without a BOM using the system ANSI code page, which corrupts non-ASCII
# string literals and can break parsing outright.
#
# IDEMPOTENT: already-registered fonts are skipped, so it is safe to call on
# every launch.  Font failures never block startup; subtitles fall back.

[CmdletBinding()]
param(
    # Report what would happen without touching the font table or registry.
    [switch]$DryRun,
    # Print only the one-line summary.
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'

function Write-Info {
    param([string]$Message, [string]$Color = 'Gray')
    if (-not $Quiet) { Write-Host $Message -ForegroundColor $Color }
}

$root = Split-Path -Parent $PSScriptRoot
$candidateDirs = @(
    (Join-Path $root 'static\fonts\portable'),
    (Join-Path $root 'fonts'),
    (Join-Path $root 'static\fonts')
)

$fontsDir = $null
foreach ($candidate in $candidateDirs) {
    if ((Test-Path -LiteralPath $candidate) -and (Get-ChildItem -LiteralPath $candidate -Filter *.ttf -File -ErrorAction SilentlyContinue)) {
        $fontsDir = $candidate
        break
    }
}

if (-not $fontsDir) {
    Write-Info "[fonts] no .ttf found to register; tried: $($candidateDirs -join '; ')" 'Yellow'
    exit 0
}

$userFontDir = Join-Path $env:LOCALAPPDATA 'Microsoft\Windows\Fonts'
$regPath = 'HKCU:\Software\Microsoft\Windows NT\CurrentVersion\Fonts'

if (-not $DryRun) {
    New-Item -ItemType Directory -Force -Path $userFontDir | Out-Null
    if (-not (Test-Path $regPath)) { New-Item -Path $regPath -Force | Out-Null }
}

# Read the real family name out of the font file so the registry entry is
# human-readable instead of a content-hash file name.
$drawingReady = $false
try {
    Add-Type -AssemblyName System.Drawing -ErrorAction Stop
    $drawingReady = $true
} catch {
    $drawingReady = $false
}

function Get-FontFamilyName {
    param([string]$Path, [string]$Fallback)
    if (-not $drawingReady) { return $Fallback }
    $collection = $null
    try {
        $collection = New-Object System.Drawing.Text.PrivateFontCollection
        $collection.AddFontFile($Path)
        if ($collection.Families.Count -gt 0) {
            $name = $collection.Families[0].Name
            if ($name) { return $name }
        }
    } catch {
        # Corrupt file or GDI+ limitation: fall back to the file name and keep
        # registering the remaining fonts.
    } finally {
        if ($collection) { $collection.Dispose() }
    }
    return $Fallback
}

Write-Info "[fonts] source directory: $fontsDir"

$registered = 0
$skipped = 0
$failed = 0
$families = New-Object System.Collections.Generic.List[string]

foreach ($file in (Get-ChildItem -LiteralPath $fontsDir -Filter *.ttf -File | Sort-Object Name)) {
    $family = Get-FontFamilyName -Path $file.FullName -Fallback $file.BaseName
    $title = "$family (TrueType)"
    $destination = Join-Path $userFontDir $file.Name

    if ($DryRun) {
        Write-Info "  [dry-run] $($file.Name) -> $family"
        $registered++
        continue
    }

    try {
        $existing = Get-ItemProperty -Path $regPath -Name $title -ErrorAction SilentlyContinue
        if ($existing -and (Test-Path -LiteralPath $existing.$title)) {
            $skipped++
            continue
        }
        if (-not (Test-Path -LiteralPath $destination)) {
            Copy-Item -LiteralPath $file.FullName -Destination $destination -Force
        }
        New-ItemProperty -Path $regPath -Name $title -Value $destination -PropertyType String -Force | Out-Null
        $registered++
        $families.Add($family)
    } catch {
        $failed++
        Write-Info "  [warn] failed to register $($file.Name): $($_.Exception.Message)" 'Yellow'
    }
}

if ($DryRun) {
    Write-Info "[fonts] dry-run complete: would register $registered font file(s)."
    exit 0
}

if (-not $Quiet -and $families.Count -gt 0) {
    Write-Info "  newly registered: $((($families | Sort-Object -Unique) -join ', '))" 'DarkGreen'
}
Write-Info "[fonts] done: registered=$registered skipped=$skipped failed=$failed (dir $fontsDir)" $(if ($failed -gt 0) { 'Yellow' } else { 'DarkGreen' })

# Font registration must never block startup.
exit 0
