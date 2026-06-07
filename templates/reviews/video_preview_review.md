# 视频预览审核清单

审核对象：

- 每页 `runs/<run_id>/slides/slide_xxx/preview.mp4`
- 整片 `runs/<run_id>/video/rough_cut.mp4`
- 每页 `subtitles.srt`
- 每页 `audio_timeline.json`
- 每页 `animation_timeline.json`
- `runs/<run_id>/logs/render_log.md`

输出：

- `runs/<run_id>/logs/qa_log.md`

## 检查项

- 语音是否自然，是否有明显机械感、怪异停顿或不合适语气标签？
- 字幕是否准确，是否和语音内容一致？
- 字幕是否保持单行显示？
- 字幕是否居中靠下，且不遮挡开放内容区主体信息？
- 字幕中是否没有出现 TTS 控制标签，例如停顿标记或语气标签？
- 动画是否跟随旁白，不提前暴露重点信息？
- 页面节奏是否过快或过慢？
- 是否有黑屏、静音、花屏、资源缺失或图片丢失？
- 是否有音画不同步、字幕不同步或动画不同步？
- 标题、副标题、正文是否清晰可读？
- 底部字幕安全区内是否只出现视频字幕，没有 PPT 内容或装饰元素？
- `rough_cut.mp4` 是否已生成并通过审核后，才进入 `final.mp4` 导出？

## QA Log 要求

`qa_log.md` 必须记录：

- `review_target`: 审核对象，例如 `rough_cut.mp4`。
- `review_status`: `approved`、`revise_audio`、`revise_animation`、`revise_scene` 或 `revise_slide`。
- `summary`: 整体判断。
- `checks`: 每项检查结果。
- `issues`: 具体问题列表。
- `requested_changes`: 需要回退修改的动作。

每个问题必须尽量标明：

- `slide_id`
- 问题类型
- 需要回退的 stage
- 具体修改建议

## 状态路由

- `approved`: 进入最终导出。
- `revise_audio`: 回到 `generate-audio-subtitles`。
- `revise_animation`: 回到 `bind-animation-timeline`。
- `revise_scene`: 回到 `reconstruct-scenes` 或 `render-element-previews`。
- `revise_slide`: 回到 `plan-slides`。

## 示例

```md
# QA Log

## Review Target

- rough_cut: runs/demo/video/rough_cut.mp4
- review_status: revise_animation

## Summary

整体内容可用，但第 3 页右侧流程箭头提前出现，和旁白不同步。

## Checks

- voice_naturalness: pass
- subtitle_accuracy: pass
- subtitle_single_line: pass
- subtitle_not_blocking_content: pass
- subtitle_has_no_tts_markup: pass
- animation_sync: fail
- black_frame: pass
- missing_assets: pass
- audio_video_sync: pass

## Issues

1. slide_003：右侧流程箭头在旁白提到之前提前出现。

## Requested Changes

- slide_003 回到 `bind-animation-timeline`，重新绑定箭头和步骤卡片出现时间。
```
