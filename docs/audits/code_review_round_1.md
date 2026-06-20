# Code review round 1

Date: 2026-06-21

## Focus

- Syntax and core regression checks.
- Existing Mask and audio confirmation behavior.
- New generalized pipeline tests.

## Commands

```powershell
python -m compileall -q server.py scripts checks
node --check static\app.js
node --check static\flow.js
node checks\test_visible_flow.js
python checks\test_generalized_pipeline_config.py
python checks\test_reveal_mask_integrity.py
python checks\test_reveal_pipeline_isolation.py
python checks\test_slide_visual_invalidation.py
python checks\test_audio_confirmation.py
python checks\test_audio_tail_padding.py
python checks\test_mask_coverage_gate.py
```

## Result

Passed after adjusting profile wording to explicitly discourage fixed slide templates.
