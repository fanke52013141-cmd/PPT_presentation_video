# 仓库与便携包体积审查

审核日期：2026-09-16
触发问题：「感觉项目文件好大，整个资源包可能要 1.6G，我的项目真有这么复杂吗？」

## 一、结论先说

**你的项目本身不复杂。** 实测数据：

| 口径 | 体积 | 说明 |
| --- | --- | --- |
| 整个工作目录 | **2121 MB** | 含依赖、运行数据、构建产物 |
| Git 跟踪的全部内容 | **89.2 MB** | 529 个文件 |
| 其中最大的一个文件 | **71.8 MB** | `tools/doclayout/doclayout_yolo_docstructbench_imgsz1024.onnx` |
| **真正的源码 + 前端 + 配置 + 文档** | **约 17 MB** | 去掉 ONNX 后的全部跟踪内容 |

也就是说：**代码只占 0.8%，99.2% 是依赖、模型、运行数据和一次打包产物。**
你感觉"没那么复杂"是对的 —— 源码确实只有 17MB。

而你说的"1.6G"，实测就是 `outputs/PPTStudio_Portable_Win_x64_20260915.zip`
**解压后的体积：1663.7 MB（1.66 GB）**。这个包本身也不复杂，它是被下面几个东西撑起来的。

## 二、当前工作目录的 2121 MB 花在哪

| 目录 | MB | 性质 | 该不该在仓库里 |
| --- | --- | --- | --- |
| `outputs/` | 760.7 | **一个 760MB 的旧便携包 zip** | 否（.gitignore 已排除） |
| `scripts/` | 683.7 | 其中 `scripts/remotion/node_modules` 628 MB | 否（已排除） |
| `runs/` | 270.0 | 50 个项目的运行数据（PNG 162 + MP4 92 + JSON 10） | 否（已排除） |
| `.venv/` | 190.5 | 开发用 Python 虚拟环境 | 否（已排除） |
| `.git/` | 93.7 | 历史（pack 80.6 MB，主要是 ONNX） | — |
| `tools/` | 71.8 | 全部是那一个 ONNX 模型 | **是**（已跟踪） |
| `static/` | 19.7 | 其中 `static/fonts` 18.5 MB（433 个 Noto Sans SC woff2 子集） | 否（字体已排除） |
| `references/` | 18.4 | 风格参考图 | 是 |
| `data/` | 4.7 | 含 `projects.db`、**`credentials.json`（API Key）** | 部分 |
| 其余全部 | ~3 | 代码、配置、模板、迁移 | 是 |

结论：**2121 MB 里只有 89 MB 属于"项目"，其余 2032 MB 是环境 + 运行产物 + 一个旧包。**

## 三、1.66 GB 便携包的构成（从 zip 中央目录实测）

| 路径 | MB | 判断 |
| --- | --- | --- |
| `scripts/remotion`（node_modules） | 529.2 | 必需，但可裁剪 |
| `tools/ffmpeg` | 434.4 | 必需，**但含 148 MB 死重**（见 P1-2） |
| `static/fonts` | 336.2 | 其中 `static/fonts/portable/` **38 个全量 CJK TTF = 317.7 MB**，且**根本没生效**（见 P1-1） |
| `runtime/python` | 166.1 | 必需（嵌入式 Python） |
| `runtime/node` | 95.0 | 必需（嵌入式 Node） |
| `tools/doclayout`（ONNX） | 71.8 | 必需 |
| `references/` | 18.4 | 部分必需 |
| `file-manifest.json` | 5.0 | **生成物**，26430 条文件清单 |
| `data/` | 4.5 | 必需（含凭据） |
| `runs/`、`outputs/`、`logs/`、`.git/`、`.venv/` | **0** | 0915 打包时恰好是空的 |

## 四、问题清单

### P0-1 打包脚本不排除 `outputs/` —— 会把自己的上一个包再装进去

`scripts/build_portable_package.ps1:18-21`：

```powershell
$excludedDirectories = @(
    '.git', '.venv', '.pytest_cache', '__pycache__', '.agents', '.codex', '.zcode',
    '.github', 'bad_cases', 'checks', 'docs', 'logs'
)
```

`outputs` 和 `runs` **都不在列表里**，而 robocopy `/E` 是全量复制。

当前 `outputs/` 里躺着 **760.7 MB 的 `PPTStudio_Portable_Win_x64_20260915.zip`**。
所以下一次打包的结果是：

```text
1.66 GB（0915 包的实际内容）
+ 0.76 GB（上一个包自己）
+ 0.27 GB（runs/ 当前 50 个项目）
≈ 2.7 GB
```

而且**每重打一次就再涨一个包的体积**（包套包）。这就是"怎么会那么大"的直接答案。

脚本默认把包输出到仓库**外面**（`:3`），但没有任何机制阻止之后把 zip 手工放回 `outputs/`，
而 `outputs/` 又是打包源的一部分 —— 这个环必须切断。

### P0-2 打包脚本不排除 `runs/` —— 270 MB 用户运行数据被打进"软件包"

同一份脚本只在 `:56-60` 删除 `digital_human` 素材，其余 `runs/` 全部原样复制。
现在 `runs/` 有 50 个项目、162 MB PNG、92 MB MP4。
软件分发包里不该带 270 MB 的用户工程数据（体积 + 隐私 + 首次启动状态）。

### P1-1 包里 317.7 MB 的字体既没用上、又装不上

事实链：

1. 包里 `static/fonts/portable/` 有 **38 个 TTF、317.7 MB**（单个最大 14.1 MB，典型全量 CJK 字体）；
2. `启动.bat:41` 每次启动调用 `scripts\portable_install_fonts.ps1`；
3. 该脚本 `:10` 找的是 **`<包根>/fonts`**：

