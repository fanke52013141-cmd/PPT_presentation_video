# Slide Plan Checks

Target: `runs/<run_id>/planning/slide_plan.json`

## Required Fields

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
- `content`
- `content.content_type`
- `content.layout_intent`
- `content.items[]`
- `narration`
- `narration_beats[]`

## Narration Checks

- `narration` is a speakable Chinese voiceover paragraph.
- It does not contain stage directions, camera directions, or bracketed emotion
  notes.
- It expands the visible slide content.
- It does not introduce unrelated ideas that the page will not show.
- `narration_beats[]` has 4-7 beats when possible.
- Every important beat maps to a `visual_group`.
- Each beat references a source article point or a clear article concept.

## Visual Planning Checks

- Each slide explains one core idea.
- Complex topics are split across slides instead of crowded into one page.
- The planned visual can be represented by 5-8 macro groups.
- `layout_intent` mentions a layout that can keep groups separated.
- The plan does not require many tiny labels, dense paragraphs, or overlapping
  connector lines.

## Disallowed

- No `article_brief.json` dependency.
- No `duration_sec` as a fixed slide-plan output; exact duration comes from
  TTS/audio later.
- No narration that is unrelated to `content.items[]`.
