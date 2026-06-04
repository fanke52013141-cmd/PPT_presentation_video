# 视频预览审核清单

审核对象：

- `preview.mp4` 或 `rough_cut.mp4`
- `subtitles.srt`
- `audio_timeline.json`
- `animation_timeline.json`

输出：`qa_log.md`

检查项：

- 语音是否自然？
- 字幕是否准确且不遮挡主体？
- 动画是否跟随旁白？
- 页面节奏是否过快或过慢？
- 是否有黑屏、静音、资源缺失？
- 总时长是否在 3 到 6 分钟？

路由：

- `revise_audio`: 回到 TTS。
- `revise_animation`: 回到动画绑定。
- `revise_scene`: 回到元素重建。
- `revise_slide`: 回到分镜规划。

