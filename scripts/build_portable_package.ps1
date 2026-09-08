[CmdletBinding()]
param(
    [string]$DestinationRoot = (Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) "PPT视频工作台_便携版_$(Get-Date -Format 'yyyyMMdd-HHmmss')")
)

$ErrorActionPreference = 'Stop'

$sourceRoot = (Resolve-Path (Split-Path -Parent $PSScriptRoot)).Path
$destinationRoot = [System.IO.Path]::GetFullPath($DestinationRoot)

if ($destinationRoot.TrimEnd('\\') -eq $sourceRoot.TrimEnd('\\') -or $destinationRoot.StartsWith($sourceRoot.TrimEnd('\\') + '\\', [System.StringComparison]::OrdinalIgnoreCase)) {
    throw '便携包目录不能是源项目目录或其子目录。'
}
if (Test-Path -LiteralPath $destinationRoot) {
    throw "目标目录已存在：$destinationRoot"
}

$excludedDirectories = @(
    '.git', '.venv', '.pytest_cache', '__pycache__', '.agents', '.codex', '.zcode',
    '.github', 'bad_cases', 'checks', 'docs', 'logs'
)

Write-Host "[1/4] 复制应用与内置运行环境到：$destinationRoot"
New-Item -ItemType Directory -Path $destinationRoot | Out-Null
& robocopy $sourceRoot $destinationRoot /E /COPY:DAT /DCOPY:DAT /R:2 /W:1 /NFL /NDL /NJH /NJS /NP /XD $excludedDirectories /XF '*.pyc' 'server_boot.log' '_sandbox_test.txt' | Out-Host
if ($LASTEXITCODE -gt 7) {
    throw "文件复制失败，robocopy 退出码：$LASTEXITCODE"
}

Write-Host '[2/4] 生成一致的项目数据库快照'
$sourceDatabase = Join-Path $sourceRoot 'data\projects.db'
$targetDatabase = Join-Path $destinationRoot 'data\projects.db'
$portablePython = Join-Path $sourceRoot 'runtime\python\python.exe'
if (-not (Test-Path -LiteralPath $portablePython)) {
    throw "未找到包内 Python：$portablePython"
}
if (Test-Path -LiteralPath $sourceDatabase) {
    $backupScript = @'
import sqlite3
import sys

source, target = sys.argv[1], sys.argv[2]
with sqlite3.connect(source) as source_connection, sqlite3.connect(target) as target_connection:
    source_connection.backup(target_connection)
    target_connection.execute("UPDATE projects SET mask_enabled = 0, presentation_mode = 'full_frame'")
    target_connection.commit()
'@
    & $portablePython -c $backupScript $sourceDatabase $targetDatabase
    if ($LASTEXITCODE -ne 0) {
        throw 'SQLite 数据库快照失败。'
    }
    Remove-Item -LiteralPath "$targetDatabase-wal", "$targetDatabase-shm" -Force -ErrorAction SilentlyContinue
}

Write-Host '[2/4] 移除数字人运行素材并固定为静态切页模式'
Remove-Item -LiteralPath (Join-Path $destinationRoot 'data\digital_human') -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -LiteralPath (Join-Path $destinationRoot 'runs') -Recurse -Force -Directory -Filter 'digital_human' -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction Stop
Get-ChildItem -LiteralPath (Join-Path $destinationRoot 'runs') -Recurse -Force -File -Filter 'digital_human.json' -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction Stop

Write-Host '[3/4] 验证便携包内的 Python、Node、FFmpeg 与 Remotion 依赖'
$requiredPaths = @(
    '启动.bat',
    'runtime\python\python.exe',
    'runtime\node\node.exe',
    'tools\ffmpeg\bin\ffmpeg.exe',
    'tools\ffmpeg\bin\ffprobe.exe',
    'scripts\remotion\node_modules\remotion\package.json',
    'data\projects.db',
    'data\credentials.json',
    'data\model_connections.json',
    'data\creation_configs.json'
)
foreach ($relativePath in $requiredPaths) {
    $path = Join-Path $destinationRoot $relativePath
    if (-not (Test-Path -LiteralPath $path)) {
        throw "便携包缺少必要文件：$relativePath"
    }
}
& (Join-Path $destinationRoot 'runtime\python\python.exe') -c 'import fastapi, uvicorn, sqlalchemy; print("Python runtime OK")'
if ($LASTEXITCODE -ne 0) { throw '便携 Python 运行环境验证失败。' }
& (Join-Path $destinationRoot 'runtime\node\node.exe') --version
if ($LASTEXITCODE -ne 0) { throw '便携 Node 运行环境验证失败。' }
& (Join-Path $destinationRoot 'tools\ffmpeg\bin\ffmpeg.exe') -version | Select-Object -First 1
if ($LASTEXITCODE -ne 0) { throw '便携 FFmpeg 验证失败。' }

Write-Host '[4/4] 写入便携包使用说明'
$readmePath = Join-Path $destinationRoot '便携版使用说明.txt'
$readme = @'
PPT 视频工作台（便携版）

使用方法
1. 将整个文件夹复制到另一台 Windows 电脑（建议 Windows 10/11 64 位）。
2. 双击“启动.bat”。首次启动会为当前 Windows 用户注册包内字幕字体；无需管理员权限。
3. 浏览器会自动打开本地工作台。保持启动窗口开启；关闭窗口即停止服务。

本便携包已包含
- 内置 Python、Node.js、FFmpeg 和 Remotion 依赖，不需要另装开发环境。
- 当前项目、创作配置、模型连接、图片风格、模板和模型凭据，因此无需重新做账号、创作或模型设置。
- 已固定为整页静态切换：不执行 Mask/逐元素揭示动画，也不包含数字人运行素材。

安全提醒
- 为实现免设置，本包包含 API Key 等访问凭据。仅复制、保存或传输到你完全信任的设备；不要发送给他人、上传网盘公开链接或提交到 Git。
- 所有数据在此文件夹内的 data、runs、outputs 目录保存。备份时请复制整个文件夹。

兼容性
- 仅适用于 Windows 10/11 64 位。
- 初次运行前请确认 Windows 安全软件没有隔离 runtime、tools 或启动脚本。
'@
[System.IO.File]::WriteAllText($readmePath, $readme, [System.Text.UTF8Encoding]::new($false))

$size = (Get-ChildItem -LiteralPath $destinationRoot -Recurse -File | Measure-Object -Property Length -Sum).Sum
Write-Host ''
Write-Host '便携包创建完成：' -ForegroundColor Green
Write-Host $destinationRoot -ForegroundColor Green
Write-Host ("总大小：{0:N2} GB" -f ($size / 1GB))
