---
name: render-video
description: Render slide previews and final video with Remotion using PNG layers, audio, subtitles, and FFmpeg media processing.
---

# Purpose

把每页的 PNG 图层版 `scene.json`、`animation_timeline.json`、`voice.mp3`、`audio_timeline.json` 和 `subtitles.srt` 合成为可播放视频。

Remotion 的职责只包括：

- 显示 PNG 图层。
- 对 PNG 图层执行轻量动画。
- 播放音频。
- 叠加单行字幕。

Remotion 不负责重新绘制文本、shape、line、group 或复杂图表。FFmpeg 只做媒体合并、转码、压缩和抽帧检查。

本阶段包含两层：

1. 逐页渲染 `preview.mp4`，用于定位单页问题。
2. 全片合成 `rough_cut.mp4` 和 `final.mp4`。

# Inputs

```json
{
  "run_manifest_path": "runs/<run_id>/run_manifest.yaml",
  "slides_dir": "runs/<run_id>/slides",
  "remotion_props_path": "runs/<run_id>/remotion_props.json",
  "remotion_project_dir": "scripts/remotion",
  "ffmpeg": "system path"
}
```

# Required Per-slide Files

每页必须包含：

- `scene.json`，且使用 `layers[]` PNG 图层结构。
- `animation_timeline.json`，且 `events[].target` 指向 `scene.layers[].id`。
- `voice.mp3`
- `audio_timeline.json`
- `subtitles.srt`

缺少任何一个文件，都不能进入该页视频渲染。

# Required Remotion Props

渲染前必须生成：

```text
runs/<run_id>/remotion_props.json
```

该文件是 Remotion 的唯一业务输入，结构必须包含：

```json
{
  "fps": 30,
  "width": 1920,
  "height": 1080,
  "total_duration_sec": 120.0,
  "slides": [
    {
      "slide_id": "slide_001",
      "start_sec": 0,
      "duration_sec": 18.5,
      "scene": {"layers": []},
      "audio_file": "runs/<run_id>/slides/slide_001/voice.mp3",
      "audio_timeline": {"segments": []},
      "animation_timeline": {"events": []}
    }
  ]
}
```

`remotion_props.json` 可以由脚本或 Agent 生成，但生成后必须落盘。它负责把每页 slide 的 scene、音频、字幕时间轴和动画时间轴汇总给 Remotion。

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
3. 校验每页 `scene.json` 使用 `layers[]`，并且每个 layer 是 PNG 资源。
4. 校验每页 `animation_timeline.events[].target` 都存在于 `scene.layers[].id`。
5. 生成或检查 `runs/<run_id>/remotion_props.json`。
6. 确认 `remotion_props.json.slides[]` 已包含每页 scene、audio_file、audio_timeline 和 animation_timeline。
7. 使用 `scripts/render_remotion.ps1` 调用 Remotion，并通过 `--props` 读取 `remotion_props.json`。
8. 先渲染短预览，确认资源路径、画面非黑屏、字幕区不被 PPT 内容占用。
9. 逐页渲染 `preview.mp4`。
10. 对每页 `preview.mp4` 抽帧检查画面、字幕、音画同步和黑屏问题。
11. 所有单页预览可用后，渲染整片 `rough_cut.mp4`。
12. Review Gate 3 通过后，再导出或转码为 `final.mp4`。
13. 用 FFmpeg 做必要的媒体合并、转码、压缩和抽帧检查。

# Validation

- `remotion_props.json` 必须存在且为合法 JSON。
- `remotion_props.json.slides[]` 不能为空。
- 每个 props slide 必须包含 `scene.layers[]`、`audio_file`、`audio_timeline.segments[]` 和 `animation_timeline.events[]`。
- 视频分辨率为 1920x1080。
- 帧率符合 `config/task.yaml`。
- 不设置固定总时长要求。视频时长由文章内容、slide 数量和真实 TTS 音频决定。
- 每页 `preview.mp4` 必须有视频轨和音频轨。
- `rough_cut.mp4` 必须在 `final.mp4` 之前生成。
- 音频、字幕和 PNG 图层动画应与 `audio_timeline.json`、`animation_timeline.json` 对齐。
- 无黑屏、无资源缺失。
- 用 `ffprobe` 校验视频轨和音频轨。
- 用 `ffmpeg` 抽取至少开头、中段、后段三帧做视觉检查。
- 字幕必须单行显示，居中靠下，不遮挡内容框主体信息。
- 字幕不得包含 TTS 控制标签。
- 底部字幕安全区内只能出现视频字幕，不允许有 PPT 内容或装饰元素。

# Failure Handling

- 如果缺少 `remotion_props.json`，先生成该文件，不直接调用 Remotion。
- Remotion 失败时，记录 composition、frame、资源路径和错误信息。
- FFmpeg 失败时，记录命令和 stderr。
- 如果某页预览失败，只回退该页，不重做全片。
- 如果 PNG 图层错位，回到 `reconstruct-scenes` 或 `render-element-previews`。
- 如果动画不同步，回到 `bind-animation-timeline`。
- 如果语音或字幕异常，回到 `generate-audio-subtitles`。

# Bad Case Tags

- `render-error`
- `data-break`
- `validation-weak`
- `missing-render-input`
- `missing-remotion-props`
- `black-frame`
- `subtitle-not-single-line`
- `audio-video-desync`
- `non-png-scene-input`
