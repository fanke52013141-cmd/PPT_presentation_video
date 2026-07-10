# Runtime hotfixes and optional security controls

This repository currently uses a small set of runtime bridge modules to stabilize
the PPT video pipeline while the large `server.py` file is difficult to patch as a
single replacement.

The bridge is intentionally explicit and removable. Every item below should
ultimately be migrated back into the normal source files.

## Runtime bridge files

| File | Purpose |
| --- | --- |
| `sitecustomize.py` | Python auto-loaded runtime safeguards for pipeline stability. |
| `runtime_security.py` | Optional access token and origin checks. |
| `runtime_settings_mask.py` | Optional masking for credentials returned by `/api/settings`. |
| `scripts/ppt_studio_doctor.py` | Consolidated project health check entry point. |
| `runtime_bootstrap.py` | Explicit installer for backend compatibility routes. |
| `scripts/check_python_startup_hooks.py` | Self-check that normal server startup calls the explicit installer. |
| `scripts/check_runtime_hotfixes.py` | Self-check for the main runtime safeguards. |
| `scripts/check_runtime_settings_mask.py` | Self-check for settings credential masking. |
| `scripts/check_smoke_artifacts.py` | Structural artifact checker after manual end-to-end smoke tests. |
| `docs/e2e_smoke_test_checklist.md` | Manual happy-path smoke test checklist. |
| `scripts/cleanup_step1_dead_code.py` | Local source cleanup helper for Step 1 unreachable code. |

## What is currently protected

### Pipeline stability

`sitecustomize.py` provides runtime protections for:

- Step 8 `props_started` missing name.
- Duplicate pre-timeout Remotion render call.
- Missing timeouts for known subprocesses.
- Step 6 init overwriting existing narration.
- Step 2 / Step 5 `visual_contract.json` to `reveal_manifest.json` group-level reconciliation.
- Step 2 `topic_summary` preservation.
- Step 5 `build_assets=false` semantics.
- JSON-safe handling for `validate_render_color.py` output.

### Frontend flow

`static/flow.js` currently includes a guard that confirms Step 3 images before
navigating to Step 5 Mask annotation.

### Optional access control

Set a token to protect the API and browser UI:

```bash
export PPT_STUDIO_ACCESS_TOKEN="replace-with-long-random-token"
```

Supported request authentication methods:

- `Authorization: Bearer <token>`
- `X-App-Token: <token>`
- `?access_token=<token>`
- `?token=<token>`
- `ppt_studio_access_token` cookie

For browser use, first visit:

```text
http://127.0.0.1:8000/?access_token=replace-with-long-random-token
```

A successful query-token request sets an HttpOnly same-origin cookie.

### Optional Origin allow-list

```bash
export PPT_STUDIO_ALLOWED_ORIGINS="http://127.0.0.1:8000,http://localhost:8000"
```

When set, requests with an `Origin` header must match the allow-list.

### Optional settings credential masking

```bash
export PPT_STUDIO_MASK_SETTINGS_SECRETS=1
```

When enabled, `GET /api/settings` masks:

- `llm_api_key`
- `image_api_key`
- `tts_api_key`
- `tts_secret_key`
- `tts_provider_extra`

The placeholder is:

```text
__PPT_STUDIO_MASKED_VALUE__
```

If the browser submits the placeholder back through `PUT /api/settings`, the
stored value is preserved instead of being overwritten by the placeholder.

## Recommended local hardened start

```bash
export PPT_STUDIO_ACCESS_TOKEN="replace-with-long-random-token"
export PPT_STUDIO_MASK_SETTINGS_SECRETS=1
export PPT_STUDIO_ALLOWED_ORIGINS="http://127.0.0.1:8000,http://localhost:8000"
python server.py
```

## Self-check commands

Preferred consolidated check:

```bash
python scripts/ppt_studio_doctor.py
```

With a project artifact check:

```bash
python scripts/ppt_studio_doctor.py --run-dir runs/<project_id> --stage step8
```

Focused checks are still available:

```bash
python scripts/check_python_startup_hooks.py
python scripts/check_runtime_hotfixes.py
PPT_STUDIO_MASK_SETTINGS_SECRETS=1 python scripts/check_runtime_settings_mask.py
```

`ppt_studio_doctor.py` runs the startup hook check, runtime hotfix check,
settings masking check, Step 1 cleanup safety preview, and optionally a run_dir
artifact check.

`check_python_startup_hooks.py` confirms that normal server startup calls
`runtime_bootstrap.install_for_server_module` and that the retired
`usercustomize.py` hook is absent.

`check_runtime_hotfixes.py` validates the main runtime pipeline safeguards.
`check_runtime_settings_mask.py` validates settings credential masking and
placeholder preservation.

## End-to-end smoke testing

Use the manual checklist after pipeline or security changes:

```text
docs/e2e_smoke_test_checklist.md
```

After each stage, validate artifacts structurally with:

```bash
python scripts/check_smoke_artifacts.py --run-dir runs/<project_id> --stage step1
python scripts/check_smoke_artifacts.py --run-dir runs/<project_id> --stage step2
python scripts/check_smoke_artifacts.py --run-dir runs/<project_id> --stage step3
python scripts/check_smoke_artifacts.py --run-dir runs/<project_id> --stage step5
python scripts/check_smoke_artifacts.py --run-dir runs/<project_id> --stage step6
python scripts/check_smoke_artifacts.py --run-dir runs/<project_id> --stage step7
python scripts/check_smoke_artifacts.py --run-dir runs/<project_id> --stage step8
```

## Step 1 dead-code cleanup

Step 1 currently returns after writing a local article brief, while an old
LLM-based ingestion block remains below that return in `server.py`.

Use the helper script locally:

```bash
python scripts/cleanup_step1_dead_code.py --check
python scripts/cleanup_step1_dead_code.py --apply
```

The script checks exact anchors, verifies expected legacy fragments, parses the
result with Python AST, and creates a timestamped backup before writing.

## Migration tracking

Source migration is tracked in GitHub issue #7:

- migrate runtime patches back into `server.py` and main frontend files;
- remove runtime bridge code as source patches land;
- close the gap between local-only defaults and hardened deployment defaults.

## Important limitations

These runtime modules are not a substitute for source-level fixes. They are safe
bridges for the current repository state. Long term, keep `server.py` as the
source of truth for backend behavior, keep frontend navigation behavior in the
main frontend code, and keep security middleware in normal application startup
code.
# One-click resume and AI Mask protection (2026-07-10)

`runtime_one_click_orchestrator.py` now writes status atomically, distinguishes
restart from resume, resumes at the failed stage, preserves existing narration,
and requests automatic technical audio confirmation explicitly. Its AI Mask
calls preserve locked groups and manual corrections while allowing untouched
AI-only RLE masks to be refreshed.

`runtime_ai_mask.py` supports `overwrite_existing_ai_mask` separately from
`overwrite_existing_manual_mask`. Only an unlocked AI mask with no correction
strokes is replaceable when manual overwrite is disabled. The component
completion pass also conservatively reassigns small secondary components when
another dominant visual island is at least 1.5 times closer.

Migration debt: these behaviors remain runtime bridge behavior until the
one-click orchestration and AI Mask services are moved behind normal modules
registered directly from `server.py`. Track this migration with issue #7.
