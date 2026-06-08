---
name: generate-audio-subtitles
description: Generate MiniMax TTS audio, metadata, subtitles, and audio timeline from slide narration.
---

# Purpose

用 MiniMax TTS 为每页旁白生成语音，并产出字幕和时间轴，供动画绑定使用。

本阶段逐页执行。每次从 `slide_plan.json` 中读取当前 `slide_id` 的 `narration`，生成一版适合语音合成的 `tts_text.txt`，再调用 MiniMax。

# Inputs

```json
{
  "slide_plan_path": "runs/<run_id>/planning/slide_plan.json",
  "slide_id": "slide_xxx",
  "task_config_path": "config/task.yaml",
  "env": {
    "MINIMAX_API_KEY": "required",
    "MINIMAX_TTS_ENDPOINT": "optional",
    "MINIMAX_TTS_MODEL": "optional",
    "MINIMAX_TTS_VOICE_ID": "optional",
    "MINIMAX_TTS_EMOTION": "optional"
  }
}
```

# Outputs

```json
{
  "narration_path": "runs/<run_id>/slides/slide_xxx/narration.txt",
  "tts_text_path": "runs/<run_id>/slides/slide_xxx/tts_text.txt",
  "voice_path": "runs/<run_id>/slides/slide_xxx/voice.mp3",
  "audio_meta_path": "runs/<run_id>/slides/slide_xxx/audio_meta.json",
  "subtitles_path": "runs/<run_id>/slides/slide_xxx/subtitles.srt",
  "audio_timeline_path": "runs/<run_id>/slides/slide_xxx/audio_timeline.json"
}
```

`narration.txt` 是从 `slide_plan.json` 导出的原始旁白副本。`tts_text.txt` 是加入少量停顿和语气标签后的 TTS 输入文本。字幕和时间轴必须基于清洗后的原始旁白，不显示 MiniMax 控制标签。

# MiniMax Markup Rules

MiniMax 支持在文本中插入停顿标记 `<#x#>`。`speech-2.8-hd` 和 `speech-2.8-turbo` 也支持少量语气词标签。

## 停顿规则

- 只在有必要时使用停顿，不为了“拟真”到处加停顿。
- 停顿只能放在两个可发音文本之间。
- 禁止在整段文本开头或结尾放停顿。
- 禁止在一句话开头或结尾放停顿。
- 禁止连续使用多个停顿标记。
- 常用停顿：`<#0.25#>`、`<#0.4#>`、`<#0.6#>`、`<#0.8#>`。
- 一般不要超过 `1.0` 秒；除非是明显的段落转场。

适合加停顿的位置：

- 开场问题之后。
- 从现象切到解释之前。
- 举例之前。
- 关键结论之前。
- 对比关系中间。
- 总结句之前。

## 语气标签规则

本项目默认只允许少数自然讲解标签：

- `(breath)`：自然换气。只用于长解释中间，避免机械连读。
- `(emm)`：轻微思考。只在引出类比或口语化转折时使用。
- `(chuckle)`：轻笑。只在非常轻松的例子或温和纠错时使用。
- `(laughs)`：笑声。极少使用，默认不用。
- `(sighs)`：轻叹。只在讲常见困惑、踩坑或误区时使用。

其它拟声、生理声或强表演标签默认不使用。

限制：

- 每页默认 0 到 2 个语气标签即可。
- 不要每页都使用语气标签。
- 不要在文本开头或结尾放语气标签。
- 语气标签不能替代真实内容表达。

## Emotion 参数

- 默认 `emotion` 使用 `calm`。
- 可以根据页面局部语境改为 `happy` 或 `surprised`，但不要滥用。
- 默认不要使用 `angry`、`fearful`、`disgusted`、`sad`。
- 不使用 `whisper`，避免科普旁白不清楚。

# Procedure

1. 读取 `slide_plan.json`，定位当前 `slide_id`。
2. 提取当前 slide 的 `narration`。
3. 保存原始旁白到 `narration.txt`。
4. 根据本 Skill 的停顿和语气标签规则，生成 `tts_text.txt`。
5. 校验 `tts_text.txt`：不得以停顿或语气标签开头/结尾，不得连续停顿，不得滥用语气标签。
6. 调用 `scripts/minimax_tts.py`。
7. 保存语音、MiniMax 响应摘要、字幕和时间轴。
8. 字幕和 `audio_timeline.json` 必须清洗掉 `<#x#>` 和语气标签。
9. 若没有官方字幕时间戳，则按字幕分段和音频总长生成近似 `audio_timeline.json`，并标记 `timing_source: estimated`。
10. 默认 endpoint 使用 `https://api.minimaxi.com/v1/t2a_v2`，备用接口为 `https://api-bj.minimaxi.com/v1/t2a_v2`。

# Encoding Rules

- 中文 `slide_plan.json`、`narration.txt`、`tts_text.txt` 必须以 UTF-8 写入。
- Windows/PowerShell 下不要用 here-string 管道把中文脚本传给 Python 再写文件；这会把中文降级成 `?`。如需批量写中文文件，使用 PowerShell/.NET `UTF8Encoding($false)` 或已有结构化脚本。
- 调用 TTS 前必须抽查 `narration.txt` 和 `tts_text.txt`，不得包含连续 `??`，也不得把大段中文变成 `?`。

# Command

```powershell
python scripts/minimax_tts.py `
  --text-file runs/<run_id>/slides/slide_xxx/tts_text.txt `
  --subtitle-text-file runs/<run_id>/slides/slide_xxx/narration.txt `
  --slide-id slide_xxx `
  --emotion calm `
  --out-tts-text runs/<run_id>/slides/slide_xxx/tts_text.normalized.txt `
  --out-audio runs/<run_id>/slides/slide_xxx/voice.mp3 `
  --out-meta runs/<run_id>/slides/slide_xxx/audio_meta.json `
  --out-srt runs/<run_id>/slides/slide_xxx/subtitles.srt `
  --out-timeline runs/<run_id>/slides/slide_xxx/audio_timeline.json
```

# Validation

- `narration.txt` 必须和 `slide_plan.json` 当前 slide 的 `narration` 一致。
- `tts_text.txt` 可以包含少量 `<#x#>` 和允许的语气标签。
- `tts_text.txt` 不得以停顿标记或语气标签开头/结尾。
- `tts_text.txt` 不得连续使用停顿标记。
- 字幕文本不得包含 `<#x#>` 或语气标签。
- 字幕文本不得出现编码损坏：禁止只有 `?` 的字幕段，禁止连续 `??`。
- `voice.mp3` 必须存在且非空。
- `audio_timeline.json` 必须包含 `segments[]`。
- 每条字幕默认不超过 28 个中文字符，且最大 1 行。

# Failure Handling

- API 报错时记录 `trace_id`、HTTP 状态码和响应体。
- 旁白过长时拆成多段，分别合成后再用 FFmpeg 合并。
- 音色不合适时只调整 MiniMax 配置，不改文案。
- 如果语气标签导致效果怪异，优先删除语气标签，只保留必要停顿。
- 如果停顿显得不自然，减少停顿数量，不增加更长停顿。

# Bad Case Tags

- `tts-error`
- `audio-timing-weak`
- `missing-input`
- `tts-markup-overused`
- `pause-at-boundary`
- `subtitle-has-tts-markup`
- `subtitle-encoding-damaged`