```powershell
$root = Split-Path -Parent $PSScriptRoot      # <包根>
$fontsDir = Join-Path $root 'fonts'           # <包根>\fonts   ← 不存在
if (-not (Test-Path $fontsDir)) { exit 0 }    # 静默退出
```

4. 实测：包里**没有** `<包根>/fonts`（顶层 `fonts/` 条目数 = 0），字体实际在 `<包根>/static/fonts/portable/`；
5. 调用处还有 `>nul 2>&1` 吞掉输出，所以**失败了也没有任何提示**。

**后果**：这 317.7 MB 是纯死重，同时"便携包自带字幕字体"这个功能实际上是坏的
（脚本注释自己写着"注册失败会回退到微软雅黑"）。

### P1-2 ffmpeg 目录有 148 MB 死重

| 文件 | MB |
| --- | --- |
| `tools/ffmpeg/bin/ffmpeg.exe` | 141.4 |
| `tools/ffmpeg/bin/ffprobe.exe` | 141.2 |
| **`tools/ffmpeg/bin/ffplay.exe`** | **141.2** ← 播放器，流水线完全不用 |
| `tools/ffmpeg/doc/*.html` | ~7 |
| `tools/ffmpeg` 其余 | ~44 |

`启动.bat:15-16` 只设置 `FFMPEG_BINARY` / `FFPROBE_BINARY`。
删掉 `ffplay.exe` 和 `doc/` 可省 **约 148 MB**，零功能影响。

### P1-3 生成物被一起打包

- `scripts/remotion/public/runtime/` **54.7 MB** —— 渲染期生成物。
  `.gitignore:41` 已经排除它，但 **robocopy 不读 .gitignore**，所以照样进包。
- `file-manifest.json` **5.0 MB** —— 26430 条记录的生成清单。
- `data/backup_20260912/`、`data/backup_image_provider_20260912_151441/` —— 旧备份。

### P1-4 `tools/doclayout/*.onnx`（71.8 MB）拉高了 Git 历史

- 它是跟踪内容 **89.2 MB 中的 71.8 MB（80%）**；
- 它是二进制权重文件，**每次替换都会往 `.git` 历史里再加约 72 MB**（当前 pack 已 80.6 MB）；
- 它不是"源码"，不适合留在普通 Git 里。

### P2-1 包内 `data/` 含明文凭据

`data/credentials.json` 会被复制进包（脚本 `:71` 还把它列为必需文件）。
`便携版使用说明.txt:104` 已经警示"本包包含 API Key"。
另外 `data/credentials.json` 只有 0.0 MB 但 `data/model_connections.json` 等也一并打包。
建议：包内凭据加密或首次启动时要求重新填写，至少不要在"体积审查"之外被忽略。

### P2-2 现在这个工作目录**无法**重新打包

脚本 `:33-36` 要求源目录存在 `runtime\python\python.exe`，`:67-68` 要求 `tools\ffmpeg\bin\ffmpeg.exe`。
实测当前目录：

- `runtime/` —— **不存在**
- `tools/` —— 只有 `doclayout`，**没有 ffmpeg**

所以现在直接运行 `scripts/build_portable_package.ps1` 会在 **[2/4] 步就抛错**
（`未找到包内 Python`）。这说明 0915 那个 zip 不是从当前这份目录构建的，
或者 `runtime/`、`tools/ffmpeg` 之后被删掉了 —— **这一点需要你确认**，
否则"下次打包"的真实体积无法预测。

### P2-3 包里的项目可能是空壳（需确认）

0915 包内 `runs/` 的文件数 = **0**，但 `data/projects.db` 有 0.2 MB 内容。
如果 db 里有项目而 runs 为空，那么打开这些项目会没有图片/音频。
需要确认这是"打包前特意清空了 runs"还是打包流程的缺陷。

## 五、建议与预期效果

### 立即做（改动小、收益最大）

1. **切断包套包**：把 `outputs`、`runs` 加入 `build_portable_package.ps1:18-21` 的
   `$excludedDirectories`；并在脚本开头断言源目录内不存在 `outputs/*.zip`。
2. **清掉当前那个 760.7 MB 的旧包**（或移到仓库外归档）。
3. **补排除生成物**：`scripts\remotion\public\runtime`、`file-manifest.json`、`data\backup_*`。
4. **修字体路径**：`portable_install_fonts.ps1:10` 改为
   `Join-Path $root 'static\fonts\portable'`，并去掉 `启动.bat:41` 的 `>nul 2>&1`，
   让失败可见（或在脚本内写日志）。

### 中期做

5. **字体精简**：38 个全量 CJK TTF（317.7 MB）→ 只保留实际提供的字体家族，
   或按常用汉字子集化，预计可省 **250–300 MB**。
6. **ffmpeg 瘦身**：删 `ffplay.exe` + `doc/`，省 **约 148 MB**。
7. **ONNX 移出 Git**：改用 Git LFS，或首次运行时下载并校验哈希。
8. **给打包脚本加体积预算断言**：例如总大小超过 800 MB 就失败，
   并打印体积 top-10 目录。防止体积再次无声膨胀。

### 预期效果

| 场景 | 体积 |
| --- | --- |
| 现状（下一次打包，未修） | **约 2.7 GB** |
| 仅修排除列表（P0-1/P0-2/P1-3） | 约 1.66 GB |
| 再修字体（P1-1）与 ffmpeg（P1-2） | **约 1.20 GB** |
| 再裁剪 node_modules 生产依赖 | 有望降到 **1.0 GB 以内** |

而 Git 仓库侧：把 ONNX 移出后，跟踪内容从 **89.2 MB → 约 17 MB**。
