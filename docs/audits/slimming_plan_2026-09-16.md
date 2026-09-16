# 仓库与便携包瘦身方案

编制日期：2026-09-16
依据：`docs/audits/repo_size_review_2026-09-16.md` + 本轮逐项实测（未删除任何文件）
原则：**只删不可再生的浪费，不删功能和作品**。每一项都给出"谁在用 / 删了会怎样"。

## 一、结论先说

| 分类 | 体积 | 处置 |
| --- | --- | --- |
| **A. 零功能损失**（缓存 / 可重建产物 / 完全重复） | **约 251 MB** | ✅ 已删除 253 MB |
| **B. 需要你决策**（分发成品 / 你的作品 / 字体能力） | **约 1.15 GB** | 字体已救回；zip 待你最终确认 |
| **C. 必须保留**（删了会坏功能） | **约 1.05 GB** | 不动 |

而**"越打越大"的真正元凶不是文件多，是打包脚本不排除 `outputs/` 和 `runs/`** ——
它会把你**上一次打好的包**再装进新包，每打一次涨一个包。这一条比所有文件都重要。

## 〇、执行记录（2026-09-16）

| 动作 | 结果 |
| --- | --- |
| 从便携包 zip 中救出设计字体 → `static/fonts/portable/` | **+317.7 MB**（40 个文件） |
| **删除 `outputs/PPTStudio_Portable_Win_x64_20260915.zip`** | **−760.7 MB** |
| 删除渲染成品视频 `videos/render_*.mp4` + `out.mp4` | **−92.4 MB**（8 个文件；同步清理 `artifact_records` 4 条） |
| 删除 webpack 打包缓存 `node_modules/.cache` | **−99.0 MB** |
| 删除 Remotion 运行时缓存 `public/runtime` | **−54.7 MB** |
| 删除 `__pycache__` / `.pytest_cache` / 16 个孤儿 runs 目录 | **−7.0 MB** |
| **仓库合计** | **2441.7 → 1522.2 MB** |

### 字体修复（已完成，可验证）

| 步骤 | 结果 |
| --- | --- |
| 体检 38 个 TTF | ✅ 全部可解析、与 CSS 清单一致、中文字形齐全 |
| 修 `portable_install_fonts.ps1` 的字体目录（改为 `static/fonts/portable`，保留旧路径回退） | ✅ |
| 去掉 `启动.bat` 的 `>nul 2>&1`（失败不再静默） | ✅ |
| 把安装接到 `launch.bat` / `start_here.bat` / `run_local.ps1`（原先只有便携版会尝试） | ✅ |
| **实际注册到当前用户字体表** | **新注册 31 个，已存在 7 个，失败 0 个** |
| 用 GDI+ 按字体名复验（渲染就是这条路径） | ✅ `LXGW Marker Gothic`（默认字幕字体）、`Ma Shan Zheng`、`ZCOOL XiaoWei`、`Noto Sans TC`、`LXGW WenKai TC` 全部可解析 |
| 幂等复测（再跑一次） | ✅ `registered=0 skipped=38 failed=0` |

### 顺带修掉的三个既有缺陷

1. **`build_portable_package.ps1` 在本机根本无法运行**。系统 ANSI 码页是 936，而该脚本是**无 BOM 的 UTF-8 中文文件**，
   PowerShell 5.1 按 GBK 解码后中文字节会"吃掉"后面的引号，导致解析失败（实测 36 个语法错误）。
   已给它（以及含中文的 `run_local.ps1`、`start_digital_human_stack.ps1`）补上 **UTF-8 BOM**，现在全部解析通过。
   这也解释了为什么 0915 那个包不是它构建的 —— 它当时跑不起来。
2. **包内使用说明是乱码**：脚本用 `UTF8Encoding($false)`（无 BOM）写中文 readme，Windows 记事本会按 ANSI 显示成乱码。已改为带 BOM。
3. **打包脚本加体积预算断言**：超过 1.6 GB 时打印体积 top-10 目录并提示"若出现 outputs/runs 说明排除列表被改坏"，防止再次无声膨胀。

### 打包脚本排除列表（已修）

新增排除：`outputs`、`runs`、`.tmp`、`node_modules\.cache`、`public\runtime`、`tools\ffmpeg\doc`，
以及文件级排除 `ffplay.exe`、`file-manifest.json`。

### 新增 `scripts/prepare_portable_runtime.ps1`

把"嵌入式 Python + Node + ffmpeg/ffprobe"的获取脚本化（原先仓库里完全没有这个环节，
所以重建便携包只能手工找文件，上一份包还是从旧 zip 里挖出来的）。
默认版本对齐上一份包的验收记录：Python 3.13.0、Node v22.22.2、ffmpeg gyan.dev **full**。

