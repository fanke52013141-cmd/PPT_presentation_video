---
name: render-video
description: Render slide previews and final video with Remotion, using FFmpeg for media processing.
---

# Purpose

把 `scene.json`、`animation_timeline.json`、语音和字幕合成为视频。Remotion 是主渲染层，FFmpeg 是媒体处理层。

# Inputs

```json
{
  "run_manifest_path": "runs/<run_id>/run_manifest.yaml",
  "slides_dir": "runs/<run_id>/slides",
  "remotion_project_dir": "scripts/remotion",
  "ffmpeg": "system path"
}
```

# Outputs

```json
{
  "slide_preview_paths": "runs/<run_id>/slides/slide_xxx/preview.mp4",
  "rough_cut_path": "runs/<run_id>/video/rough_cut.mp4",
  "final_video_path": "runs/<run_id>/video/final.mp4",
  "render_log_path": "runs/<run_id>/logs/render_log.md"
}
```

# Procedure

1. 检查每页必需文件：`scene.json`、`animation_timeline.json`、`voice.mp3`。
2. 把运行期图片、背景图和音频复制到 `scripts/remotion/public/runtime/<run_id>/`，Remotion 组件内只用 `staticFile()` 引用资源。
3. 先渲染结构版或短预览，确认资源路径、画面非黑屏、字幕区不被内容占用。
4. 用 Remotion 渲染单页预览，供 Review Gate 3 使用。
5. 单页通过后，渲染整片 rough cut。
6. 用 FFmpeg 合并音频、压缩或转码。
7. 输出最终 16:9 MP4。

# Validation

- 视频分辨率为 1920x1080。
- 帧率符合 `config/task.yaml`。
- 主版本时长在 180 到 360 秒之间；低于 180 秒时回到 `plan-slides` 拆页或补足讲解层次。
- 音频和字幕同步。
- 无黑屏、无资源缺失、无文字溢出。
- 用 `ffprobe` 校验视频轨和音频轨，用 `ffmpeg` 抽取至少开头、中段、后段三帧做视觉检查。
- 字幕必须在底图字幕框内垂直居中；单行和双行字幕都要抽帧检查。

# Failure Handling

- Remotion 失败时，记录 composition、frame、资源路径。
- 如果 Remotion 无法加载 `file:///` 资源，改用 `public/runtime/<run_id>/` 加 `staticFile()`。
- FFmpeg 失败时，记录命令和 stderr。
- 若某页预览失败，只回退该页，不重做全片。

# Bad Case Tags

- `render-error`
- `data-break`
- `validation-weak`

