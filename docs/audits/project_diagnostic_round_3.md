# Project Diagnostic Round 3 - Runtime mask/TTS/video audit

Date: 2026-06-21

Scope: manual Mask rendering, reveal timeline binding, Remotion effects, and TTS provider architecture.

## Findings

1. Manual Mask strategy is intentionally conservative and safe.
   - Current production builder copies only manually painted source pixels onto a solid background.
   - It avoids automatic expansion, connected-component ownership, segmentation, and cross-group erasing.
   - This is not always the fastest authoring UX, but it is the safest production output contract.

2. Mask optimization opportunities are mostly UX/preflight, not automatic compositing.
   - Good next optimizations:
     - AI semantic block suggestions remain optional.
     - Coverage preview and uncovered-foreground diagnostics remain mandatory before render.
     - Optional assisted brush-fill can be added later, but should write explicit strokes/masks and still pass exact-mask validation.
   - Avoid reintroducing old automatic layer splitting into production.

3. Reveal animation had a real consistency bug.
   - `reveal_manifest.json` could contain wipe/fog-style actions.
   - `scripts/build_reveal_scene.py` reduced unsupported actions to `crop_fade_up`.
   - `scripts/bind_reveal_timeline.py` also capped reveal duration at 0.12s.
   - This branch preserves configured action/duration and adds Remotion support for richer wipe/scratch reveal effects.

4. TTS was MiniMax-specific.
   - Settings, test endpoint, and synthesize endpoint were tightly coupled to MiniMax.
   - This branch adds `scripts/generic_tts.py` and provider settings for MiniMax, Aliyun CosyVoice, Tencent TTS, and Volcengine Seed Speech.
   - Output files remain unchanged: `voice.mp3`, `tts_metadata.json`, `tts_narration.srt`, `audio_timeline.json`.

## Conclusion

The mask algorithm should stay exact and manual-first. The higher-value improvements are providerized TTS, configurable reveal effects, preserving reveal duration, and better preflight/test coverage.