> ⚠️ **该脚本未做端到端实测**：本机 PowerShell 无外网（python.org / nodejs.org 均连接失败），
> 只验证了语法、纯 ASCII 与 `-DryRun` 的 URL/路径规划。首次使用请逐步核对输出。
> ffmpeg 只下载 `ffmpeg.exe` + `ffprobe.exe`（不含 ffplay/doc），并在结尾**强制校验**
> `h264_nvenc`/`h264_qsv`/`h264_amf` 是否仍被 advertize —— 否则渲染会静默退回 CPU。

## 二、A 类：可以直接删（零功能损失，约 251 MB）

| 项目 | 体积 | 它是什么 | 删了会怎样 | 证据 |
| --- | --- | --- | --- | --- |
| `scripts/remotion/node_modules/.cache/webpack` | **99.0 MB** | 打包器磁盘缓存 | 下次渲染自动重建，只是首次慢一点 | 纯缓存目录 |
| `scripts/remotion/public/runtime/**` | **54.7 MB** | Remotion 渲染运行时素材（4 个项目的 slide 副本） | 下次渲染前由 `build_remotion_props.py` 重新生成；删除项目时系统本来就会清它 | `remotion_runner._build_remotion_props`、`project_service.py:583` 明确清理该目录 |
| `runs/*/slides/*/assets/full_slide.png` | **48.9 MB**（34 个） | reveal 场景构建出的整页底图 | 由 `scripts/build_reveal_scene.py:301` 在确认/渲染时重建 | 同一张图与 `visual_draft.png` 逐字节相同（哈希一致） |
| `runs/*/out.mp4` | **46.2 MB**（4 个） | 旧版遗留的"最终视频" | 与 `videos/render_*.mp4` **逐字节相同**；当前代码只读不写它，不会丢任何独有内容 | 哈希对比一致；`video_artifact_service.py:356` 仅在项目没有任何渲染产物时才展示它 |
| `__pycache__/`、`scripts/**/__pycache__/`、`.pytest_cache/` | ~2.5 MB | 字节码/测试缓存 | 自动重建 | — |
| `runs/` 中 16 个孤儿目录 | 0.0 MB | 数据库已删除、文件残留的空壳 | 无影响（顺手清掉，避免进包） | 数据库 155 个项目 vs runs 171 个目录 |

**唯一需要留意的**：`assets/full_slide.png` 和 `public/runtime` 删除后，**下一次渲染前会自动重建**。
如果你近期不打算再渲染，打开 Mask 工作区时也会按需重建单个 slide（`mask_preview_service`）。
所以这两个删了是安全的，但我仍建议**先删缓存类（99 + 54.7 MB），确认一次渲染正常后再删 assets**——
不是因为风险高，而是这样你能看到它确实自己长回来了。

## 三、C 类：必须保留（删了会坏功能）

| 项目 | 体积 | 谁在用 | 删了会怎样 |
| --- | --- | --- | --- |
| `scripts/remotion/node_modules`（去掉 `.cache` 后约 529 MB） | 529 | `npx remotion render` | **离线包必须有**：`remotion_runner._ensure_remotion_dependencies` 发现没有 `node_modules` 会执行 `npm install`（需联网） |
| └ `node_modules/.remotion/chrome-headless-shell` | 269.1 | Remotion 渲染用的无头浏览器 | 删了渲染直接失败。当前渲染命令没有传 `--browser-executable` |
| └ `@remotion`、`@rspack`、`@esbuild`、`webpack`、`react-dom` | 171 | 渲染与打包链路 | 同上 |
| `.venv` | 190.5 | `launch.bat:8`、`start_here.bat:12`、`run_local.ps1:48` 的正常启动环境；内含 `onnxruntime`(43.9) 供 AI Mask 使用 | 正常启动路径失效（便携包走 `runtime/python`，两者互不替代） |
| `tools/doclayout/doclayout_yolo_docstructbench_imgsz1024.onnx` | 71.8 | `ai_mask_doclayout.py` 的 DocLayout-YOLO 版面检测 | AI Mask 的元素检测退化 |
| `static/fonts`（433 个 woff2） | 18.5 | 网页 UI 字体，由 `static/fonts/local-fonts.css` 逐条 `@font-face` 引用 | 网页排版退化 |
| `references/`（风格参考图） | 18.4 | Step 3「必须/优先使用参考图」策略 | 参考图功能失效 |
| `data/`（`projects.db`、`credentials.json`、各类模板） | 4.8 | 项目库、凭据、模板 | 应用无法启动 |
| `checks/`、`docs/`、`scripts/`（源码） | ~6 | 测试与文档 | — |

