# Prepare the portable runtime materials that scripts/build_portable_package.ps1
# requires: an embedded Python (with this project's dependencies), an embedded
# Node.js, and ffmpeg/ffprobe under tools\ffmpeg\bin.
#
# WHY THIS EXISTS
# ---------------
# build_portable_package.ps1 validates runtime\python\python.exe,
# runtime\node\node.exe and tools\ffmpeg\bin\ffmpeg.exe. Those materials are not
# in the repository and there was no script to fetch them, so a rebuild meant
# hunting for files by hand (the last package had to be mined for them).
#
# ASCII-ONLY ON PURPOSE: Windows PowerShell 5.1 decodes .ps1 files without a BOM
# using the system ANSI code page (936 on this machine). Non-ASCII string
# literals get corrupted and can break parsing outright. Keep this file ASCII.
#
# NOT VERIFIED END-TO-END: the machine this was written on has no outbound
# network, so the downloads below were never executed. Verify each step's output
# before trusting a package built from it.
#
# USAGE
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\prepare_portable_runtime.ps1
#   ... -FfmpegFlavor essentials    # smaller ffmpeg; re-verify hw encoder detection
#   ... -Force                      # re-download even if the target already exists

[CmdletBinding()]
param(
    [string]$PythonVersion = '3.13.0',
    [string]$NodeVersion = '22.22.2',
    # 'full' is the build the previous package shipped (known good, ~141 MB per exe).
    # 'essentials' is much smaller but MUST be re-verified: remotion_runner probes
    # ffmpeg -encoders for h264_nvenc / h264_qsv / h264_amf.
    [ValidateSet('full', 'essentials')]
    [string]$FfmpegFlavor = 'full',
    [switch]$Force,
    # Print the planned downloads and target paths without touching the network
    # or the filesystem. Use this first to see exactly what will be fetched.
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$repoRoot = Split-Path -Parent $PSScriptRoot
$runtimeDir = Join-Path $repoRoot 'runtime'
$pythonDir = Join-Path $runtimeDir 'python'
$nodeDir = Join-Path $runtimeDir 'node'
$ffmpegDir = Join-Path $repoRoot 'tools\ffmpeg\bin'
$downloadDir = Join-Path $runtimeDir '_download'

$ffmpegZipName = if ($FfmpegFlavor -eq 'essentials') { 'ffmpeg-release-essentials.zip' } else { 'ffmpeg-release-full.zip' }

if ($DryRun) {
    Write-Host 'Planned downloads and targets (nothing is fetched):' -ForegroundColor Cyan
    [pscustomobject]@{
        Component = 'Python (embeddable)'
        Url       = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
        Target    = $pythonDir
    }, [pscustomobject]@{
        Component = 'get-pip.py'
        Url       = 'https://bootstrap.pypa.io/get-pip.py'
        Target    = $downloadDir
    }, [pscustomobject]@{
        Component = "Node v$NodeVersion"
        Url       = "https://nodejs.org/dist/v$NodeVersion/node-v$NodeVersion-win-x64.zip"
        Target    = $nodeDir
    }, [pscustomobject]@{
        Component = "ffmpeg ($FfmpegFlavor)"
        Url       = "https://www.gyan.dev/ffmpeg/builds/$ffmpegZipName"
        Target    = $ffmpegDir
    } | Format-Table -AutoSize | Out-Host
    Write-Host "Requirements to install into the embedded Python: $(Join-Path $repoRoot 'requirements.txt')"
    exit 0
}

New-Item -ItemType Directory -Force -Path $runtimeDir, $downloadDir, $ffmpegDir | Out-Null

function Get-RemoteFile {
    param([string]$Url, [string]$Destination)
    if ((Test-Path -LiteralPath $Destination) -and -not $Force) {
        Write-Host "[skip] already downloaded: $(Split-Path $Destination -Leaf)"
        return $Destination
    }
    if ($DryRun) {
        Write-Host "[plan] download $Url"
        Write-Host "       -> $Destination"
        return $Destination
    }
    Write-Host "[get ] $Url"
    Invoke-WebRequest -Uri $Url -OutFile $Destination -UseBasicParsing
    return $Destination
}

function Expand-ZipInto {
    param([string]$ZipPath, [string]$Destination)
    $staging = Join-Path $downloadDir ('unzip_' + [System.IO.Path]::GetFileNameWithoutExtension($ZipPath))
    Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
    Expand-Archive -LiteralPath $ZipPath -DestinationPath $staging -Force
    return $staging
}

# ---------------------------------------------------------------- embedded Python
# python.org ships the embeddable distribution as a zip; it has no pip and its
# ._pth file disables site-packages, both of which must be enabled so the
# project's requirements can be installed into it.
if (-not (Test-Path (Join-Path $pythonDir 'python.exe')) -or $Force) {
    $pythonZip = Get-RemoteFile `
        -Url "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip" `
        -Destination (Join-Path $downloadDir "python-$PythonVersion-embed-amd64.zip")
    $staging = Expand-ZipInto -ZipPath $pythonZip -Destination $pythonDir

    Remove-Item -LiteralPath $pythonDir -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $pythonDir | Out-Null
    Copy-Item -Path (Join-Path $staging '*') -Destination $pythonDir -Recurse -Force

    # Enable site-packages so pip-installed dependencies are importable.
    $pth = Get-ChildItem -LiteralPath $pythonDir -Filter 'python*._pth' | Select-Object -First 1
    if ($pth) {
        $content = Get-Content -LiteralPath $pth.FullName
        $content = $content -replace '^#\s*import site', 'import site'
        if (-not ($content -match '^import site')) { $content += 'import site' }
        Set-Content -LiteralPath $pth.FullName -Value $content -Encoding ASCII
        Write-Host "[ok  ] enabled site-packages in $($pth.Name)"
    }

    # Bootstrap pip, then install the project requirements.
    $getPip = Get-RemoteFile -Url 'https://bootstrap.pypa.io/get-pip.py' -Destination (Join-Path $downloadDir 'get-pip.py')
    & (Join-Path $pythonDir 'python.exe') $getPip --no-warn-script-location
    if ($LASTEXITCODE -ne 0) { throw 'failed to bootstrap pip into the embedded Python' }
    & (Join-Path $pythonDir 'python.exe') -m pip install --no-warn-script-location -r (Join-Path $repoRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'failed to install requirements.txt into the embedded Python' }
    Write-Host '[ok  ] embedded Python prepared'
} else {
    Write-Host '[skip] runtime\python already present'
}

# ------------------------------------------------------------------ embedded Node
if (-not (Test-Path (Join-Path $nodeDir 'node.exe')) -or $Force) {
    $nodeZip = Get-RemoteFile `
        -Url "https://nodejs.org/dist/v$NodeVersion/node-v$NodeVersion-win-x64.zip" `
        -Destination (Join-Path $downloadDir "node-v$NodeVersion-win-x64.zip")
    $staging = Expand-ZipInto -ZipPath $nodeZip -Destination $nodeDir

    Remove-Item -LiteralPath $nodeDir -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $nodeDir | Out-Null
    $inner = Get-ChildItem -LiteralPath $staging -Directory | Select-Object -First 1
    Copy-Item -Path (Join-Path $inner.FullName '*') -Destination $nodeDir -Recurse -Force
    Write-Host '[ok  ] embedded Node prepared'
} else {
    Write-Host '[skip] runtime\node already present'
}

# ------------------------------------------------------------------------ ffmpeg
# Only ffmpeg.exe and ffprobe.exe are needed. ffplay.exe is a standalone player
# that nothing in this application or its launchers references (video playback
# uses the browser's native <video> element), and the doc/ folder is HTML help.
if (-not (Test-Path (Join-Path $ffmpegDir 'ffmpeg.exe')) -or $Force) {
    $ffmpegZip = Get-RemoteFile `
        -Url "https://www.gyan.dev/ffmpeg/builds/$ffmpegZipName" `
        -Destination (Join-Path $downloadDir $ffmpegZipName)
    $staging = Expand-ZipInto -ZipPath $ffmpegZip -Destination $ffmpegDir

    $binDir = Get-ChildItem -LiteralPath $staging -Directory |
        ForEach-Object { Join-Path $_.FullName 'bin' } |
        Where-Object { Test-Path (Join-Path $_ 'ffmpeg.exe') } |
        Select-Object -First 1
    if (-not $binDir) { throw 'could not locate ffmpeg bin/ inside the downloaded archive' }

    Remove-Item -LiteralPath $ffmpegDir -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $ffmpegDir | Out-Null
    foreach ($exe in 'ffmpeg.exe', 'ffprobe.exe') {
        Copy-Item -LiteralPath (Join-Path $binDir $exe) -Destination $ffmpegDir -Force
    }
    Write-Host "[ok  ] ffmpeg ($FfmpegFlavor) prepared in $ffmpegDir"
} else {
    Write-Host '[skip] tools\ffmpeg\bin already present'
}

# -------------------------------------------------------------------- verification
Write-Host ''
Write-Host 'Verifying prepared materials...' -ForegroundColor Cyan
$checks = @(
    (Join-Path $pythonDir 'python.exe'),
    (Join-Path $nodeDir 'node.exe'),
    (Join-Path $ffmpegDir 'ffmpeg.exe'),
    (Join-Path $ffmpegDir 'ffprobe.exe')
)
foreach ($path in $checks) {
    if (-not (Test-Path -LiteralPath $path)) { throw "missing after preparation: $path" }
}

& (Join-Path $pythonDir 'python.exe') -c "import fastapi, uvicorn, sqlalchemy; print('python runtime OK')"
if ($LASTEXITCODE -ne 0) { throw 'embedded Python cannot import the application dependencies' }
& (Join-Path $nodeDir 'node.exe') --version
if ($LASTEXITCODE -ne 0) { throw 'embedded Node failed to run' }

# The app selects GPU vs CPU encoding from this list; a build without the
# hardware encoders silently degrades renders to CPU.
$encoders = & (Join-Path $ffmpegDir 'ffmpeg.exe') -hide_banner -encoders 2>&1 | Out-String
foreach ($encoder in 'h264_nvenc', 'h264_qsv', 'h264_amf') {
    $present = $encoders -match $encoder
    Write-Host ("  {0,-12} {1}" -f $encoder, $(if ($present) { 'advertised' } else { 'NOT advertised (renders fall back to CPU)' }))
}
if ($encoders -notmatch 'libx264') { throw 'ffmpeg does not advertise libx264; rendering will fail' }

Write-Host ''
Write-Host 'Runtime ready. Next: scripts\build_portable_package.ps1' -ForegroundColor Green
