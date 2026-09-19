# 构建便携版文件包：复制到另一台 Windows 电脑即可直接使用，无需二次设置。
#
# 内容策略（相对源仓库的差异）：
#   移除  1) 数字人部分：Step 9 面板/步骤条/入口脚本/工作流配置/运行素材
#         2) 本地 ComfyUI / IndexTTS（TTS 2.5）语音合成：设置页与模型表单 UI
#         3) 历史项目库：数据库转为空项目库（保留账号/设置/令牌/模板）
#   保留  Mask 逐元素揭示动画、云端 TTS、图片生成、一键流程、MP4/PPTX 导出、
#          全部账号/创作配置/模型连接/图片风格/字幕字体/音色参考。
#
# 换机免设置的关键：包内 data/.portable_root 记录构建时根路径，首次启动时
# scripts/portable_relocate.py 自动把包内数据里的旧绝对路径改写为新位置。
#
# 本文件含中文注释与中文字符串：必须以 UTF-8 BOM 保存，否则 Windows
# PowerShell 5.1 会按 ANSI(936) 解码导致乱码/解析失败。

[CmdletBinding()]
param(
    # 默认输出到桌面；也可用 -DestinationRoot 指定其他位置。
    [string]$DestinationRoot = (Join-Path ([Environment]::GetFolderPath('Desktop')) "PPT视频工作台_便携版_$(Get-Date -Format 'yyyyMMdd-HHmmss')"),
    # 只生成文件夹，不压 ZIP。
    [switch]$NoZip
)

$ErrorActionPreference = 'Stop'

$sourceRoot = (Resolve-Path (Split-Path -Parent $PSScriptRoot)).Path
$destinationRoot = [System.IO.Path]::GetFullPath($DestinationRoot)
$robocopy = Join-Path $env:SystemRoot 'System32\Robocopy.exe'
$tarExe = Join-Path $env:SystemRoot 'System32\tar.exe'
$portablePython = Join-Path $sourceRoot 'runtime\python\python.exe'