## 四、B 类：需要你决策（约 1.15 GB）

### 决策 1：`outputs/PPTStudio_Portable_Win_x64_20260915.zip`（760.7 MB）

先纠正一个理解：它**不是"打包的项目"**，而是一个 **Windows 免安装版应用分发包**
（含一份应用代码副本 + 嵌入式 Python/Node/ffmpeg + 数据库快照 + 你的 API 凭据）。
所以它确实是从源码构建出来的产物、可以重建 —— 但重建需要材料。

**关键发现：这个 zip 是目前全盘唯一一份运行时材料的载体。**
我在 `D:\software` 及各常见位置搜过，没有任何已解压的 `runtime\python\python.exe`、
`runtime\node\node.exe`、`tools\ffmpeg\bin\ffmpeg.exe`，仓库里也**没有任何下载/安装脚本**
（搜 `Invoke-WebRequest`/`Expand-Archive`/`python-embed` 等，零匹配）。

zip 里除字体（已救出）之外还在用的独有内容：

| 内容 | 解压后 | 说明 |
| --- | --- | --- |
| `runtime/python` | 166.1 MB | 嵌入式 Python + 应用依赖 |
| `runtime/node` | 95.0 MB | 嵌入式 Node |
| `tools/ffmpeg` | 434.4 MB | 其中 ffmpeg.exe+ffprobe.exe 有 282.6 MB，**ffplay.exe 141.2 MB 是死重** |

其余内容（`scripts/remotion/node_modules` 529 MB、`tools/doclayout` 71.8 MB、
`references` 18.4 MB、`static/fonts` 的 woff2）**本地都已经有**。

#### 两个选项

| 选项 | 仓库净变化 | 代价 |
| --- | --- | --- |
| **A. 直接删 zip**（推荐） | **−760.7 MB** | 以后要重新打包需重新准备 Python/Node/ffmpeg；我建议同时补一个 `prepare_portable_runtime.ps1` 把它脚本化 |
| **B. 先抽出 runtime 再删** | ≈ **−207 MB** | 立刻可重新打包，但要保留 554 MB（去掉 ffplay/doc 后）的运行时 |

**推荐 A**，理由：这些材料全部可通过官方渠道重新获取（Python embeddable + `requirements.txt`、
Node 官方 zip、gyan.dev ffmpeg），把它脚本化比留一个 760 MB 的二进制 blob 更好；
而且包里那份 ffmpeg 是**体积严重超标的 full 构建**（下节），保留它本身就不是好选择。

## 四之二、ffmpeg 体检（回应"功能是不是多了、有些没用到"）

我把包里的 ffmpeg 抽出来实测了它的构建配置（检查完已删除临时文件）：

```text
ffmpeg version 7.1.1-full_build-www.gyan.dev
245 个编码器 / 545 个解码器 / 569 个滤镜 / 187 个复用器 / 9 种硬件加速
启用了 29 个非 lib 开关 + 66 个外部库
```

### 应用**真正用到**的能力（很少）

| 用途 | 需要的能力 | 出现位置 |
| --- | --- | --- |
| 探测时长/码流 | `ffprobe` | `scripts/media_tools.py`、`digital_human_service.py`、`validate_render_color.py` |
| 整段语音拼接 | 逐页转 wav、`anullsrc` 生成静音、`concat` 解复用、输出 mp3 | `digital_human_routes.py:791-827` |
| 数字人圆形窗合成 | `scale` / `crop` / `setsar` / `overlay` / `fps`、`libx264`、`aac`、`+faststart` | `digital_human_service.py:547-575` |
| Mock 测试视频 | `drawtext`（需 libfreetype/fontconfig）、`libx264`、`aac` | `digital_human_service.py:317-325` |
| 渲染前硬件编码器探测 | 必须能**列出** `h264_nvenc` / `h264_qsv` / `h264_amf` | `remotion_runner.py:121` → `video_acceleration.py:28-51` |

> 注意最后一行：`ffmpeg -encoders` 的输出**是有功能的**，它决定渲染走 GPU 还是 CPU。
> 换精简构建后必须复测这一点，否则会静默退回 CPU 编码（**变慢但不会坏**，
> `video_acceleration.select_video_encoder` 会给出 `hardware_h264_encoder_not_advertised` 原因）。

### 明显**用不到**的部分

