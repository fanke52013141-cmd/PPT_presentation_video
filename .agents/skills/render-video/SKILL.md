---
name: render-video
description: Render slide previews and final video with Remotion, using FFmpeg for media processing.
---

# Purpose

把每页的 `scene.json`、`animation_timeline.json`、`voice.mp3`、`audio_timeline.json` 和 `subtitles.srt` 合成为可播放视频。Remotion 是主渲染层，FFmpeg 是媒体处理层。

本阶段包含两层：

1. 逐页渲染 `preview.mp4`，用于定位单页问题。
2. 全片合成 `rough_cut.mp4` 和 `final.mp4`。

# Inputs

```json
{
  "run_manifest_path": "runs/<run_id>/run_manifest.yaml",
  "slides_dir": "runs/<run_id>/slides",
  "remotion_project_dir": "scripts/remotion",
  "ffmpeg": "system path"
}
```

# Required Per-slide Files

每页必须包含：

- `scene.json`
- `animation_timeline.json`
- `voice.mp3`
- `audio_timeline.json`
- `subtitles.srt`

缺少任何一个文件，都不能进入该页视频渲染。

# Outputs

```json
{
  "slide_preview_paths": "runs/<run_id>/slides/slide_xxx/preview.mp4",
  "rough_cut_path": "runs/<run_id>/video/rough_cut.mp4",
  "final_video_path": "runs/<run_id>/video/final.mp4",
  "render_log_path": "runs/<run_id>/logs/render_log.md"
}
```

# Output Meaning

- `preview.mp4`: 单页视频预览，用于 Review Gate 3 前的逐页检查。
- `rough_cut.mp4`: 所有 slide 合成后的整片粗剪版本。
- `final.mp4`: 最终导出的 16:9 成片。
- `render_log.md`: 全局视频渲染日志，记录资源路径、渲染命令、错误、抽帧检查结果和 FFmpeg 输出。

# Procedure

1. 读取 `run_manifest.yaml`，确认 run_id、分辨率、fps 和 slide 顺序。
2. 检查每页必需文件：`scene.json`、`animation_timeline.json`、`voice.mp3`、`audio_timeline.json`、`subtitles.srt`。
3. 把运行期图片、手绘素材、音频和字幕复制到 `scripts/remotion/public/runtime/<run_id>/`。
4. Remotion 组件内只使用 `staticFile()` 引用运行期资源，不直接使用 `file:///` 本地路径。
5. 先渲染结构版或短预览，确认资源路径、画面非黑屏、字幕区不被内容占用。
6. 逐页渲染 `preview.mp4`。
7. 对每页 `preview.mp4` 抽帧检查画面、字幕、音画同步和黑屏问题。
8. 所有单页预览可用后，渲染整片 `rough_cut.mp4`。
9. Review Gate 3 通过后，再导出或转码为 `final.mp4`。
10. 用 FFmpeg 做必要的媒体合并、转码、压缩和抽帧检查。

# Validation

- 视频分辨率为 1920x1080。
- 帧率符合 `config/task.yaml`。
- 不设置固定总时长要求。视频时长由文章内容、slide 数量和真实 TTS 音频决定。
- 每页 `preview.mp4` 必须有视频轨和音频轨。
- `rough_cut.mp4` 必须在 `final.mp4` 之前生成。
- 音频、字幕和动画应与 `audio_timeline.json`、`animation_timeline.json` 对齐。
- 无黑屏、无资源缺失、无文字溢出。
- 用 `ffprobe` 校验视频轨和音频轨。
- 用 `ffmpeg` 抽取至少开头、中段、后段三帧做视觉检查。
- 字幕必须单行显示，居中靠下，不遮挡内容框主体信息。
- 字幕不得包含 TTS 控制标签。
- 底部字幕安全区内只能出现视频字幕，不允许有 PPT 内容或装饰元素。

# Failure Handling

- Remotion 失败时，记录 composition、frame、资源路径和错误信息。
- 如果 Remotion 无法加载 `file:///` 资源，改用 `public/runtime/<run_id>/` 加 `staticFile()`。
- FFmpeg 失败时，记录命令和 stderr。
- 如果某页预览失败，只回退该页，不重做全片。
- 如果页面结构错位，回到 `reconstruct-scenes` 或 `render-element-previews`。
- 如果动画不同步，回到 `bind-animation-timeline`。
- 如果语音或字幕异常，回到 `generate-audio-subtitles`。

# Bad Case Tags

- `render-error`
- `data-break`
- `validation-weak`
- `missing-render-input`
- `black-frame`
- `subtitle-not-single-line`
- `audio-video-desync`
