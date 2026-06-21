# Generalization implementation plan

Date: 2026-06-21

## Goals

1. Make storyboard/slide structure configurable.
2. Make image prompt and image style configurable.
3. Keep exact manual Mask production behavior, but improve diagnostics and preserve richer reveal effects.
4. Add providerized TTS with voice-clone-compatible fields.
5. Add configurable reveal effects in final video.
6. Leave changes on a safe feature branch.

## Implementation steps

1. Add `config/pipeline_profiles.yaml`.
   - Configurable slide count, group count, roles, optional/required fields, and default reveal actions.

2. Add `scripts/pipeline_profiles.py`.
   - Shared helper for prompts, validators, reveal defaults, and speak policies.

3. Update storyboard generation.
   - Remove fixed subtitle/summary requirement.
   - Inject profile rules into system prompt.

4. Update image prompt generation.
   - Read generic image prompt rules from profile.
   - Keep style editor backed by `config/style_tokens.yaml`.

5. Update schemas and validators.
   - Allow custom roles.
   - Keep semantic consistency checks for narration and display-only groups.

6. Update reveal generation and timeline binding.
   - Preserve configured action/duration.
   - Add wipe/scratch reveal support in Remotion.

7. Add generic TTS.
   - Keep MiniMax as default.
   - Add Aliyun CosyVoice, Tencent TTS, Volcengine Seed Speech.
   - Support clone voice ids without changing downstream audio files.

8. Add tests and documentation.

## Non-goals for this branch

- No automatic production segmentation replacement for manual Mask.
- No deletion of legacy diagnostics.
- No full UI redesign.
- No hard dependency on paid provider credentials in tests.