| 类别 | 例子 |
| --- | --- |
| 光盘/蓝光 | `libbluray`、`libdvdnav`、`libdvdread`、`libcdio` |
| 广播/串流 | `libaribb24`、`libaribcaption`、`libzvbi`、`libsrt`、`librist`、`libssh`、`libzmq` |
| 终端字符画 | `libcaca` |
| 从不接触的音频编解码 | `libgsm`、`libcodec2`、`libilbc`、`libopencore-amr*`、`libspeex`、`libvorbis`、`libtheora`、`libtwolame`、`libshine`、`libopus`、`liblc3`、`libflite` |
| 从不使用的音频效果 | `ladspa`、`libbs2b`、`librubberband`、`libsoxr`、`libmodplug`、`libgme`、`libopenmpt` |
| 从不使用的视频编码 | `libx265`、`libvpx`、`libaom`、`libsvtav1`、`librav1e`、`libvvenc`、`libxeve`、`libxevd`、`libuavs3d`、`libdavs2`、`libxavs2`、`libxvid`、`libjxl`、`libwebp`、`libopenjpeg`、`libdav1d` |
| 分析/测量 | `libvmaf`、`libvidstab`、`liblensfun`、`libzimg`、`chromaprint`、`libquirc`、`libqrencode` |
| GPU 着色器 | `libplacebo`、`libshaderc`、`vulkan`、`opencl`、`frei0r` |
| 设备/采集 | `sdl2`、`avisynth`、`mediafoundation` |
| **整个播放器** | **`ffplay.exe`（141.2 MB）—— 完全是播放器，代码和启动脚本都没引用它** |
| 文档 | `doc/*.html`（约 7 MB） |

### 结论与建议

1. **零风险立刻可省 148 MB**：删 `tools/ffmpeg/bin/ffplay.exe`（141.2 MB）+ `tools/ffmpeg/doc/`（约 7 MB）。
   `启动.bat:15-16` 只设置 `ffmpeg`/`ffprobe` 两个路径，没有任何地方用到 ffplay。
2. **想再省一半需要换精简构建**：把 gyan.dev **full**（141 MB/exe）换成更小的构建，
   `ffmpeg.exe + ffprobe.exe` 从 282.6 MB 降到约 100–150 MB。
   **换完必须验证**：`ffmpeg -encoders` 仍列出 `h264_nvenc`/`h264_qsv`/`h264_amf`，
   且 `libx264`、`aac`、`libmp3lame`、`drawtext`、`scale/crop/overlay/setsar/fps`、
   `concat`、`lavfi`、`mp4/mp3/wav` 都在。
   （`drawtext` 只在 Mock 模式用；若确定不用 Mock，可再省 freetype/fontconfig 相关体积。）
3. **不建议自己编译裁剪 ffmpeg**：收益（再省几十 MB）远小于维护成本与兼容性风险。

### 决策 2：`runs/` 里的作品数据（删除视频后 270.4 MB）

`runs/` 是 171 个项目的运行目录，**这是你的作品，不是垃圾**。构成：

| 内容 | 体积 | 是否可再生 |
| --- | --- | --- |
| `visual_draft.png` 等 slide 图片 | ~160 MB | ❌ 重生成要花**生图额度和钱**，务必保留 |
| ~~`videos/render_*.mp4` 渲染成品~~ | ~~46 MB~~ | ✅ **已按你的要求删除**（含重复的 `out.mp4`，共 92.4 MB） |
| 音频/字幕/时间轴 | ~7 MB | ⚠️ 可重新合成，但要花 TTS 额度 |
| JSON/日志等文本 | ~10 MB | ✅ 可再生 |

**已执行**：删除了 8 个 mp4（`videos/render_*.mp4` 4 个 + `out.mp4` 4 个，共 92.4 MB），
并同步清理了 `artifact_records` 里的 4 条视频记录，避免界面列出指向已删文件的坏条目。

**其余一律保留**：slide 图片、音频、字幕、时间轴都是花钱或花额度生成的。
真正该做的是把 `runs/` **排除在便携包之外** —— 软件分发包不该带用户工程数据（体积 + 隐私 + 首次启动状态）。

如果你的目标是让"便携包"能直接带着项目走，那就应该由你**显式挑几个项目**打包，而不是把 171 个全塞进去。

### 决策 3：打包用的中文字体（原包里 317.7 MB）—— 已救回并完成体检

**已从 zip 中取出到 `static/fonts/portable/`（40 个文件，317.7 MB）。**

#### 体检结论：**字体文件完全可用，但目前一处接线都没接上，所以一个设计字体都没生效**

| 检查项 | 结果 |
| --- | --- |
| 38 个 TTF 能否解析 | ✅ 全部可解析，**0 个损坏** |
| 与 `bundled-google-fonts.css` 的映射 | ✅ 完全一致（38 条 `@font-face`，无缺失、无多余） |
| 中文/标点字形是否真的存在 | ✅ 抽样渲染通过（不会出方框） |
| 覆盖应用提供的 14 款字幕字体 | ⚠️ **13/14**。缺 `LXGW WenKai`（简体文楷）；包里只有 `LXGW WenKai TC`（繁体） |
| 额外附带 | `Plus Jakarta Sans`（界面字体，3 个字重） |

