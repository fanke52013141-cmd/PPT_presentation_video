# PPT Presentation Video

本项目把文章转换为手绘 PPT 风格讲解视频，提供本地 Web 界面完成分镜、图片、Mask、旁白、音频和视频渲染。

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

1. 导入文章。
2. 生成并编辑分镜规划。
3. 为每页生成或上传完整图片。
4. 可选地为页面内容涂抹 Mask。
5. 编辑旁白、生成音频并试听确认。
6. 渲染、下载和删除视频。

### 用户步骤与内部 API 步骤映射

用户界面现在固定为 6 个可见步骤，但后端和历史检查脚本仍保留内部 Step 编号。维护时按下表对齐口径：

| 用户可见步骤 | 内部 API / 产物阶段 | 主要产物 |
| --- | --- | --- |
| Step 1 导入文章 | Step 1 import | `inputs/article.md`, `planning/article_brief.json` |
| Step 2 分镜规划 | Step 2 storyboard / visual contract | `planning/visual_contract.json` |
| Step 3 图片生成/上传 | Step 3 images + Step 4 image confirmation | `slides/<slide_id>/visual_draft.png`, `reveal_manifest.json` |
| Step 4 Mask | Step 5 reveal manifest / mask assets | `reveal_manifest.json`, reveal layer assets |
| Step 5 旁白与音频 | Step 6 narration + Step 7 TTS/audio confirmation | `planning/narration_beats.json`, `voice.mp3`, subtitles/timelines |
| Step 6 视频渲染 | Step 8 Remotion render | `remotion_props.json`, rendered video + `.render.json` sidecar |

文档、检查脚本和代码注释中如出现 Step 5/6/7/8，默认指内部 API 编号；面向用户的说明应优先使用 6 步流程。

## 当前 Mask 渲染规则

生产管线固定为 `manual_mask_boundary_white_v4`：

- 没有 Mask：直接显示完整图片。
- 图片生成提示词强制要求外围背景为纯白色。
- 有 Mask：每个涂抹区域就是一个语块的处理边界；只清除从该边界向内连通的纯白/近白背景。
- 图像内部被内容包围的白色不会被抠除。
- 非白色内容按原图保留；边缘只做少量抗锯齿透明度和白边去色。
- 不使用原图作为背景。
- 不执行自动扩边、前景缩边、最近区域分配、语义分割或跨组擦除。
- Mask 页面只显示原图和彩色涂抹区域，不显示覆盖率、红色诊断或额外预览。
- 每次渲染前都会清理并重建 Reveal 与 Remotion 运行时素材。

生产构建顺序：

```text
visual_draft.png
-> reveal_manifest.json（可选手动 Mask）
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
                           外围白底与手动 Mask 构建器
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

### 安全模式说明

默认模式面向本机开发和本地使用。若把服务暴露到局域网或公网，必须开启运行时访问控制和密钥脱敏：

```bash
export PPT_STUDIO_ACCESS_TOKEN="replace-with-long-random-token"
export PPT_STUDIO_MASK_SETTINGS_SECRETS=1
export PPT_STUDIO_ALLOWED_ORIGINS="http://127.0.0.1:8000,http://localhost:8000"
python server.py
```

访问控制在应用启动时加载；密钥脱敏由 `/api/settings` 源码路径处理。历史 runtime bridge 迁移计划见 `docs/runtime_hotfixes_and_security.md` 和 issue #7。

## 验证

CI 自动检查：

pull request 到 `main` 时会运行 `.github/workflows/ci.yml` 中的低依赖检查：

```powershell
python -m compileall -q server.py scripts checks
node --check static\app.js
node --check static\flow.js
node checks\test_visible_flow.js
python scripts\check_runtime_hotfixes.py
$env:PPT_STUDIO_MASK_SETTINGS_SECRETS = "1"; python scripts\check_runtime_settings_mask.py
```

这些检查不需要 LLM、生图、TTS API key，也不会执行真实 Remotion 渲染。

本地基础检查和手动 smoke 验证：

```powershell
.\.venv\Scripts\python.exe -m compileall -q server.py scripts checks
node --check static\app.js
node --check static\flow.js
node checks\test_visible_flow.js
node checks\test_frontend_quality.js
.\.venv\Scripts\python.exe checks\test_source_hardening.py
.\.venv\Scripts\python.exe checks\test_generalized_settings.py
.\.venv\Scripts\python.exe checks\test_subtitle_style.py
.\.venv\Scripts\python.exe checks\test_reveal_mask_integrity.py
.\.venv\Scripts\python.exe checks\test_reveal_pipeline_isolation.py
.\.venv\Scripts\python.exe checks\test_slide_visual_invalidation.py
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

- `sitecustomize.py`、`usercustomize.py`、`runtime_security.py` 和 `runtime_settings_mask.py` 是临时 runtime bridge，不应继续扩大职责。
- 新修复优先落在 `server.py`、`static/**` 或正常启动路径中；只有无法安全改大文件时才使用 runtime bridge。
- 已合并且相对 `main` 没有 ahead commits 的临时分支可以清理。
- `scripts/remotion` 已提交 `package-lock.json`；可复现验证应使用 `npm ci`。
