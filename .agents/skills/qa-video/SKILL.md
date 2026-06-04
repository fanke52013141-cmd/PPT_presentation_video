---
name: qa-video
description: Review a slide preview or final video and route revisions to the right stage.
---

# Purpose

对视频预览做最终质量检查，并把问题路由回正确阶段，避免笼统地“重新做”。

# Inputs

```json
{
  "video_path": "runs/<run_id>/video/rough_cut.mp4 或 slide preview",
  "qa_checklist_path": "checks/qa_checklist.md",
  "slide_plan_path": "runs/<run_id>/planning/slide_plan.json",
  "subtitles_path": "runs/<run_id>/media/final_subtitles.srt 可选"
}
```

# Outputs

```json
{
  "qa_log_path": "runs/<run_id>/logs/qa_log.md"
}
```

`qa_log.md` 必须包含：

- `status`: `approved | revise_audio | revise_animation | revise_scene | revise_slide`
- `issues[]`
- `route_to_stage`
- `requested_changes[]`

# Procedure

1. 检查画面、语音、字幕、动画、节奏和平台适配。
2. 每个问题都定位到具体 slide 和具体阶段。
3. 如果是语音问题，回到 `generate-audio-subtitles`。
4. 如果是动画时机问题，回到 `bind-animation-timeline`。
5. 如果是画面元素问题，回到 `reconstruct-scenes`。
6. 如果是内容逻辑问题，回到 `plan-slides`。

# Validation

- QA 不能只写“感觉不好”，必须给出可执行修改。
- 成片必须满足 3 到 6 分钟。
- 字幕不能遮挡主体信息。
- B 站、抖音、视频号横屏发布都能接受。

# Failure Handling

- 如果无法判断问题阶段，先标记 `needs_human_decision`。
- 同类问题出现两次，记录 bad case。

# Bad Case Tags

- `validation-weak`
- `animation-mismatch`
- `audio-timing-weak`
- `output-unclear`