#### 但字体**没有生效**，断在三个地方

1. **安装脚本找错目录**（致命）：`scripts/portable_install_fonts.ps1:10` 找 `<包根>/fonts`，
   字体实际在 `<包根>/static/fonts/portable/`。而 `启动.bat:41` 把输出重定向到 `>nul 2>&1`，
   所以脚本 **静默 `exit 0`，从来没装上过任何字体**。
2. **只有便携版会尝试安装**：`launch.bat` / `start_here.bat` / `run_local.bat` 都不调用安装脚本，
   所以**本地渲染也拿不到这些字体**。
3. **网页端也没用它们**：`static/index.html:11` 与 `static/style.css:1` 直接引 Google Fonts CDN；
   包内的 `bundled-google-fonts.css` 从未被任何页面引用。

#### 为什么"系统字体"是决定性的一环

`scripts/remotion/src/Video.tsx:384-410` 的 `subtitleFontFamily()` **只返回 CSS 字体名**
（如 `"Ma Shan Zheng", "Microsoft YaHei", KaiTi, cursive`），
没有任何 `@remotion/google-fonts`、`FontFace` 或 `staticFile` 调用 ——
**Remotion 只认系统已安装字体**。所以字体不装进 Windows，选了也等于没选。

本机实测：`Noto Sans SC`、`Noto Serif SC` 已装（来自其它来源）；
`LXGW WenKai TC`、`Ma Shan Zheng`、`ZCOOL XiaoWei` **未安装** → 选这些字体渲染出来仍是微软雅黑。

#### 让字体真正可用需要做的三件事

| # | 改动 | 影响面 |
| --- | --- | --- |
| 1 | 修 `portable_install_fonts.ps1:10` 的路径（优先 `static/fonts/portable`，回退 `fonts`），并让 `启动.bat:41` 不再吞掉输出 | 便携包 |
| 2 | 让 `launch.bat` / `start_here.bat` 也调用一次安装脚本 | 本地渲染 |
| 3 | （可选）`index.html` 增加 `bundled-google-fonts.css` 作为离线回退 | 离线时网页预览 |

> 另外 `LXGW WenKai`（简体）缺失，需要单独补一个 TTF 才能让 14/14 齐全。

#### 至于 `static/fonts` 里那 433 个 woff2（18.5 MB）

`static/fonts/local-fonts.css` **没有被任何文件引用**（index.html、style.css、JS、middleware 全无），
所以这 18.5 MB 目前也是"下载了但没接线"。可以：
**（a）** 在 `index.html` 里引用它，让网页端离线也能用本地字体；或 **（b）** 删掉。
它不属于你要求的"设计字体"，是网页 UI 字体。

### 决策 4：`.git` 历史里的 ONNX（93.9 MB）

`tools/doclayout/*.onnx` 是**跟踪内容 89.2 MB 中的 71.8 MB（80%）**，是二进制权重。
它必须保留，但每次替换都会往历史里再加 ~72 MB。

| 选项 | 效果 |
| --- | --- |
| 改用 Git LFS 跟踪该文件 | 克隆体积大幅下降；需要 LFS 环境 |
| 改为首次运行时下载 + 哈希校验 | 仓库最轻；需要联网，且要写下载逻辑 |
| 保持现状 | 仓库每次换模型都涨 72 MB |

**这一项不影响便携包体积**（模型本来就该在包里），只影响仓库分发。优先级最低。

## 五、打包脚本的元凶（真正的"越打越大"）

`scripts/build_portable_package.ps1:18-21` 的排除列表：

```powershell
$excludedDirectories = @(
    '.git', '.venv', '.pytest_cache', '__pycache__', '.agents', '.codex', '.zcode',
    '.github', 'bad_cases', 'checks', 'docs', 'logs'
)
```

**缺了 `outputs` 和 `runs`**，而 robocopy `/E` 是全量复制。后果：

```text
1.66 GB（0915 包的实际内容）
+ 0.76 GB（outputs 里的上一个包自己被装进来）
+ 0.36 GB（runs 当前 171 个项目）
≈ 2.8 GB   ← 下一次打包的结果
```

而且**每重打一次就再涨一个包的体积**（包套包）。

### 需要补的排除项

