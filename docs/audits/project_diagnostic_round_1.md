# Project Diagnostic Round 1 - Structure and stale-file audit

Date: 2026-06-21

Scope: repository structure, README/AGENTS/config alignment, runtime artifacts, legacy scripts, and visible production path.

## Findings

1. Runtime and deliverable folders are correctly protected by `.gitignore`.
   - `runs/**`, `outputs/**`, `data/**`, media outputs, Remotion runtime assets, `.env`, and local caches are ignored.
   - `.gitkeep` placeholders are intentionally tracked.

2. Production reveal path is consistently documented as manual Mask exact v2, but legacy diagnostic tools remain in the repo.
   - `README.md` and `AGENTS.md` both say these scripts are diagnostics only:
     - `scripts/auto_fit_reveal_boxes.py`
     - `scripts/split_master_layers.py`
     - `scripts/decompose_slide_layers.py`
     - `scripts/compose_manifest_layers.py`
     - `scripts/prepare_full_slide_scenes.py`
   - Existing test `checks/test_reveal_pipeline_isolation.py` protects the web production path from calling old algorithms.
   - Recommendation: keep them as diagnostics for now; deleting them would remove useful recovery/debug tools.

3. The two biggest files are `server.py` and `static/app.js`.
   - `server.py` and `static/app.js` are both large enough that future changes should favor helper modules.
   - This branch follows that direction by adding `scripts/pipeline_profiles.py` and `scripts/generic_tts.py`.

4. Encoding concern was investigated.
   - PowerShell output can show mojibake for Chinese text, but Python UTF-8 reads confirmed source files are intact.
   - Risk remains for Windows console display only, not repository corruption.

5. Chinese reference image filenames can show escaped bytes in Git/PowerShell contexts.
   - `references/style_reference/PPT模板.png`
   - `references/style_reference/PPT示例.png`
   - They are intentionally tracked because image style reference generation uses them.

## Conclusion

No redundant committed runtime output was found. The main cleanup risk is not deletion, but drift: legacy scripts must remain clearly isolated from web production.
