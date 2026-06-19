# PPT Presentation Video

本项目把文章转换为手绘 PPT 风格讲解视频，提供本地 Web 界面完成分镜、图片、Mask、旁白、音频和视频渲染。

## 本地启动

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
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

## 当前 Mask 渲染规则

生产管线固定为 `manual_mask_exact_v2`：

- 没有 Mask：直接显示完整图片。
- 有 Mask：使用固定纯色背景，只复制手动画笔 Mask 内的源图像素。
- 不使用原图作为背景。
- 不执行自动扩边、连通区域扩张、最近区域分配或跨组擦除。
- Mask 页面可以打开“最终抠除预览”，直接查看视频将使用的结果和未覆盖内容。
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

以下脚本仅保留作历史诊断，不进入 Web 生产流程：

- `scripts/auto_fit_reveal_boxes.py`
- `scripts/split_master_layers.py`
- `scripts/decompose_slide_layers.py`
- `scripts/compose_manifest_layers.py`
- `scripts/prepare_full_slide_scenes.py`

## 主要目录

```text
server.py                  FastAPI 后端
static/                    本地 Web 前端
scripts/build_reveal_scene.py
                           精确手动 Mask 构建器
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

设置保存在本机数据库中。不要把真实凭据写入 Git。

## 验证

基础检查：

```powershell
.\.venv\Scripts\python.exe -m compileall -q server.py scripts checks
node --check static\app.js
node --check static\flow.js
node checks\test_visible_flow.js
.\.venv\Scripts\python.exe checks\test_reveal_mask_integrity.py
.\.venv\Scripts\python.exe checks\test_reveal_pipeline_isolation.py
.\.venv\Scripts\python.exe checks\test_slide_visual_invalidation.py
.\.venv\Scripts\python.exe checks\test_audio_confirmation.py
.\.venv\Scripts\python.exe checks\test_audio_tail_padding.py
npx tsc --noEmit -p scripts\remotion\tsconfig.json
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