| 排除 | 体积 | 理由 |
| --- | --- | --- |
| `outputs` | 760.7 MB | 分发成品不是源码 |
| `runs` | 362.8 MB | 用户工程数据，不该进软件包 |
| `scripts\remotion\public\runtime` | 54.7 MB | 渲染缓存，首次渲染自建 |
| `node_modules\.cache` | 99.0 MB | 打包器缓存 |
| `file-manifest.json` | 5 MB | 生成物，仓库里没有任何代码生成或读取它 |
| `data\backup_*` | ~0.4 MB | 旧备份 |
| `tools\ffmpeg\bin\ffplay.exe` | 141.2 MB | 播放器，`启动.bat:15-16` 只用 ffmpeg/ffprobe |
| `tools\ffmpeg\doc` | ~7 MB | HTML 文档 |

### 一个必须先解决的前置问题

打包脚本 `:33-36` 要求源目录有 `runtime\python\python.exe`，`:67-68` 要求 `tools\ffmpeg\bin\ffmpeg.exe`。
**当前工作目录两者都不存在**（实测 `runtime` = False、`tools\ffmpeg` = False），
所以现在直接运行打包脚本会在 **[2/4] 步就抛错**。

而仓库里**没有任何下载/安装这两个运行时的脚本**（我搜过 `Invoke-WebRequest`/`Expand-Archive`/`python-embed` 等，无匹配）。

所以在你补齐这两样之前，"下次打包多大"我无法实测验证，只能按构成推算。
**建议顺手补一个 `scripts/prepare_portable_runtime.ps1`**，把"下载嵌入式 Python/Node + ffmpeg"固化下来，
否则每次打包都要靠手工找文件。

## 六、预期效果

| 场景 | 仓库体积 | 便携包体积 |
| --- | --- | --- |
| 现状（直接打包，未修） | 2.25 GB | **≈ 2.8 GB**（且每次增长） |
| 只修排除列表（§五） | 1.49 GB | **≈ 1.66 GB**（不再增长） |
| ＋ A 类清理（§二） | **1.24 GB** | ≈ 1.41 GB |
| ＋ ffmpeg 去掉 ffplay/doc | 1.24 GB | **≈ 1.26 GB** |
| ＋ 字体改为精选 4 款 | 1.24 GB | ≈ 1.35 GB（功能修好了） |
| ＋ 字体放弃 | 1.24 GB | **≈ 1.26 GB** |

仓库侧另计：ONNX 移出 Git 后，跟踪内容 **89.2 MB → 约 17 MB**。

## 七、执行状态与剩余待办

### 已完成（2026-09-16）

- [x] 从 zip 救出设计字体 → `static/fonts/portable/`（317.7 MB）
- [x] **删除 760.7 MB 的便携包 zip**（仓库 2280.7 → 1522.2 MB）
- [x] 删除渲染成品视频 8 个 + 清理 `artifact_records` 4 条（92.4 MB）
- [x] 删除 webpack 缓存 / Remotion 运行时缓存 / `__pycache__` / 16 个孤儿 runs 目录（160.6 MB）
- [x] **字体修复并实测生效**：31 个新注册、GDI+ 按名解析通过、幂等
- [x] 字体安装接入 `启动.bat` / `launch.bat` / `start_here.bat` / `run_local.ps1`
- [x] 修打包脚本排除列表 + 体积预算断言 + readme 编码
- [x] 修三个 .ps1 的 BOM 问题（其中 `build_portable_package.ps1` 原本完全无法解析）
- [x] 新增 `scripts/prepare_portable_runtime.ps1`（DryRun 已验证，下载未实测——无外网）
- [x] ffmpeg 体检（gyan.dev full build，66 个外部库里约 2/3 用不到）

### 待办（按优先级）

1. **验证一次渲染**：确认 `public/runtime` 与 `assets/full_slide.png` 会被自动重建，并确认字幕字体生效
2. **确认渲染字幕用的是设计字体**（打开一个项目渲染一页，看字幕字形是否变化）
3. **补 `LXGW WenKai`（简体）字体**，凑齐 14/14
4. 删 `runs/*/slides/*/assets/full_slide.png`（48.9 MB，可重建，建议等第 1 步验证后）
5. `tools/ffmpeg`（下次准备时）去掉 `ffplay.exe` + `doc/`（148 MB）+ 评估换精简构建
6. `static/fonts` 里 433 个未引用的 woff2（18.5 MB）：接线或删除
7. （可选，最后）ONNX 移出 Git

## 八、已无待决策项

三个决定都已执行：

| 决定 | 结果 |
| --- | --- |
| 760 MB 便携包 zip | ✅ 按选项 A 删除；已补 `prepare_portable_runtime.ps1` 保住重建能力 |
| 设计字体保留 | ✅ 已救回 + **修复并实测生效**（原先一处接线都没接上） |
| 渲染成品视频 | ✅ 已删除（含重复的 `out.mp4`），同步清理数据库记录 |
| ffplay | ✅ 已确认全仓库零引用（网页播放用浏览器原生 `<video>`），已加入打包排除 |

