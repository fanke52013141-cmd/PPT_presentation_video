# Slide Plan Prompt

## Purpose

Convert the supplied article into a narration-first slide plan that downstream visual planning can consume without inventing facts or prematurely fixing the page layout.

## Input

- `runs/<run_id>/inputs/article.md` is the sole content source.
- Production invariants and the schemas named below define the non-negotiable boundaries.

## Output

- Write one valid JSON object to `runs/<run_id>/planning/slide_plan.json`.
- Output no Markdown wrapper, commentary, image prompt, Mask coordinates, or Reveal implementation.

Read `runs/<run_id>/inputs/article.md` and produce
`runs/<run_id>/planning/slide_plan.json`.

The plan must be narration-first. Do not over-structure the page. The only fixed
content structure is: one main title and body content / narration. Page
subtitles are not part of the product contract.

## Production Invariants

These rules are not style choices and must never be changed by a style profile:

- Every slide must have one clear `main_title`.
- `presentation_policy.subtitle_policy` must be `no_slides_have_subtitle`.
- No slide may include a page subtitle, subtitle underline, or subtitle placeholder.
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
- `subtitle` must be an empty string when retained for backward-compatible storage
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

Use the fixed no-subtitle presentation policy:

```json
{
  "presentation_policy": {
    "subtitle_policy": "no_slides_have_subtitle",
    "subtitle_decided_by": "system_no_subtitle_contract",
    "subtitle_rationale": "页面只保留主标题，把垂直空间交还给正文视觉。",
    "default_visual_anchor_count": "2-5",
    "layout_freedom": "high"
  }
}
```

Do not choose or generate page subtitles. Give that space back to the main visual.

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
- Keep the plan simple: main title, body content, narration.
- Do not classify content as diagram/data/summary/quote/process/etc. during planning.
- Put everything besides the title into `body_content`.
- Use `visual_intent` to describe the desired meaning or feel, not exact coordinates or blocks.
- Let the image generation stage decide whether body content becomes a scene, diagram, card, timeline, icon set, metaphor, or mixed layout.
- If you provide `visual_groups`, keep them as 2-5 loose anchors for later Mask/Reveal review.
- Keep y=930..1080 completely clear.

## Example

```json
{
  "presentation_policy": {
    "subtitle_policy": "no_slides_have_subtitle",
    "subtitle_decided_by": "system_no_subtitle_contract",
    "subtitle_rationale": "页面只保留主标题。",
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
      "subtitle": "",
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
