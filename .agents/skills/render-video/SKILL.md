---
name: render-video
description: Render the validated v3 reveal scenes, confirmed audio, and transparent subtitles with Remotion.
---

# Purpose

使用当前 reveal 场景、已确认音频和字幕渲染最终 MP4。Remotion 只显示 PNG、执行轻量动画、播放音频和绘制字幕，不重绘 PPT 主体。

# Required Sequence

```powershell
python scripts/build_reveal_scene.py --manifest runs/<run_id>/reveal_manifest.json --repo-root .
python scripts/validate_reveal_scene.py --run-dir runs/<run_id> --repo-root .
python scripts/bind_reveal_timeline.py --run-dir runs/<run_id> --lead-sec 0
python scripts/build_remotion_props.py --run-dir runs/<run_id> --repo-root .
```

随后在 `scripts/remotion` 中直接调用 Remotion CLI 渲染 `ArticleVideo`，使用：

- H.264
- `yuv420p`
- BT.709
- 1920×1080
- 项目配置的帧率

# Rendering Rules

- 每页音频必须已生成并由用户确认。
- 音频尾部保留安全余量，避免末字被下一页截断。
- 字幕单行、透明背景、靠近底部但保留安全边距。
- 视频背景色读取图片管理页的项目设置。
- 每次渲染前重建 `public/runtime/<run_id>`。
- MP4 必须生成 `.render.json` sidecar；删除视频时同时删除 sidecar。

# Validation

- `validate_reveal_scene.py` 通过。
- `validate_run_assets.py --require-layered` 通过。
- TypeScript 检查通过。
- `ffprobe` 能识别视频轨和音频轨。
- `validate_render_color.py` 通过 BT.709 检查。
- 抽查开头、中段、结尾帧，无黑屏、缺图、字幕底板或内容截断。
