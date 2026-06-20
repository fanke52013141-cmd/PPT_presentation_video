# Project Diagnostic Round 2 - Contract/schema/prompt consistency audit

Date: 2026-06-21

Scope: visual contract generation, schemas, reveal manifest template, image prompt generation, and frontend editing flow.

## Findings

1. The old storyboard prompt was too rigid.
   - It required title, subtitle, content body, and summary on every slide.
   - This contradicted the desired generalized content structure where subtitle/summary may be absent and other structures may be better.

2. Schema and validators needed to align with generalized roles.
   - `schemas/visual_contract.schema.json` previously enumerated a small role list.
   - `scripts/validate_visual_contract.py` previously treated only fixed roles as speakable.
   - This branch changes validation to use `config/pipeline_profiles.yaml` and permits custom roles while keeping `display_only` constraints.

3. Image style already had a UI and YAML-backed editor.
   - Existing `/api/image-style` plus `config/style_tokens.yaml` was a good foundation.
   - Remaining problem: the generated image prompt still hard-coded “hand-drawn PPT” language.
   - This branch now reads generic image prompt constraints from `config/pipeline_profiles.yaml` and style details from `config/style_tokens.yaml`.

4. Reveal manifest template needed role-based default animation from config.
   - The old template had a fixed `default_reveal(role)` function.
   - This branch delegates defaults to `scripts/pipeline_profiles.py`.

## Conclusion

The main contradiction was “prompt says fixed slide structure” while the product goal asks for flexible structure. The branch resolves this by introducing a pipeline profile and aligning prompt, schema, validator, template, and frontend persistence.
