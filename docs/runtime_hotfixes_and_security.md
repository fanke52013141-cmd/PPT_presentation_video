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
| `usercustomize.py` | Python auto-loaded bridge for small optional hooks. |
| `runtime_security.py` | Optional access token and origin checks. |
| `runtime_settings_mask.py` | Optional masking for credentials returned by `/api/settings`. |
| `scripts/check_python_startup_hooks.py` | Self-check that Python startup imports the hook modules. |
| `scripts/check_runtime_hotfixes.py` | Self-check for the main runtime safeguards. |
| `scripts/check_runtime_settings_mask.py` | Self-check for settings credential masking. |
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

Run these from the repository root:

```bash
python scripts/check_python_startup_hooks.py
python scripts/check_runtime_hotfixes.py
PPT_STUDIO_MASK_SETTINGS_SECRETS=1 python scripts/check_runtime_settings_mask.py
```

`check_python_startup_hooks.py` launches a child Python interpreter and confirms
that `sitecustomize`, `runtime_security`, `usercustomize`, and
`runtime_settings_mask` are imported during normal Python startup.

`check_runtime_hotfixes.py` validates the main runtime pipeline safeguards.
`check_runtime_settings_mask.py` validates settings credential masking and
placeholder preservation.

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
