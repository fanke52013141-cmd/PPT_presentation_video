# Video QA Checklist

## Eight-Step UI

- Notifications appear in the unused lower-left navigation area.
- Storyboard edits autosave without overwriting newer changes.
- Image cards keep titles close to previews.
- Image confirmation is disabled until every current slide has an image.
- Replacing or deleting an image clears that slide's old Masks and downstream state.
- Mask editing shows the original image with a clear colored paint overlay.
- Audio must be generated and confirmed before video rendering.
- Rendered videos can be downloaded and deleted locally.

## Visuals

- Source images match the selected canvas: 1920×1080 or 1080×1920.
- Masked pages start from the fixed background, not the full source image.
- Each reveal removes only boundary-connected white inside its painted Mask.
- White enclosed by non-white content remains visible.
- No coverage score, red diagnostic overlay, or legacy preview asset remains.
- No-Mask pages display the complete image from the first frame.
- No clipped text, missing card edges, floating fragments, or stale layers.
- Subtitles do not obscure important content.
- Every slide is inspected before, during and after its annotation events; test-only region marks must be explicitly removed from rehearsal copies before a demo is approved.
- Screen quotes match selected OCR text, while narration quotes match the exact spoken range. Replacement/unknown glyphs block confirmation until corrected.
- Annotation strokes stay on selected words, exclude adjacent words and remain visible on white, yellow and dark backgrounds.

## Timing and Audio

- Reveal events begin with their linked narration beat.
- Slide duration covers audio plus tail padding.
- Speech is not cut at slide boundaries.
- Audio and video durations are consistent.

## Export

- MP4 plays normally at 1920×1080.
- New videos carry `exact_rle_mask_with_manual_corrections_v6` metadata.
- Historical videos are visibly marked as legacy.

## Regression

- Python and JavaScript syntax checks pass.
- Remotion TypeScript check passes.
- All checks under `checks/test_*.py` and `checks/test_*.js` pass.
- Browser console has no new errors during the eight visible steps.
