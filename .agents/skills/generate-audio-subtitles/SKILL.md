---
name: generate-audio-subtitles
description: Generate MiniMax TTS audio, metadata, subtitles, and audio timeline from narration text.
---

# Purpose

用 MiniMax TTS 为每页旁白生成语音，并产出字幕和时间轴，供动画绑定使用。

# Inputs

```json
{
  "narration_path": "runs/<run_id>/slides/slide_xxx/narration.txt",
  "task_config_path": "config/task.yaml",
  "env": {
    "MINIMAX_API_KEY": "required",
    "MINIMAX_TTS_ENDPOINT": "optional",
    "MINIMAX_TTS_MODEL": "optional",
    "MINIMAX_TTS_VOICE_ID": "optional"
  }
}
```

# Outputs

```json
{
  "voice_path": "runs/<run_id>/slides/slide_xxx/voice.mp3",
  "audio_meta_path": "runs/<run_id>/slides/slide_xxx/audio_meta.json",
  "subtitles_path": "runs/<run_id>/slides/slide_xxx/subtitles.srt",
  "audio_timeline_path": "runs/<run_id>/slides/slide_xxx/audio_timeline.json"
}
```

# Procedure

1. 读取 `narration.txt`。
2. 检查文本长度，单次请求不超过 MiniMax HTTP T2A 限制。
3. 调用 `scripts/minimax_tts.py`。
4. 保存语音、MiniMax 响应摘要、字幕和时间轴。
5. 若没有官方字幕时间戳，则按句子和音频总长生成近似 `audio_timeline.json`，并标记 `timing_source: estimated`。

# Command

```powershell
python scripts/minimax_tts.py `
  --text-file runs/<run_id>/slides/slide_xxx/narration.txt `
  --out-audio runs/<run_id>/slides/slide_xxx/voice.mp3 `
  --out-meta runs/<run_id>/slides/slide_xxx/audio_meta.json `
  --out-srt runs/<run_id>/slides/slide_xxx/subtitles.srt `
  --out-timeline runs/<run_id>/slides/slide_xxx/audio_timeline.json
```

# Validation

- `voice.mp3` 必须存在且非空。
- `audio_timeline.json` 必须包含 `segments[]`。
- 字幕文本必须和旁白基本一致。
- 语音时长应接近 `slide_spec.duration_sec`。

# Failure Handling

- API 报错时记录 `trace_id`、HTTP 状态码和响应体。
- 旁白过长时拆成多段，分别合成后再用 FFmpeg 合并。
- 音色不合适时只调整 MiniMax 配置，不改文案。

# Bad Case Tags

- `tts-error`
- `audio-timing-weak`
- `missing-input`

