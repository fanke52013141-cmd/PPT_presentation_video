# Video QA Checklist

## Content

- The slide explains the article's core point accurately.
- The narration expands the visible content instead of drifting to unrelated
  ideas.
- Every important narration beat has a visible macro group.
- The page is understandable for AI beginners.

## Master Image

- The master slide is an Image Gen bitmap, not a local code drawing.
- The middle content area is not crowded.
- Independent macro groups have at least 48-80px of clean spacing.
- Text, arrows, labels, icons, cards, formulas, and diagram strokes do not
  overlap or nearly touch.
- The subtitle safe zone is empty.
- Text is readable and not fake or garbled.

## Layer Recomposition

- `render_preview.png` visually matches the approved `visual_draft.png`.
- `split_report.json` exists.
- There are no `severity=blocking` split warnings.
- The scene has multiple PNG layers and no animated `full_slide` layer.
- Macro layers are large coherent groups, not tiny fragments.
- Layer edges do not show obvious white boxes, paper-noise blocks, or dirty
  alpha halos.

## Animation

- Animation follows narration beats.
- Body and diagram layers reveal when the voice reaches their cue.
- Summary appears near the end and can highlight.
- All content is not visible at frame 0.
- Motion is subtle enough that split edges do not feel like stickers.

## Audio And Subtitles

- TTS is natural and matches the narration.
- Subtitles match the voiceover.
- Subtitles do not cover key visual content.
- Chinese text is not encoding-damaged.

## Export

- MP4 plays normally.
- Resolution is 1920x1080.
- Aspect ratio is 16:9.
- Audio and video durations match.
