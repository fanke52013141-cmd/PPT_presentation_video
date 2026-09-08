# 可选字体自动注册（仅当前用户，无需管理员权限）
# 用途：把包内 fonts/ 目录的开源字体注册到当前用户字体表，
#       让 Remotion 渲染字幕时能命中设计字体；注册失败不影响使用
#       （字幕会回退到微软雅黑，与未装字体的原机行为一致）。
# 由 启动.bat 在每次启动时调用，已注册则直接跳过。
[功能: 便携包字体自注册]

$ErrorActionPreference = 'SilentlyContinue'
$root = Split-Path -Parent $PSScriptRoot
$fontsDir = Join-Path $root 'fonts'
if (-not (Test-Path $fontsDir)) { exit 0 }

$userFontDir = Join-Path $env:LOCALAPPDATA 'Microsoft\Windows\Fonts'
New-Item -ItemType Directory -Force -Path $userFontDir | Out-Null
$regPath = 'HKCU:\Software\Microsoft\Windows NT\CurrentVersion\Fonts'

Get-ChildItem $fontsDir -Filter *.ttf | ForEach-Object {
    $name = $_.Name
    $dest = Join-Path $userFontDir $name
    if (-not (Test-Path $dest)) {
        Copy-Item $_.FullName $dest -Force
    }
    $title = $_.BaseName + ' (TrueType)'
    if (-not (Get-ItemProperty -Path $regPath -Name $title -ErrorAction SilentlyContinue)) {
        New-ItemProperty -Path $regPath -Name $title -Value $dest -PropertyType String -Force | Out-Null
    }
}
exit 0
