# Slide Plan Prompt

Read `runs/<run_id>/inputs/article.md` and produce
`runs/<run_id>/planning/slide_plan.json`.

The plan must be narration-first. Each slide needs a voiceover paragraph and a
set of `narration_beats`. These beats drive the visual groups and animation
timeline later.

## Output Schema

The JSON must conform to `schemas/slide_plan.schema.json`.

Required top-level fields:

- `topic.topic_id`
- `topic.topic_name`
- `topic.topic_summary`
- `slides[]`

Each slide must include:

- `slide_id`
- `slide_purpose`
- `main_title`
- `subtitle`
- `core_message`
- `content.content_type`
- `content.layout_intent`
- `content.items[]`
- `narration`
- `narration_beats[]`

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
- Use 4-7 narration beats per slide.
- Map every important beat to one visible group.
- Keep page content sparse enough for manual Mask painting: usually 5-8 visible groups.
- Avoid planning a slide that requires many tiny labels or dense text.
- If a concept needs many steps, split it into multiple slides.
- Keep the subtitle safe zone clear in the visual plan.

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
      "content": {
        "content_type": "concept_explanation",
        "layout_intent": "左侧解释梯度和负梯度，中间用下山图，右侧放目标和学习率。",
        "items": [
          {"type": "concept", "label": "梯度", "text": "上升最快方向"},
          {"type": "concept", "label": "负梯度", "text": "下降最快方向"},
          {"type": "diagram", "label": "下山找谷底", "text": "沿山坡逐步靠近最低点"},
          {"type": "summary", "text": "每一步都重新计算方向，再更新参数"}
        ]
      },
      "narration": "先把梯度下降想象成下山。梯度指向上升最快的方向，而负梯度就是最陡的下坡路。我们每走一步，就重新判断当前最陡的下降方向，再继续靠近谷底。",
      "narration_beats": [
        {
          "id": "beat_01",
          "spoken_point": "先把梯度下降想象成下山。",
          "source_article_point": "生活化比喻：下山找谷底",
          "visual_group": "valley_diagram",
          "animation": "soft_zoom_in",
          "time_hint": "early"
        },
        {
          "id": "beat_02",
          "spoken_point": "梯度指向上升最快的方向。",
          "source_article_point": "梯度的方向含义",
          "visual_group": "gradient_card",
          "animation": "fade_up",
          "time_hint": "middle"
        },
        {
          "id": "beat_03",
          "spoken_point": "负梯度就是最陡的下坡路。",
          "source_article_point": "负梯度是下降最快方向",
          "visual_group": "negative_gradient_card",
          "animation": "fade_up",
          "time_hint": "middle"
        }
      ]
    }
  ]
}
```
