# Slide Plan Prompt

Read `runs/<run_id>/inputs/article.md` and produce
`runs/<run_id>/planning/slide_plan.json`.

The plan must be narration-first. Do not over-structure the page. The only fixed
content structure is: main title, AI project-level subtitle policy, and body
content / narration.

## Production Invariants

These rules are not style choices and must never be changed by a style profile:

- Every slide must have one clear `main_title`.
- Decide subtitle usage once at the project level in `presentation_policy.subtitle_policy`.
- `subtitle_policy` must be either:
  - `all_slides_have_subtitle`
  - `no_slides_have_subtitle`
- If `all_slides_have_subtitle`, every slide must include a non-empty `subtitle`.
- If `no_slides_have_subtitle`, no slide should include a subtitle.
- Generated slide images use a pure-white `#FFFFFF` background.
- The visual plan must keep y=930..1080 completely empty for video subtitles.
- The final image must remain manually maskable, but Mask convenience must not force a rigid block layout.

## Output Schema

The JSON must conform to `schemas/slide_plan.schema.json` and be compatible with
`schemas/visual_contract.schema.json`.

Required top-level fields:

- `presentation_policy.subtitle_policy`
- `presentation_policy.subtitle_rationale`
- `topic.topic_id`
- `topic.topic_name`
- `topic.topic_summary`
- `slides[]`

Each slide must include:

- `slide_id`
- `main_title`
- `subtitle` only when `presentation_policy.subtitle_policy` is `all_slides_have_subtitle`
- `core_message`
- `body_content[]`
- `visual_intent`
- `narration`

Optional fields:

- `narration_beats[]`
- `visual_groups[]`

`visual_groups[]` are post-design visual anchors for Mask/Reveal review. They
are not a pre-generation layout template.

## Presentation Policy

Before creating slides, make a project-level subtitle choice:

```json
{
  "presentation_policy": {
    "subtitle_policy": "all_slides_have_subtitle",
    "subtitle_decided_by": "ai",
    "subtitle_rationale": "Use subtitles when the article benefits from a second explanatory line on every page.",
    "default_visual_anchor_count": "2-5",
    "layout_freedom": "high"
  }
}
```

Use `all_slides_have_subtitle` only when subtitles clearly improve comprehension
across the whole video. Otherwise use `no_slides_have_subtitle` and give that
space back to the main visual.

## Narration Beats

`narration_beats[]` are optional rhythm hints. They may include:

- `id`: stable beat id, for example `beat_01`
- `spoken_point`: the sentence or idea spoken in this beat
- `source_article_point`: the source concept from the article
- `visual_group`: optional post-design anchor name
- `animation`: suggested action, such as `fade_up`, `soft_zoom_in`, or `highlight`
- `time_hint`: rough order hint, such as `early`, `middle`, `late`, or `0-3s`

Do not create beats merely to cover every visual group. The narration is the
source of truth; visual anchors are matched after the page is drawn.

## Planning Rules

- Each slide explains one core idea.
- Keep the plan simple: main title, optional project-wide subtitle, body content, narration.
- Do not classify content as diagram/data/summary/quote/process/etc. during planning.
- Put everything besides title/subtitle into `body_content`.
- Use `visual_intent` to describe the desired meaning or feel, not exact coordinates or blocks.
- Let the image generation stage decide whether body content becomes a scene, diagram, card, timeline, icon set, metaphor, or mixed layout.
- If you provide `visual_groups`, keep them as 2-5 loose anchors for later Mask/Reveal review.
- Keep y=930..1080 completely clear.

## Example

```json
{
  "presentation_policy": {
    "subtitle_policy": "all_slides_have_subtitle",
    "subtitle_decided_by": "ai",
    "subtitle_rationale": "梯度下降概念较抽象，统一副标题能把主标题转成一句可理解的解释。",
    "default_visual_anchor_count": "2-4",
    "layout_freedom": "high"
  },
  "topic": {
    "topic_id": "gradient_descent",
    "topic_name": "梯度下降",
    "topic_summary": "梯度下降通过沿负梯度方向迭代更新参数，让损失函数逐步变小。"
  },
  "slides": [
    {
      "slide_id": "slide_001",
      "main_title": "梯度下降",
      "subtitle": "沿着负梯度，一步步走向最低点",
      "core_message": "负梯度指向损失下降最快的方向。",
      "body_content": [
        "先把梯度下降想象成下山。",
        "梯度指向上升最快的方向。",
        "负梯度就是最陡的下坡路。"
      ],
      "visual_intent": "用一个清晰、亲和的视觉隐喻解释这段演讲稿，让观众一眼理解‘沿下降方向靠近最低点’。",
      "narration": "先把梯度下降想象成下山。梯度指向上升最快的方向，而负梯度就是最陡的下坡路。我们每走一步，就重新判断当前最陡的下降方向，再继续靠近谷底。",
      "narration_beats": [
        {
          "id": "beat_01",
          "spoken_point": "先把梯度下降想象成下山。",
          "source_article_point": "生活化比喻：下山找谷底",
          "time_hint": "early"
        }
      ]
    }
  ]
}
```