**唯一仍需你确认的小项**：`runs/*/slides/*/assets/full_slide.png`（48.9 MB，可重建）
—— 建议等你跑过一次渲染、确认它能自动重建之后再删。


## 九、瘦身后的稳定性验证（2026-09-16）

前提是项目依旧可以稳定跑，所以逐层验证，不只看文件是否还在。

### 1. 静态与单元层

| 检查 | 结果 |
| --- | --- |
| 全量 pytest | **950 passed / 4 failed**，与改动前 pristine HEAD 基线**逐条相同** → **零新增失败** |
| AGENTS.md Required Validation | 全绿：compileall、node --check ×3、visible-flow、迁移+失效+safeguards（16 passed）、agent 契约 --check、source registration contract、5 个脚本式检查 |
| 6 份 .ps1 解析 | 全部 OK（含修复了 BOM 的 3 份） |
| 3 个启动脚本 | 括号配对、字体安装调用都在独立 if exist 块内、无 errorlevel 门控 |

### 2. 真实服务端到端（起服务的只读冒烟）

start_server.py 起在 8123/8124 端口，**21 项接口全部 200**，覆盖：

- 首页 / 项目列表 / 账号列表 / 系统设置 / 运行时诊断 / 限额治理器快照
- **被删视频的 4 个项目**：项目详情、成片列表（返回 {success: true, videos: []} 优雅降级为空）、一键状态、导出列表、任务列表
- **字体服务**：/fonts/portable/089a8698ad08d783ade46995.ttf → 200，**3,185,012 字节**（LXGW Marker Gothic 正常提供）
- 步骤链路：Step2 分镜 / Step3 图片与视觉设置 / Step5 Mask / Step6 旁白 / Step7 音频状态 / 字幕设置 / PPTX 就绪度 / slide 图片（1.8 MB）

> 排错记录：首轮出现 12 个 404，全部是**我测试脚本自身的问题**——静态资源挂在 / 而不是 /static；
> 项目详情**按账号过滤**，那 4 个项目属于 acct_c0fc31248cdc44b2（晓晓华）而非 default。
> 用真实路由表与正确账号头重测后全绿。

### 3. 被删缓存能否自动重建（本次最高风险项）

用与 remotion_runner._build_remotion_props **完全相同的调用**复现：

    python scripts/build_remotion_props.py --run-dir runs/1448e51e_100854 --repo-root . \
      --remotion-public-dir scripts/remotion/public --width 1920 --height 1080
    -> exit 0；public/runtime 重新生成 36 个文件 / 30.7 MB；remotion_props.json 正常产出

**结论：public/runtime 是纯缓存，删除安全。** 验证后已重新清掉。

另核对：remotion_props.json 在原有渲染成片的 4 个项目里**本来就存在**（我的重建只是刷新了其中一个的时间戳），
且它每次渲染前都会重建，不承担新鲜度判定 → 无状态影响。

### 4. 字体安装不会拖慢或阻断启动

| 检查 | 结果 |
| --- | --- |
| 已安装后再跑一次 | 退出码 0，**0.94 秒** |
| 字体目录不存在时（模拟其他机器） | 打印跳过原因并 exit 0 |
| 启动脚本是否据此判失败 | 否——三处都是独立 if exist 块，无 errorlevel 判断 |

### 5. 验证过程中发现并已修复：测试套件污染真实项目库

**我跑全量测试时，测试套件往真实 data/projects.db 和 runs/ 里写了 120 个测试项目**
（Agent E2E Test Project、Lock Test、Parity Mask Default Test 等 15 个固定名称 × 8 轮）。

已按三重条件（**精确测试名 + default 账号 + slides 为空**）识别并清理：

    清理前：数据库 170 个项目 / runs 170 个目录
    清理后：数据库  50 个项目 / runs  50 个目录   <- 双向零孤儿
            分布：default 42、晓晓华 6、语文老师 2

50 这个数字与便携包验收记录「原电脑的 50 个项目仍在」完全吻合，说明清理没有误伤真实项目。

> **这是既有的卫生问题，不是我引入的**：checks/agent/ 等测试直接用 SessionLocal 指向生产库。
> 你以后每跑一次 pytest checks/agent/ 都会被灌入约 15 个测试项目。
> 建议让测试改用临时数据库（独立 PPT_STUDIO_DB 或用 fixture 覆盖 SessionLocal）。

### 6. 验证后的最终体积

    scripts 530.1 · static 337.4 · runs 283.6 · .venv 190.5 · .git 93.9 · tools 71.8 · references 18.4
    TOTAL: 1540.3 MB   （本次瘦身起点 2441.7 MB）

