# PPT Presentation Video

本项目把文章转换为 PPT 风格讲解作品，提供本地 Web 界面完成分镜、图片、Mask、旁白、音频、视频渲染和图片型 PPTX 导出。

## 本地启动

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:PYTHONPATH = (Get-Location).Path
.\.venv\Scripts\python.exe server.py
```

打开 [http://127.0.0.1:8000](http://127.0.0.1:8000)。

也可以使用：

```powershell
.\run_local.ps1
```

## 用户流程

1. 导入文章，或输入话题让 AI 生成文章；文章生成的 System Content 可单独配置。
2. 分别配置“文章➡️slides”和“slides➡️可视化”，再生成并编辑分镜。
3. 配置最终视频背景与图片风格，生成或上传每页完整图片；图片风格支持参考图反推、System Content 生成参考图、手动上传参考图和命名模板。
4. AI 自动拆解画面元素，并用多模态模型关联演讲稿语块、生成彩色 Mask。
5. 编辑旁白、生成音频并试听确认。
6. 在“作品输出”中生成、下载和删除 MP4 视频或图片型 PPTX。

视频渲染和 PPTX 导出任务会写入本机 SQLite。刷新页面不会丢失任务状态；应用异常退出后，未完成的视频任务会显示为“已中断”，可以重新生成。新生成的 MP4、调速 MP4 和 PPTX 都会登记产物记录，并在删除文件时同步清理。

### 用户步骤与内部 API 步骤映射

用户界面现在固定为 6 个可见步骤，但后端和历史检查脚本仍保留内部 Step 编号。维护时按下表对齐口径：

| 用户可见步骤 | 内部 API / 产物阶段 | 主要产物 |
| --- | --- | --- |
| Step 1 导入文章 | Step 1 import | `inputs/article.md`（文章唯一事实来源） |
| Step 2 分镜规划 | Step 2 storyboard / visual contract | `planning/visual_contract.json` |
| Step 3 图片生成/上传 | Step 3 images + Step 4 image confirmation | `slides/<slide_id>/visual_draft.png`, `reveal_manifest.json` |
| Step 4 Mask | Step 5 reveal manifest / mask assets | `reveal_manifest.json`, reveal layer assets |
| Step 5 旁白与音频 | Step 6 narration + Step 7 TTS/audio confirmation | `planning/narration_beats.json`, `voice.mp3`, subtitles/timelines |
| Step 6 作品输出 | Step 8 Remotion render / PPTX export | `remotion_props.json`、视频与 `.render.json`、图片型 `.pptx` |

文档、检查脚本和代码注释中如出现 Step 5/6/7/8，默认指内部 API 编号；面向用户的说明应优先使用 6 步流程。

## 当前 Mask 渲染规则

当前使用 `exact_rle_mask_with_manual_corrections_v5`：自动像素标注为主，手动工具作为兜底：

- 没有 Mask：直接显示完整图片。
- 图片生成提示词强制要求外围背景为纯白色。
- AI 先检测连通像素组件，再结合分镜和演讲稿确定语义锚点；正文、装饰和细小边缘组件会确定性归入最近的旁白语块。
- 自动标注写入精确 `row_runs_v1` RLE；每个像素只能属于一个语块，质量门禁要求覆盖率至少 99.5%、零未分配组件、零跨组重叠。
- 图像内部被内容包围的白色不会被抠除。
- 非白色内容按原图保留；边缘只做少量抗锯齿透明度和白边去色。
- 不使用原图作为背景。
- Reveal 构建阶段直接消费精确 RLE，并在其上按顺序应用手动画笔或橡皮修正。
- Mask 页面默认展示自动结果，同时保留添加语块、画笔、橡皮、删除和清除当前页作为人工兜底。
- 每次渲染前都会清理并重建 Reveal 与 Remotion 运行时素材。

生产构建顺序：

```text
visual_draft.png
-> 自动元素检测 + 多模态演讲稿关联
-> reveal_manifest.json（精确 RLE + 可选手动修正 strokes）
-> scripts/build_reveal_scene.py
-> scripts/bind_reveal_timeline.py
-> scripts/build_remotion_props.py
-> Remotion ArticleVideo
```

## 主要目录

```text
server.py                  FastAPI 后端
static/                    本地 Web 前端
scripts/build_reveal_scene.py
                           外围白底与兼容 Mask strokes 构建器
scripts/bind_reveal_timeline.py
                           将 Reveal 事件绑定到音频时间
scripts/build_remotion_props.py
                           生成 Remotion 配置并复制运行时素材
scripts/remotion/          Remotion 视频工程
checks/                    回归检查
runs/                      本地项目运行数据，不提交
outputs/                   本地交付文件，不提交
```

## 系统设置

界面支持配置：

- 文本模型 Base URL、API Key、模型、温度和最大 Token。
- 生图 Base URL、API Key、模型和图片尺寸。
- MiniMax TTS 地址、API Key、模型、音色、语速、音量和音调。
- 图片生成页可设置最终视频背景色，默认 `#FEFDF9`。

设置保存在本机数据库中。不要把真实凭据写入 Git。

