# Video QA Checklist

## Six-Step UI

- Notifications appear in the unused lower-left navigation area.
- Storyboard edits autosave without overwriting newer changes.
- Image cards keep titles close to previews.
- Image confirmation is disabled until every current slide has an image.
- Replacing or deleting an image clears that slide's old Masks and downstream state.
- Mask preview matches the exact rendered composite.
- Audio must be generated and confirmed before video rendering.
- Rendered videos can be downloaded and deleted locally.

## Visuals

- Source images are 1920×1080.
- Masked pages start from the fixed background, not the full source image.
- Each reveal contains only its painted Mask pixels after outer-white removal.
- Fully enclosed Mask holes are filled only when no eraser stroke exists; explicit erasing is preserved.
- Mask foreground coverage must be at least 99.9%.
- No-Mask pages display the complete image from the first frame.
- No clipped text, missing card edges, floating fragments, or stale layers.
- Subtitles do not obscure important content.

## Timing and Audio

- Reveal events begin with their linked narration beat.
- Slide duration covers audio plus tail padding.
- Speech is not cut at slide boundaries.
- Audio and video durations are consistent.

## Export

- MP4 plays normally at 1920×1080.
- New videos carry `manual_mask_outer_white_v3` metadata.
- Historical videos are visibly marked as legacy.

## Regression

- Python and JavaScript syntax checks pass.
- Remotion TypeScript check passes.
- All checks under `checks/test_*.py` and `checks/test_*.js` pass.
- Browser console has no new errors during the six visible steps.
