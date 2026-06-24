# Maintenance audit: 2026-06-24

This document records the repository consistency audit and the cleanup queue discovered on 2026-06-24.

## Scope reviewed

- Repository metadata and permissions.
- Open issues and recent merged pull requests.
- README, AGENTS, smoke-test documentation, runtime-hotfix documentation.
- Core runtime bridge files: `sitecustomize.py`, `usercustomize.py`, `runtime_security.py`, `runtime_settings_mask.py`.
- Main backend touchpoints in `server.py` visible through repository search.
- Pipeline configuration and production invariants.
- Dependency declarations and ignore rules.

## Current high-level state

The project has a clear production flow:

```text
article.md
-> visual_contract.json
-> visual_prompt.md
-> visual_draft.png
-> optional manual masks in reveal_manifest.json
-> scripts/build_reveal_scene.py
-> scripts/bind_reveal_timeline.py
-> scripts/build_remotion_props.py
-> Remotion MP4
```

The main maintenance risk is that several production behaviors are still implemented through Python startup hooks rather than normal application source. Those hooks are valid short-term bridges, but they should not continue to accumulate responsibilities.

## Confirmed consistency fixes made in this audit PR

- Added an explicit mapping between six user-visible steps and internal Step numbers in `README.md`.
- Added the same mapping and runtime-bridge policy to `AGENTS.md`.
- Clarified the end-to-end smoke checklist so UI Step numbers and internal artifact/API Step numbers are no longer conflated.
- Added explicit maintenance notes for security hardening, temporary branches, runtime bridges, and dependency lockfiles.

## Remaining source-level cleanup queue

These items are intentionally not fixed in the documentation-only audit PR because they touch large or behavior-sensitive code paths.

### 1. Remove Step 1 unreachable legacy code

`server.py` currently returns after writing the local article brief, while a legacy LLM ingestion block remains below that return. The repository already includes a conservative cleanup helper:

```bash
python scripts/cleanup_step1_dead_code.py --check
python scripts/cleanup_step1_dead_code.py --apply
```

Recommended follow-up:

- Run the helper locally.
- Review the generated diff.
- Commit the cleaned `server.py` in a dedicated PR.

### 2. Move Step 5 `build_assets` semantics into `server.py`

The Step 5 endpoint accepts a `build_assets` query argument, but the source path still builds assets unconditionally. Runtime code currently patches this behavior.

Recommended source behavior:

```text
build_assets=true  -> save manifest and rebuild reveal assets
build_assets=false -> save manifest only and return built_assets=false
```

### 3. Move Step 6 narration preservation into `server.py`

The Step 6 init path currently calls `write_narration_from_visual_contract.py --overwrite`. Runtime code prevents overwriting existing edited narration.

Recommended source behavior:

```text
existing narration_beats.json + no explicit force -> preserve existing narration
no existing narration_beats.json -> initialize from visual_contract.json
explicit force/overwrite -> regenerate from visual_contract.json
```

### 4. Move Step 8 Remotion render safeguards into source

Runtime code currently handles several Step 8 issues:

- `props_started` fallback.
- duplicate pre-timeout Remotion render skipping.
- explicit Remotion entrypoint normalization.
- bounded subprocess timeouts.

Recommended source behavior:

- Define elapsed-time variables in the Step 8 render function directly.
- Keep exactly one effective Remotion render call.
- Use the explicit Remotion entrypoint form: `npx remotion render src/index.tsx ArticleVideo <output>`.
- Set timeouts at the actual subprocess call sites.

### 5. Move optional security controls into normal application startup

`runtime_security.py` and `runtime_settings_mask.py` should remain until source-level app startup owns:

- optional access token middleware;
- optional origin allow-list;
- optional settings credential masking;
- placeholder-preserving settings updates.

## Branch cleanup candidates

The following merged PR branches were observed as `ahead_by=0` relative to `main` during the audit and can be deleted after confirming no follow-up work depends on them:

- `fix-step8-render`
- `codex/tts-resume-flexible-style`
- `feature/ai-style-template-agent-v3`
- `codex/production-invariants-style-policy`

## Dependency reproducibility

Current dependency declarations use open ranges:

- Python `requirements.txt` uses `>=` constraints.
- Remotion `package.json` uses `^` ranges.
- No Node lockfile was observed for `scripts/remotion` during the audit.

Recommended follow-up:

```bash
cd scripts/remotion
npm install
# commit package-lock.json if generated
npm ci
npx tsc --noEmit -p tsconfig.json
```

After committing a lockfile, change validation docs from `npm install` to `npm ci`.

## Related tracker

Issue #7 remains the source-migration tracker for runtime hotfixes. This audit does not close that issue; it sharpens the remaining work and reduces documentation ambiguity around the current transitional state.