Step 3 的原生生图、候选图应用和本地上传都会写入逐页 `visual_provenance.json`。
生产校验默认接受 `codex_image_gen` 和 `openai_compatible`；如发布规范不同，可通过
`PPT_STUDIO_PRODUCTION_IMAGE_PROVIDERS` 或重复传入 `--allowed-image-provider` 明确配置。
日常渲染默认也要求逐页 provenance 完整，允许范围可用 `PPT_STUDIO_RENDER_IMAGE_PROVIDERS` 调整；
历史图片缺少 provenance 时需要在 Step 3 重新生成或重新上传，系统不会伪造来源记录。

### 安全模式说明

默认模式面向本机开发和本地使用。若把服务暴露到局域网或公网，必须开启运行时访问控制和密钥脱敏：

```bash
export PPT_STUDIO_ACCESS_TOKEN="replace-with-long-random-token"
export PPT_STUDIO_ALLOWED_ORIGINS="https://studio.example.com"
export PPT_STUDIO_ALLOWED_HOSTS="studio.example.com"
python server.py
```

默认仅允许同源浏览器访问，跨域来源必须显式加入白名单；浏览器写请求还必须携带应用专用请求头。`/api/settings` 和普通配置导出默认隐藏密钥，只有带明确确认值的独立 POST 接口可以导出密钥。历史 runtime bridge 迁移计划见 `docs/runtime_hotfixes_and_security.md` 和 issue #7。

## 数据库迁移与下游失效

- 正常启动由 `database_migrations.py` 依次执行 `migrations/NNNN_name.sql`，不再使用 `create_all` 或启动时手写 `ALTER TABLE` 维护生产库。
- 每个迁移的编号、名称、SHA-256 和执行时间会写入 `schema_migrations`；迁移失败时 SQL 与版本记录一起回滚。
- 已发布的迁移文件不可修改。新增数据库结构时继续添加连续编号的 SQL 文件；checksum 不一致或数据库含有当前代码未知的版本时，应用会拒绝启动。
- 旧版两列迁移标记表会按实际表和字段安全接管，不重复创建已有结构，也不删除项目数据。
- 编辑文章、分镜、图片、Mask、旁白、字幕样式或视频背景后的派生文件清理与步骤降级，由 `invalidation_service.py` 统一决定。服务本身不提交数据库，API 路由在文件与状态更新成功后只提交一次。

## 验证

CI 自动检查：

pull request 到 `main` 时会运行 `.github/workflows/ci.yml`，其执行 canonical 入口：

```powershell
python scripts\run_checks.py --level full
```

并在 `scripts/remotion` 下运行 `npx tsc --noEmit -p tsconfig.json`。`run_checks.py` 依次执行 compileall、所有 `node --check`、`checks/*.js`、独立检查脚本（`test_source_hardening.py`、`check_source_registration_contract.py`、`check_python_startup_hooks.py`、`check_runtime_hotfixes.py`、`check_static_extension_references.py` 等）和全部 pytest。

这些检查不需要 LLM、生图、TTS API key，也不会执行真实 Remotion 渲染。

本地基础检查和手动 smoke 验证：

完整检查入口统一为 `scripts\run_checks.py --level full`（与 CI 一致）。以下是最常用的一批，便于快速迭代：

```powershell
.\.venv\Scripts\python.exe -m compileall -q server.py scripts checks
node --check static\workflow_state.js
node --check static\workflow_state.js
node --check static\flow.js
node checks\test_visible_flow.js
node checks\test_frontend_quality.js
.\.venv\Scripts\python.exe checks\test_source_hardening.py
.\.venv\Scripts\python.exe checks\test_generalized_settings.py
.\.venv\Scripts\python.exe checks\test_subtitle_style.py
.\.venv\Scripts\python.exe checks\test_reveal_mask_integrity.py
.\.venv\Scripts\python.exe checks\test_reveal_pipeline_isolation.py
.\.venv\Scripts\python.exe checks\test_slide_visual_invalidation.py
.\.venv\Scripts\python.exe -m pytest checks\test_database_migrations.py checks\test_invalidation_service.py -q
.\.venv\Scripts\python.exe -m pytest checks\test_source_runtime_safeguards.py -q
.\.venv\Scripts\python.exe checks\test_audio_confirmation.py
.\.venv\Scripts\python.exe checks\test_audio_tail_padding.py
Push-Location scripts\remotion
npm ci
npx tsc --noEmit -p tsconfig.json
Pop-Location
```

验证已有运行项目：

```powershell
.\.venv\Scripts\python.exe scripts\validate_reveal_scene.py `
  --run-dir runs\<run_id> `
  --repo-root .

.\.venv\Scripts\python.exe scripts\validate_run_assets.py `
  --run-dir runs\<run_id> `
  --repo-root . `
  --require-layered
```

## Git 范围

提交应用和可复用代码；不要提交：

- `runs/**`
- `outputs/**`
- `logs/**`
- `data/**`
- 音视频、字幕、API Key 或 `.env`

## 维护注意事项

- `sitecustomize.py` 已删除；Manifest 对齐、子进程超时和校验器 JSON 处理都已迁入正式源码。不得重新引入 Python 自动启动补丁或全局 `subprocess.run` 替换。
- AI Mask 与项目样式的兼容模块仍由正式启动路径显式注册，后续继续按服务边界迁出。
- 新修复优先落在 `server.py`、`static/**` 或正常启动路径中；只有无法安全改大文件时才使用 runtime bridge。
- 已合并且相对 `main` 没有 ahead commits 的临时分支可以清理。
- `scripts/remotion` 已提交 `package-lock.json`；可复现验证应使用 `npm ci`。