## 十、让 CI 全绿 + 测试与用户数据彻底隔离（2026-09-16 第二轮）

推送到线上后发现 CI 本来就是红的（4 个既有失败）。逐个查明成因并修复，
顺手把一个会反复污染用户数据的卫生问题治本。

### 修掉的 4 个既有失败

| 测试 | 真实成因 | 修复 |
| --- | --- | --- |
| `test_upload_bounded_reads` | `model_connection_routes.py` 先 `await file.read()` 整块读入内存、之后才判 `>10MB` —— 2GB 上传即 2GB 内存峰值（正是该测试守护的 M-01 回归） | 改为 `await file.read(MAX_REFERENCE_AUDIO_BYTES + 1)` 有界读取 |
| `test_step2_reveal_intent` | 项目桩漏了 `target_duration_sec`。它是真实数据库列（`database.py` + 迁移 0015），属**测试桩过时**，不是生产代码问题 | 给测试桩补上该字段（用 `getattr` 改生产代码会掩盖建模错误） |
| `test_pptx_frontend` | 断言写死了历史短语"字幕文件（SRT）"，实际发布文案是"下载字幕 SRT" | 改测试去跟踪**实际发布文案**；用户可见文案随设计稿走，不为迁就测试而改 |
| `test_database_initialization` | **真实缺陷**：迁移对"加列"不幂等（见下） | 见下 |

### 迁移对"加列"不幂等 —— 会让应用完全无法启动

`_known_migration_already_present()` 只为迁移 1-13 写了"识别既有 schema"的规则，
**14、15 缺失**。于是当数据库已经是完整 schema 但没有 ledger 记录时
（由 `Base.metadata.create_all()` 建成，或来自更新的快照/备份），0014/0015 会对
已存在的列再执行 `ALTER TABLE ... ADD COLUMN`，报 duplicate column name，
`init_db()` 直接失败。

实测确认这与并发无关：**`create_all` 之后单线程 `init_db()` 同样失败**，空库则正常。

修复采用通用且精准的方式：只对 `ALTER TABLE ... ADD COLUMN` 且错误为
`duplicate column name` 的语句放行（并记录日志），其它任何语句或错误照常上抛。
这样未来新增的加列迁移不需要再补一条硬编码规则。

> 踩坑记录：`_split_sql_statements` 会把语句前的 `--` 注释行一起带进语句开头，
> 第一版正则因此不匹配、修复无效。已加 `_statement_head()` 先剥前导注释，
> 并补了针对性回归测试（含注释前缀的用例）。

### 测试不再污染用户真实数据（治本）

**问题**：`checks/` 下的用例直接使用 `database.SessionLocal` 与运行时项目目录，
所以每跑一次全量测试都会往用户真实的 `data/projects.db` 灌入约 15-30 个测试项目，
并在 `runs/` 留下无数据库记录的孤儿目录。本轮验证期间实测单次新增 60 个项目。

**修复**：

- `database.py` 支持 `PPT_STUDIO_DB_PATH`；`repository_paths.py` 支持
  `PPT_STUDIO_RUNS_DIR`（都只在显式设置时生效，生产默认行为不变）。
- 新增 `checks/conftest.py`：在任何测试模块导入 `database` 之前，把这两个变量
  指向会话级临时目录，并 `init_db()` 建出与真实库一致的结构
  （schema + 默认设置 + 默认账号 —— 迁移 0012 会插入 `default` 账号，
  所以按账号过滤的接口不会因此 404）。
- `checks/test_repository_paths.py` 的 canonical 守卫同步更新：既断言注册表源码里
  仍只声明一次规范默认值，也断言运行时值等于被覆盖的值。

**验证**：连续多轮 `python scripts/run_checks.py --level full` 之后，
真实库保持 `projects=50 / runs_dirs=50 / 孤儿=0`（与基线一致），零污染。

### 顺带修掉的 CI 日志噪音

`checks/test_video_render_components.py` 与 `test_video_job_idempotency.py` 的
`NoopThread` 桩替换了全局 `threading.Thread`，被登记进 `concurrent.futures` 的
全局线程表，进程退出时 `_python_exit` 调用 `join()` 失败，在 CI 日志里留下
`NoopThread has no attribute 'join'` 的 traceback。给桩补上 `join()` 后消失。

### 最终验证结果

```text
python scripts/run_checks.py --level full   ->  exit 0，All requested checks passed
全量 pytest                                  ->  956 passed，0 failed（此前 950/4）
Remotion TypeScript（npx tsc --noEmit）      ->  exit 0
CI 日志噪音                                  ->  无
真实数据污染                                  ->  零（projects=50 / runs_dirs=50 / 孤儿=0）
```
