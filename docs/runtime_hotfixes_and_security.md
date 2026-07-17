# Runtime hotfixes and optional security controls

This repository still has a small set of explicitly registered compatibility
adapters around the large `server.py` module. The former polling bootstrap has
been removed; normal server startup is now the only registration path.

The bridge is intentionally explicit and removable. Every item below should
ultimately be migrated back into the normal source files.

## Runtime bridge files

| File | Purpose |
| --- | --- |
| `sitecustomize.py` | Python auto-loaded runtime safeguards for pipeline stability. |
| `app_security.py` | Explicit access token and origin middleware installed by `server.py`. |
| `server.py` Settings routes | Credential masking and placeholder-preserving updates, enabled by default. |
| `scripts/ppt_studio_doctor.py` | Consolidated project health check entry point. |
| `pipeline_services.py` | In-process production service facade shared by One-click and route handlers. |
| `runtime_ai_mask_semantic_patch.py` | Semantic-object matcher used by AI Mask before exact title/body ownership is finalized. |
| `runtime_project_style_references.py` | Project-local Step 3 image-style prompts and reference image helpers. |
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
- Step 6 init narration preservation has moved into `server.py`; the old startup patch is now compatibility-only.
- Step 2 / Step 5 `visual_contract.json` to `reveal_manifest.json` group-level reconciliation.
- Step 2 `topic_summary` preservation.
- Step 5 `build_assets=false` semantics.
- JSON-safe handling for `validate_render_color.py` output.

Project-aware Step 3 prompt and generation behavior now lives in the source
routes and delegates reusable style resolution to `runtime_project_style_references.py`.
The duplicate `runtime_project_style_reference_step3.py` route was removed.

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

A successful query-token request sets an HttpOnly same-origin cookie and immediately
redirects to the same URL without the token query parameter. Query tokens are rejected
for state-changing requests.

### Same-origin enforcement and optional Origin allow-list

```bash
export PPT_STUDIO_ALLOWED_ORIGINS="http://127.0.0.1:8000,http://localhost:8000"
```

Browser requests are same-origin by default. Extra origins must match this allow-list,
and state-changing browser API requests must include `X-PPT-Studio-Request: 1`.
For a reverse proxy or custom hostname, also configure:

```bash
export PPT_STUDIO_ALLOWED_HOSTS="studio.example.com"
```

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
The normal `GET /api/config/export` follows the same masking rule. Raw secrets
are only returned by `POST /api/config/export-with-secrets` with confirmation
value `EXPORT_SECRETS`.

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

`check_python_startup_hooks.py` confirms that the retired polling bootstrap and
`usercustomize.py` hook are absent and that normal server startup explicitly
registers AI Mask.

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

- continue extracting route-handler business logic behind normal service modules;
- remove runtime bridge code as source patches land;
- close the gap between local-only defaults and hardened deployment defaults.

## Important limitations

These runtime modules are not a substitute for source-level fixes. They are safe
bridges for the current repository state. Long term, keep `server.py` as the
source of truth for backend behavior, keep frontend navigation behavior in the
main frontend code, and keep security middleware in normal application startup
code.
# One-click resume and AI Mask protection (2026-07-10)

`one_click_orchestrator.py` now writes status atomically, distinguishes
restart from resume, resumes at the failed stage, preserves existing narration,
and requests automatic technical audio confirmation explicitly. Its AI Mask
calls preserve locked groups and manual corrections while allowing untouched
AI-only RLE masks to be refreshed.

As of the second migration batch, One-click no longer creates a FastAPI
`TestClient` or calls the application's own HTTP routes. It calls
`ProjectPipelineServices` directly, while AI Mask exposes a shared
`annotate_project` service used by both the route and One-click.

`runtime_ai_mask.py` supports `overwrite_existing_ai_mask` separately from
`overwrite_existing_manual_mask`. Only an unlocked AI mask with no correction
strokes is replaceable when manual overwrite is disabled. The component
completion pass also conservatively reassigns small secondary components when
another dominant visual island is at least 1.5 times closer.

Narration-bound title and subtitle regions now remain spatially isolated but are
assigned exact RLE Masks and participate in Reveal animation. The semantic-object
bridge prompt mirrors this rule; title pixels remain static only when a slide has
no narration group available.

As of the visual-group atomicity migration, `runtime_ai_mask.py` is the prompt
source of truth. `runtime_ai_mask_semantic_patch.py` still prepares merged
semantic-object images for the multimodal matcher, but it no longer overwrites
the base AI Mask methodology or output contract during import. The source
quality pass rejects a visual group whose description asks for multiple
independent visual islands, preventing full-coverage completion from silently
absorbing several Reveal units into one Mask. This migration remains tracked in
issue #7 until semantic-object preparation also moves into the normal service.

Migration debt: the remaining `runtime_*` filenames are explicitly registered
compatibility adapters, not auto-installing patches. Continue moving their
business logic into normal services under issue #7.

## Step 3 batch Prompt normalization (2026-07-13)

The source Step 3 prompt route now separates the prompt into one global image
style/rules block and one compact block per Slide. The project-style runtime
route delegates to the same source composition helpers and returns the same
`global_prompt`, `slide_prompt`, and `batch_prompt` response contract. This
prevents the browser's “复制生图提示词” action from repeating the full style and
production rules for every Slide while preserving complete per-Slide prompts
for the application's own image-generation API.

Project-local style resolution is now called by the normal Step 3 source route;
the former compatibility route no longer shadows it. The remaining project-style
runtime modules are still tracked for service extraction in issue #7.

## Read-only results and explicit repair (2026-07-15)

`GET` result routes no longer normalize, synchronize, or rewrite project files.
Historical drift is reported through a `repair` object and can be fixed only by
an explicit user-confirmed POST:

- `POST /api/projects/{project_id}/steps/2/repair`
- `POST /api/projects/{project_id}/steps/5/repair`
- `POST /api/projects/{project_id}/steps/6/repair`

The frontend offers this repair when it detects old schema data. This keeps
retries, caching, monitoring, and ordinary reads free of hidden writes.

The legacy `/navigate`, Step 5 `/auto-mask`, Step 7 `/synthesize-legacy`, and
internal Step 4 AI Mask alias were removed after confirming that production UI
and scripts no longer call them. Runtime theme injection was also removed from
all frontend extensions; `static/style.css` is now the only style source and
active DOM code no longer uses `sketch-*` compatibility class names.
