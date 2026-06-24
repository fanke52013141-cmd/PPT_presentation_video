# Slide Plan Prompt

Read `runs/<run_id>/inputs/article.md` and produce
`runs/<run_id>/planning/slide_plan.json`.

The plan must be narration-first. Each slide needs a voiceover paragraph and a
set of `narration_beats`. These beats drive visual groups and animation later.

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
- Visual groups must be manually maskable: avoid severe overlap, arrow-through-text,
  merged unrelated groups, and tiny dense labels.

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
- `slide_purpose`
- `main_title`
- `subtitle` only when `presentation_policy.subtitle_policy` is `all_slides_have_subtitle`
- `core_message`
- `layout_type`
- `visual_metaphor`
- `composition`
- `content.content_type`
- `content.layout_intent`
- `content.items[]`
- `narration`
- `narration_beats[]`

## Presentation Policy

Before creating slides, make a project-level choice:

```json
{
  "presentation_policy": {
    "subtitle_policy": "all_slides_have_subtitle",
    "subtitle_decided_by": "ai",
    "subtitle_rationale": "Use subtitles when the article benefits from a second explanatory line on every page.",
    "default_visual_group_count": "3-5",
    "layout_diversity": "high"
  }
}
```

Use `all_slides_have_subtitle` only when subtitles clearly improve comprehension
across the whole video. Otherwise use `no_slides_have_subtitle` and give that
space back to the main visual.

## Narration Beats

Each `narration_beats[]` item should include:

- `id`: stable beat id, for example `beat_01`
- `spoken_point`: the sentence or idea spoken in this beat
- `source_article_point`: the source concept from the article
- `visual_group`: the visible group that should support this beat
- `animation`: suggested action, such as `fade_up`, `soft_zoom_in`, or `highlight`
- `time_hint`: rough order hint, such as `early`, `middle`, `late`, or `0-3s`

The narration expands the visible page content. Do not create beats that are
unrelated to what the page will show.

## Planning Rules

- Each slide explains one core idea.
- Use 3-6 narration beats per slide.
- Map every important beat to one visible group.
- Prefer 2-6 semantic visual groups per slide.
- Prefer one dominant hero visual plus supporting groups when it improves expression.
- Do not create extra groups merely to fill the page or satisfy Mask requirements.
- Avoid planning a slide that requires many tiny labels or dense text.
- If a concept needs many steps, split it into multiple slides.
- Keep the subtitle safe zone y=930..1080 completely clear in the visual plan.
- Choose a `layout_type` before defining visual groups.

## Layout Types

Prefer these `layout_type` values:

- `hero_diagram`
- `left_right_comparison`
- `process_flow`
- `cause_effect_chain`
- `central_mindmap`
- `timeline`
- `three_card_framework`
- `problem_solution`
- `pyramid`
- `before_after`
- `metaphor_scene`
- `data_callout`
- `checklist`
- `summary_takeaway`
- `custom`

## Content Types

Prefer these `content.content_type` values:

- `concept_explanation`
- `bullet_list`
- `process_flow`
- `comparison`
- `timeline`
- `cycle`
- `cards`
- `example_breakdown`
- `misconception_correction`
- `cause_effect`
- `framework_map`
- `hierarchy`
- `matrix`
- `checklist`
- `summary_takeaway`
- `custom`

## Example

```json
{
  "presentation_policy": {
    "subtitle_policy": "all_slides_have_subtitle",
    "subtitle_decided_by": "ai",
    "subtitle_rationale": "梯度下降概念较抽象，统一副标题能把主标题转成一句可理解的解释。",
    "default_visual_group_count": "3-5",
    "layout_diversity": "high"
  },
  "topic": {
    "topic_id": "gradient_descent",
    "topic_name": "梯度下降",
    "topic_summary": "梯度下降通过沿负梯度方向迭代更新参数，让损失函数逐步变小。"
  },
  "slides": [
    {
      "slide_id": "slide_001",
      "slide_purpose": "concept_explanation",
      "main_title": "梯度下降",
      "subtitle": "沿着负梯度，一步步走向最低点",
      "core_message": "负梯度指向损失下降最快的方向。",
      "layout_type": "hero_diagram",
      "visual_metaphor": "把优化过程画成一个人沿山坡下山找谷底。",
      "composition": {
        "primary_focus": "valley_diagram",
        "reading_order": "center_then_sides",
        "hierarchy": ["main_title", "valley_diagram", "gradient_card", "negative_gradient_card"],
        "group_count": 4
      },
      "content": {
        "content_type": "concept_explanation",
        "layout_intent": "中间用下山图作为主视觉，左右放梯度和负梯度两个解释卡。",
        "items": [
          {"type": "diagram", "label": "下山找谷底", "text": "沿山坡逐步靠近最低点"},
          {"type": "concept", "label": "梯度", "text": "上升最快方向"},
          {"type": "concept", "label": "负梯度", "text": "下降最快方向"}
        ]
      },
      "narration": "先把梯度下降想象成下山。梯度指向上升最快的方向，而负梯度就是最陡的下坡路。",
      "narration_beats": [
        {
          "id": "beat_01",
          "spoken_point": "先把梯度下降想象成下山。",
          "source_article_point": "生活化比喻：下山找谷底",
          "visual_group": "valley_diagram",
          "animation": "soft_zoom_in",
          "time_hint": "early"
        }
      ]
    }
  ]
}
```