# ---------------------------------------------------------------------------
# 前置校验
# ---------------------------------------------------------------------------
if (-not (Test-Path -LiteralPath $portablePython)) {
    throw "缺少源运行环境 $portablePython，请先完成 runtime\python 准备。"
}
foreach ($required in @('runtime\node\node.exe', 'runtime\node\npx.cmd', 'tools\ffmpeg\bin\ffmpeg.exe', 'tools\ffmpeg\bin\ffprobe.exe', 'data\projects.db')) {
    if (-not (Test-Path -LiteralPath (Join-Path $sourceRoot $required))) {
        throw "源目录缺少必需文件：$required"
    }
}
if ($destinationRoot.TrimEnd('\') -eq $sourceRoot.TrimEnd('\') -or $destinationRoot.StartsWith($sourceRoot.TrimEnd('\') + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
    throw '便携包目录不能是源项目目录或其子目录。'
}
if (Test-Path -LiteralPath $destinationRoot) {
    throw "目标目录已存在：$destinationRoot"
}

# ---------------------------------------------------------------------------
# 排除清单
# ---------------------------------------------------------------------------
# 按目录名匹配（任意深度都安全）：仅限确定是开发缓存的名字。
$excludedDirectories = @(
    '.git', '.venv', '.pytest_cache', '__pycache__', '.agents', '.codex', '.zcode',
    '.github', '.workbuddy-ai'
)
# 按完整路径匹配：只排除仓库根部的目录。绝不能改成裸名——robocopy /XD 的
# 裸名在任意深度生效，会误伤深层同名目录：openai 包的 runs 子包、node_modules
# 里全部 dist 运行时代码（共 139 处）都曾被剥掉，导致启动即 ModuleNotFoundError。
$excludedPaths = @(
    # 开发/CI/文档（运行不需要）
    'bad_cases', 'checks', 'docs', 'logs', '.tmp',
    'scratch', 'work', 'dist', 'build',
    # 用户数据与历史产物：绝不能打进包（历史上曾把上一个包和全部用户项目复制进去）
    'outputs', 'runs',
    # 可再生缓存与数字人数据
    'scripts\remotion\node_modules\.cache',
    'scripts\remotion\public\runtime',
    'tools\ffmpeg\doc',
    'data\digital_human'
) | ForEach-Object { Join-Path $sourceRoot $_ } | Where-Object { Test-Path -LiteralPath $_ }
$excludedFiles = @(
    # 缓存与日志
    '*.pyc', '*.log',
    # 活动数据库（改用 SQLite backup API 单独生成快照）与限流计数库（新机从零开始）
    'projects.db', 'projects.db-wal', 'projects.db-shm',
    'agent_rate_limit.db', 'agent_rate_limit.db-wal', 'agent_rate_limit.db-shm',
    # 数字人：前端面板、工作流配置、启动/插帧脚本（后端模块保留，server.py 有导入）
    'digital_human_panel.js',
    'digital_human_lecturer_fast_workflow.json',
    'prepare_digital_human_interpolation.ps1',
    'start_digital_human_stack.ps1',
    '启动数字人服务.cmd',
    # 开发文档与开发启动器（便携包唯一入口是 启动.bat）
    'AGENTS.md', 'README.md', 'hand off.md', 'UI优化方案.md', '使用说明.txt',
    'launch.bat', 'run_local.bat', 'run_local.ps1', 'start_here.bat', 'requirements-dev.txt',
    # 多余二进制与杂项
    'ffplay.exe', 'file-manifest.json', '_sandbox_test.txt',
    # 环境变量与敏感导出（密钥已随 data\*.json 与数据库快照携带）
    '.env', '.env.*',
    'ppt-studio-global-settings-sensitive*.json', '*-sensitive-*.json'
)

# ---------------------------------------------------------------------------
# [1/8] 选择性复制
# ---------------------------------------------------------------------------
Write-Host "[1/8] 复制应用与内置运行环境到：$destinationRoot"
New-Item -ItemType Directory -Path $destinationRoot | Out-Null
$robocopyArgs = @(
    $sourceRoot, $destinationRoot, '/E', '/COPY:DAT', '/DCOPY:DAT', '/R:2', '/W:1',
    '/NFL', '/NDL', '/NJH', '/NJS', '/NP',
    '/XD'
) + $excludedDirectories + $excludedPaths + @('/XF') + $excludedFiles
& $robocopy @robocopyArgs | Out-Host
if ($LASTEXITCODE -gt 7) {
    throw "文件复制失败，robocopy 退出码：$LASTEXITCODE"
}
$global:LASTEXITCODE = 0

# ---------------------------------------------------------------------------
# [2/8] 清理数据备份目录与数字人残留
# ---------------------------------------------------------------------------
Write-Host '[2/8] 清理数据备份目录'
Get-ChildItem -LiteralPath (Join-Path $destinationRoot 'data') -Directory -Filter 'backup_*' -Force -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force
# 防御：确认数字人素材目录与面板脚本未进入包内
foreach ($leftover in @('data\digital_human', 'static\digital_human_panel.js')) {
    if (Test-Path -LiteralPath (Join-Path $destinationRoot $leftover)) {
        throw "数字人残留未清理干净：$leftover"
    }
}

# ---------------------------------------------------------------------------
# [3/8] 生成数据库快照并转为空项目库
# ---------------------------------------------------------------------------
Write-Host '[3/8] 生成数据库快照（空项目库：清空项目/任务，保留账号/设置/令牌）'
$targetDatabase = Join-Path $destinationRoot 'data\projects.db'
Remove-Item -LiteralPath "$targetDatabase-wal", "$targetDatabase-shm" -Force -ErrorAction SilentlyContinue
$snapshotScript = @'
import sqlite3
import sys

source, target = sys.argv[1], sys.argv[2]
src = sqlite3.connect(source)
try:
    dst = sqlite3.connect(target)
    try:
        # backup API：源库即使正被服务写入也能得到一致快照
        src.backup(dst)
        cur = dst.cursor()
        # 空项目库：清空项目与任务数据；保留 settings / accounts /
        # agent_tokens / schema_migrations（模板与提示词在 data\*.json 中）
        for table in ("projects", "courses", "chapters", "local_jobs",
                      "artifact_records", "agent_idempotency_records"):
            try:
                cur.execute("DELETE FROM " + table)
                print("[db] cleared %s (%d row(s))" % (table, cur.rowcount))
            except sqlite3.OperationalError as exc:
                print("[db] skip %s: %s" % (table, exc))
        # 保险：全局 TTS 若指向已移除的本地 ComfyUI，回落到 MiniMax 云端
        cur.execute("UPDATE settings SET value = 'minimax'"
                    " WHERE key = 'tts_provider' AND value = 'comfyui_tts'")
        dst.commit()
        dst.isolation_level = None
        cur.execute("VACUUM")
    finally:
        dst.close()
finally:
    src.close()
print("[db] snapshot ready")
'@
$tempDir = Join-Path ([System.IO.Path]::GetTempPath()) ("ppt_portable_build_" + [System.IO.Path]::GetRandomFileName())
New-Item -ItemType Directory -Path $tempDir | Out-Null
try {
    $snapshotPy = Join-Path $tempDir 'snapshot_db.py'
    [System.IO.File]::WriteAllText($snapshotPy, $snapshotScript, [System.Text.UTF8Encoding]::new($false))
    & $portablePython $snapshotPy (Join-Path $sourceRoot 'data\projects.db') $targetDatabase
    if ($LASTEXITCODE -ne 0) { throw '数据库快照生成失败。' }
    Remove-Item -LiteralPath "$targetDatabase-wal", "$targetDatabase-shm" -Force -ErrorAction SilentlyContinue

    # -----------------------------------------------------------------------
    # [4/8] index.html：移除 ComfyUI/IndexTTS 与数字人 UI
    # -----------------------------------------------------------------------
    Write-Host '[4/8] 移除 index.html 中的 ComfyUI 与数字人界面'
    $transformScript = @'
import re
import sys

path = sys.argv[1]
with open(path, "rb") as fh:
    html = fh.read().decode("utf-8")
orig_len = len(html)


def remove_block(anchor, tag):
    """按标签配对删除以 anchor 起始的整块元素（含所在整行）。"""
    global html
    i = html.find(anchor)
    if i < 0:
        raise SystemExit("[html] anchor not found: " + anchor)
    open_re = re.compile(r"<" + tag + r"(\s[^>]*)?>", re.IGNORECASE)
    close_re = re.compile(r"</" + tag + r"\s*>", re.IGNORECASE)
    pos, depth = i, 0
    end = -1
    while True:
        mo = open_re.search(html, pos)
        mc = close_re.search(html, pos)
        if mo and (mc is None or mo.start() < mc.start()):
            depth += 1
            pos = mo.end()
        elif mc:
            depth -= 1
            pos = mc.end()
            if depth == 0:
                end = pos
                break
        else:
            raise SystemExit("[html] unbalanced tag for anchor: " + anchor)
    start = html.rfind("\n", 0, i) + 1
    if html[start:i].strip():
        start = i  # 行首还有其他内容时只删元素本身
    m = re.match(r"[ \t]*\r?\n", html[end:])
    if m:
        end += m.end()
    html = html[:start] + html[end:]


# --- ComfyUI / IndexTTS（TTS 2.5）UI：两处下拉选项 + 两个配置区块 ---
# 选项有两种形态：独占整行（全局设置页）与内联在 <select> 里（模型表单），
# 计数用不带锚点的模式，删除分两步：先删整行的（连换行），再删内联的。
total = len(re.findall(r'<option value="comfyui_tts">[^<]*</option>', html))
if total != 2:
    raise SystemExit("[html] expected 2 comfyui_tts options, found %d" % total)
html, n_line = re.subn(r'[ \t]*<option value="comfyui_tts">[^<]*</option>[ \t]*\r?\n', "", html)
html, n_inline = re.subn(r'<option value="comfyui_tts">[^<]*</option>', "", html)
if n_line + n_inline != 2:
    raise SystemExit("[html] comfyui option removal mismatch: %d + %d" % (n_line, n_inline))
remove_block('<div id="tts-comfyui-section"', "div")
remove_block('<div id="model-form-comfyui"', "div")

# --- 数字人（Step 9）：步骤条项 + 整个步骤面板 + 辅助入口 ---
remove_block('<li class="step-item" data-step="9">', "li")
remove_block('<div id="step-panel-9"', "div")
html, n = re.subn(r'[ \t]*<button id="step6-btn-export-audio"[^>]*>.*?</button>\r?\n',
                  "", html, flags=re.S)
if n != 1:
    raise SystemExit("[html] step6-btn-export-audio not removed")
html, n = re.subn(r'[ \t]*<label class="creation-config-check"><input type="checkbox" '
                  r'data-creation-config-pause="digital_human">[^<]*</label>\r?\n',
                  "", html)
if n != 1:
    raise SystemExit("[html] digital_human pause checkbox not removed")
html, n = re.subn(r'[ \t]*<script src="digital_human_panel\.js[^"]*"></script>\r?\n',
                  "", html)
if n != 1:
    raise SystemExit("[html] digital_human_panel script tag not removed")
# 手动模式说明文字里提到数字人：改写为准确描述
html, n = re.subn(r"图片、AI Mask、旁白与数字人等环节", "图片、AI Mask、旁白等环节", html)
if n != 1:
    raise SystemExit("[html] manual-mode description not rewritten")

# 兜底：删除仍含数字人的整行 HTML 注释（步骤 9 的分区注释在块删除范围之外）
html = "\n".join(
    line for line in html.split("\n")
    if not ("数字人" in line and line.strip().startswith("<!--") and line.strip().endswith("-->"))
)

# --- 断言：不允许任何残留 ---
for marker in ("comfyui", "digital_human", "digital-human", "数字人",
               "step-panel-9", 'data-step="9"'):
    if marker.lower() in html.lower():
        raise SystemExit("[html] leftover marker: " + marker)

with open(path, "wb") as fh:
    fh.write(html.encode("utf-8"))
print("[html] index.html cleaned: %d -> %d chars" % (orig_len, len(html)))
'@
    $transformPy = Join-Path $tempDir 'transform_index.py'
    [System.IO.File]::WriteAllText($transformPy, $transformScript, [System.Text.UTF8Encoding]::new($false))
    & $portablePython $transformPy (Join-Path $destinationRoot 'static\index.html')
    if ($LASTEXITCODE -ne 0) { throw 'index.html 清理失败。' }
} finally {
    Remove-Item -LiteralPath $tempDir -Recurse -Force -ErrorAction SilentlyContinue
}

# ---------------------------------------------------------------------------
# [5/8] 写入路径自适应标记（记录构建时根路径，换机首次启动自动改写）
# ---------------------------------------------------------------------------
Write-Host '[5/8] 写入路径自适应标记'
$markerJson = @{ root = $sourceRoot } | ConvertTo-Json -Compress
[System.IO.File]::WriteAllText((Join-Path $destinationRoot 'data\.portable_root'), $markerJson, [System.Text.UTF8Encoding]::new($false))

# ---------------------------------------------------------------------------
# [6/8] 使用说明（带 BOM，保证记事本打开不乱码）
# ---------------------------------------------------------------------------
Write-Host '[6/8] 写入使用说明'
$readmePath = Join-Path $destinationRoot '便携版使用说明.txt'
$readme = @'
PPT 视频工作台（便携版）

使用方法
1. 把整个文件夹复制到目标电脑任意位置（仅支持 Windows 10/11 64 位），建议放在磁盘根目录或常用工作目录，不要放在需要管理员权限的系统目录。
2. 双击「启动.bat」。首次启动会为当前 Windows 用户注册包内字幕字体（无需管理员权限），并自动把包内素材路径修正为当前位置。
3. 浏览器会自动打开工作台页面；保持启动窗口开启，关闭窗口即停止服务。
4. 换机后无需任何设置：账号、模型连接、创作配置、图片风格、音色参考、字幕字体均已随包携带。

本便携包已包含
- 内置 Python、Node.js、FFmpeg 与 Remotion 渲染依赖（含离线渲染用的 Chrome Headless Shell），不需要另装任何开发环境。
- 全部账号、创作配置、模型连接、图片风格与模板、TTS 音色参考，开箱即用。
- 完整制作能力：文章导入、分镜规划、图片生成、AI Mask 逐元素揭示动画、旁白与云端语音合成、MP4/PPTX 导出、一键生成流程。

本便携包已移除（按需定制）
- 数字人讲解（Step 9）及相关素材。
- 本地 ComfyUI / IndexTTS（TTS 2.5）语音合成入口，语音合成使用云端服务（MiniMax / 豆包等）。
- 历史项目库：项目列表为空白，新建项目即可开始，不影响任何设置。

安全提醒
- 为实现免设置，本包包含 API Key 等访问凭据。仅复制、保存或传输到你完全信任的设备；不要发送给他人、上传网盘公开链接或提交到 Git。
- 所有数据保存在文件夹内的 data、runs、outputs 目录；备份时复制整个文件夹即可。
- 删除项目或卸载：直接删除整个文件夹即可，不在系统留下注册表项之外的内容（字幕字体如需清理，可在系统「设置-字体」中移除）。

常见问题
- 启动窗口闪退：右键「启动.bat」选择「编辑」或在该目录打开命令行运行，查看报错信息。
- 杀毒软件拦截：本包自带 Python/Node/FFmpeg 可执行文件，首次运行可能被安全软件扫描，选择允许即可。
'@
[System.IO.File]::WriteAllText($readmePath, $readme, [System.Text.UTF8Encoding]::new($true))

# ---------------------------------------------------------------------------
# [7/8] 便携包预检
# ---------------------------------------------------------------------------
Write-Host '[7/8] 预检便携包完整性'
$requiredPaths = @(
    '启动.bat', '停止.bat', 'server.py',
    'runtime\python\python.exe',
    'runtime\node\node.exe',
    'runtime\node\npx.cmd',
    'tools\ffmpeg\bin\ffmpeg.exe',
    'tools\ffmpeg\bin\ffprobe.exe',
    'scripts\remotion\node_modules\remotion\package.json',
    'scripts\remotion\node_modules\.remotion\chrome-headless-shell\win64\chrome-headless-shell-win64\chrome-headless-shell.exe',
    'scripts\portable_relocate.py',
    'scripts\portable_install_fonts.ps1',
    'data\projects.db',
    'data\credentials.json',
    'data\model_connections.json',
    'data\creation_configs.json',
    'data\.portable_root',
    'static\index.html',
    'static\fonts\portable'
)
foreach ($relativePath in $requiredPaths) {
    if (-not (Test-Path -LiteralPath (Join-Path $destinationRoot $relativePath))) {
        throw "便携包缺少必要文件：$relativePath"
    }
}
$pkgPython = Join-Path $destinationRoot 'runtime\python\python.exe'
# 注意：-c 代码里不能出现双引号——PowerShell 传参给原生命令时内嵌双引号会被
# 吞掉，Python 会收到 print([preflight] 这样的残缺语句直接 SyntaxError。
& $pkgPython -c 'import fastapi, uvicorn, sqlalchemy, PIL, numpy, pptx, yaml, multipart, httpx, openai, onnxruntime, pydantic'
if ($LASTEXITCODE -ne 0) { throw '便携 Python 依赖验证失败。' }
Write-Host '[preflight] Python dependencies OK'
# 嵌入式 Python 靠 python313._pth 的相对条目（..\..）解析应用根目录下的本地模块，
# 必须在包内实测一次：缺失该条目时 server.py 启动即 ModuleNotFoundError。
& $pkgPython -c 'import database, openai.types.beta.threads.runs'
if ($LASTEXITCODE -ne 0) { throw '便携 Python 无法导入应用本地模块或 openai 子包（检查 ._pth 条目与 /XD 排除是否误伤深层目录）。' }
Write-Host '[preflight] app modules and openai subpackages resolvable'
& (Join-Path $destinationRoot 'runtime\node\node.exe') --version
if ($LASTEXITCODE -ne 0) { throw '便携 Node 运行环境验证失败。' }
& (Join-Path $destinationRoot 'tools\ffmpeg\bin\ffmpeg.exe') -version | Select-Object -First 1 | Out-Host
if ($LASTEXITCODE -ne 0) { throw '便携 FFmpeg 验证失败。' }
# 复核 UI 清理结果（Select-String 默认不区分大小写，一个模式即可覆盖 comfyui/ComfyUI）
if (Select-String -LiteralPath (Join-Path $destinationRoot 'static\index.html') -Pattern 'comfyui' -Quiet) {
    throw 'index.html 仍残留 ComfyUI 引用。'
}
if (Select-String -LiteralPath (Join-Path $destinationRoot 'static\index.html') -Pattern '数字人' -Quiet) {
    throw 'index.html 仍残留数字人引用。'
}

# ---------------------------------------------------------------------------
# [8/8] 体积报告与 ZIP
# ---------------------------------------------------------------------------
$size = (Get-ChildItem -LiteralPath $destinationRoot -Recurse -File -Force | Measure-Object -Property Length -Sum).Sum
Write-Host ''
Write-Host ('[8/8] 便携包创建完成：{0}（{1:N2} GB）' -f $destinationRoot, ($size / 1GB)) -ForegroundColor Green

# 体积预算：防止无声膨胀（历史上曾因把上一个包复制进新包而每次翻倍）
$budgetBytes = 1.6GB
if ($size -gt $budgetBytes) {
    Write-Warning ('便携包体积 {0:N2} GB 超过预算 {1:N2} GB。' -f ($size / 1GB), ($budgetBytes / 1GB))
    Write-Host '体积最大的目录（用于定位意外内容）：' -ForegroundColor Yellow
    Get-ChildItem -LiteralPath $destinationRoot -Directory -Force | ForEach-Object {
        $dirBytes = (Get-ChildItem -LiteralPath $_.FullName -Recurse -File -Force -ErrorAction SilentlyContinue |
            Measure-Object -Property Length -Sum).Sum
        [pscustomobject]@{ MB = [math]::Round($dirBytes / 1MB, 1); Name = $_.Name }
    } | Sort-Object MB -Descending | Select-Object -First 10 | Format-Table -AutoSize | Out-Host
    Write-Host '提示：outputs/ 与 runs/ 应始终被排除；若出现在上面，说明排除列表被改坏了。' -ForegroundColor Yellow
}

if (-not $NoZip) {
    $folderName = Split-Path -Leaf $destinationRoot
    $zipPath = Join-Path (Split-Path -Parent $destinationRoot) "$folderName.zip"
    Write-Host "正在压缩 ZIP：$zipPath"
    & $tarExe -a -c -f $zipPath -C (Split-Path -Parent $destinationRoot) $folderName
    if ($LASTEXITCODE -ne 0) { throw "ZIP 打包失败，tar 退出码：$LASTEXITCODE" }
    $zipSize = (Get-Item -LiteralPath $zipPath).Length
    Write-Host ('ZIP 创建完成：{0}（{1:N2} GB）' -f $zipPath, ($zipSize / 1GB)) -ForegroundColor Green
    Write-Host '复制到其他电脑时，携带 ZIP 或整个文件夹均可；ZIP 需先解压再运行 启动.bat。'
}
