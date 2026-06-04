---
name: review-visual-drafts
description: Review static visual drafts and decide whether to approve, revise, or reject.
---

# Purpose

对 `visual_draft.png` 做第一轮审核。审核对象是图片，不是 JSON。

# Inputs

```json
{
  "visual_draft_path": "runs/<run_id>/slides/slide_xxx/visual_draft.png",
  "slide_spec_path": "runs/<run_id>/slides/slide_xxx/slide_spec.json",
  "narration_path": "runs/<run_id>/slides/slide_xxx/narration.txt",
  "review_template_path": "templates/reviews/static_visual_review.md"
}
```

# Outputs

```json
{
  "visual_review_path": "runs/<run_id>/slides/slide_xxx/visual_review.yaml"
}
```

`visual_review.yaml` 必须包含：

- `slide_id`
- `status`: `approved | revise | rejected`
- `reviewer_notes[]`
- `requested_changes[]`

# Procedure

1. 检查画面是否符合本页核心观点。
2. 检查风格是否符合 AI 科普视频。
3. 检查构图是否留出文字区域。
4. 检查是否适合拆解为可动画元素。
5. 写出明确状态和修改意见。

# Routing

- `approved`: 进入 `reconstruct-scenes`。
- `revise`: 回到 `generate-visual-drafts`。
- `rejected`: 回到 `plan-slides` 或 `define-style`。

# Bad Case Tags

- `validation-weak`
- `visual-style-drift`
- `not-animation-friendly`

