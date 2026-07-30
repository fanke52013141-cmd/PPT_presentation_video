# Source safeguards, compatibility modules, and optional security controls

The Python auto-start hotfix layer has been retired. `sitecustomize.py` no
longer exists, `subprocess.run` is never globally replaced, and normal server
startup is the only registration path.

Remaining compatibility modules are explicit and removable. Every item below
should ultimately be migrated behind normal service and route modules.

## Runtime bridge files

| File | Purpose |
| --- | --- |
| `reveal_manifest_service.py` | Source-owned storyboard/Manifest reconciliation that preserves painted and manual Masks. |
| `app_security.py` | Explicit access token and origin middleware installed by `server.py`. |
| `server.py` Settings routes | Credential masking and placeholder-preserving updates, enabled by default. |
| `scripts/ppt_studio_doctor.py` | Consolidated project health check entry point. |
| `pipeline_services.py` | In-process production facade backed by explicit storyboard, image, Mask, narration, and media operation groups. |
| `pptx_routes.py` | Source-owned explicit PPTX export, job, download, and deletion routes. |
| `pptx_service.py` | Persistent PPTX job and artifact lifecycle with narrow session/root dependencies. |
| `video_routes.py` | Source-owned render, polling, MP4 collection, download, speed, deletion, and final-video routes. |
| `video_render_service.py` | Video job orchestration, in-memory compatibility state, and per-project locks. |
| `video_job_store.py` | Persistent SQLite video job creation, polling, transitions, and restart recovery. |
| `video_artifact_service.py` | Validated MP4 paths, freshness metadata, speed variants, downloads, deletion, and artifact registration. |
| `remotion_runner.py` | Reveal/timeline/props subprocess chain, Remotion execution, and color validation. |
| `video_contracts.py` | Shared video configuration and application error contracts. |
| `diagnostics_routes.py` | Source-owned diagnostics `APIRouter`; reads the request application only when producing diagnostics. |
| `storyboard_background.py` | Source-owned storyboard background service and explicit `APIRouter`. |
| `storyboard_service.py` | Step 2 prompt/profile planning, visual-contract normalization, validation, repair, and manual skeleton workflow. |
| `storyboard_routes.py` | Explicit Step 2 planning and storyboard-template HTTP routes. |
| `narration_service.py` / `narration_routes.py` | Step 6 narration lifecycle and explicit HTTP routes. |
| `tts_service.py` / `tts_routes.py` | Step 7 synthesis, audio artifact status/download, confirmation, and explicit HTTP routes. |
| `one_click_routes.py` | Source-owned One-click HTTP routes. |
| `one_click_orchestrator.py` | One-click task orchestration configured through narrow `OneClickDependencies`. |
| `ai_mask_config.py` | Source-owned AI Mask settings persistence and Prompt migration. |
| `ai_mask_service.py` | Source-owned AI Mask project task orchestration with narrow dependencies. |
| `ai_mask_routes.py` | Explicit AI Mask settings and annotation FastAPI routes. |
| `ai_mask_engine.py` | Pixel detection, exact-mask completion, and multimodal matching engine. |
| `ai_mask_semantic_matcher.py` | Source-owned semantic-object preparation and multimodal matcher, explicitly injected into the task service. |
| `project_style_routes.py` | Explicit Project Profile and Step 3 image-style FastAPI routes. |
| `project_style_context.py` | Narrow, explicitly configured dependencies for project-style services. |
| Project-style service/store modules | Source-owned profile, reverse-analysis, reference-image, state, and template behavior. |
| `scripts/check_python_startup_hooks.py` | Self-check that normal server startup calls the explicit installer. |
| `scripts/check_runtime_hotfixes.py` | Self-check for the main runtime safeguards. |
| `scripts/check_runtime_settings_mask.py` | Self-check for settings credential masking. |
| `scripts/check_smoke_artifacts.py` | Structural artifact checker after manual end-to-end smoke tests. |
| `docs/e2e_smoke_test_checklist.md` | Manual happy-path smoke test checklist. |
| `scripts/cleanup_step1_dead_code.py` | Local source cleanup helper for Step 1 unreachable code. |

## What is currently protected

### Pipeline stability

Normal source code now provides:

- one timeout-bounded Remotion render invocation;
- explicit timeouts for timeline binding, props generation, npm install, color normalization, and color validation;
- Step 6 narration reuse without overwriting an existing `narration_beats.json`;
- Step 2 / Step 5 group-level reconciliation from `visual_contract.json` to `reveal_manifest.json`;
- `topic_summary` preservation and provenance hash refresh;
- correct Step 5 `build_assets=false` semantics;
- JSON-safe handling for `validate_render_color.py` output.

Project-aware Step 3 prompt and generation behavior now lives in source-owned
routes and services. `project_style_reference_service.py` supplies reusable
style resolution without receiving the application module. The former runtime
route-registration and route-shadowing modules have been removed.

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

`ppt_studio_doctor.py` runs the startup hook check, source safeguard check,
settings masking check, Step 1 cleanup safety preview, and optionally a run_dir
artifact check.

`check_python_startup_hooks.py` confirms that the retired polling bootstrap and
`usercustomize.py` hook are absent and that normal server startup explicitly
registers AI Mask.

`check_runtime_hotfixes.py` is retained as a compatible command name, but now
validates source-owned safeguards and verifies that `sitecustomize.py` and the
global subprocess monkey patch remain absent.
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

- continue extracting AI Mask and project-style route business logic behind normal service modules;
- remove explicitly registered compatibility modules as source services land;
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

As of the explicit-route migration, One-click no longer creates a FastAPI
`TestClient`, calls the application's own HTTP routes, or receives the complete
`server` module. `one_click_routes.py` owns the HTTP contract and
`one_click_orchestrator.py` receives a narrow `OneClickDependencies` object.
The injected pipeline facade delegates production stage operations to
`ProjectPipelineServices`, which now receives an immutable
`PipelineOperations` graph instead of the complete `server` module. The graph
groups the exact storyboard, image, Mask, narration, and media functions bound
at application startup. Both the route and One-click use the source-owned
`AiMaskTaskService`.

Diagnostics and storyboard-background registration are also source-owned.
`server.py` includes their `APIRouter` instances directly; their former
`_register(server_module)` entry points and patch markers no longer exist.

PPTX export registration is source-owned as well. `pptx_routes.py` exposes an
explicit `APIRouter`, while `pptx_service.py` owns task recovery, export
execution, Step 8 completion, artifact listing, download, and deletion. Its
dependency object contains only the database session factory, validated runs
root, and an optional executor; the former
`register_pptx_routes(server_module)` and `_SERVER` global no longer exist.

The complete Step 8 video chain is also source-owned and split by responsibility.
`video_render_service.py` is now a coordinator: it validates prerequisites,
creates a persistent job, drives stage transitions, publishes the completed
artifact, and maintains the in-memory compatibility cache and project lock.
`video_job_store.py` owns SQLite job persistence and restart recovery;
`video_artifact_service.py` owns MP4 paths, sidecars, freshness, speed variants,
and registry lifecycle; `remotion_runner.py` owns the Reveal/timeline/props
subprocess chain, Remotion invocation, and color QA. `video_routes.py` exposes
the unchanged HTTP paths. `server.py` explicitly assembles these narrow
components and injects the coordinator into One-click. The former worker,
global task dictionaries, video route decorators, and unused
`persistent_job_store.py` compatibility module remain retired.

`ai_mask_engine.py` supports `overwrite_existing_ai_mask` separately from
`overwrite_existing_manual_mask`. Only an unlocked AI mask with no correction
strokes is replaceable when manual overwrite is disabled. The component
completion pass also conservatively reassigns small secondary components when
another dominant visual island is at least 1.5 times closer.

Narration-bound title and subtitle regions now remain spatially isolated but are
assigned exact RLE Masks and participate in Reveal animation. The semantic-object
bridge prompt mirrors this rule; title pixels remain static only when a slide has
no narration group available.

As of the AI Mask service extraction, `ai_mask_config.py` is the public Prompt
and settings source of truth, `ai_mask_service.py` owns task orchestration,
`ai_mask_routes.py` owns HTTP registration, and `ai_mask_engine.py` owns the
matching algorithms. `runtime_ai_mask.py` and its `_register(server_module)`
compatibility entry point no longer exist.

The semantic matcher migration is also complete:
`ai_mask_semantic_matcher.py` prepares merged semantic-object images and exposes
`SemanticVisionMatcher`; `server.py` injects its singleton into
`AiMaskTaskService`, and `ai_mask_engine.py` calls only the matcher it receives.
No project-style import mutates AI Mask behavior, so startup import order can no
longer replace `_vision_match`. The source quality pass still rejects a visual
group whose description asks for multiple independent visual islands,
preventing full-coverage completion from silently absorbing several Reveal
units into one Mask.

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

## Prompt-contract hardening (2026-07-18)

Narration annotation now treats the currently editable `tts_text` as the latest
source of truth and synchronizes its plain text into `source_text` and
`spoken_text`. Only supported MiniMax pause/expression tags are stripped; literal
ASCII parentheticals such as `(REST)` and `(GraphQL)` remain narration content.

Text-generated and reference-reversed image styles now validate their declared
JSON output contracts before persisting them. Model-supplied hidden production
fields such as `system_content` and `maskability_rules` are rejected or ignored;
production rules and editable System Content are built deterministically.

`project_style_routes.py` explicitly owns
`GET/PUT /api/settings/image-style-reference-generation`. It controls only the
content-neutral preview-image methodology. Per-project style content, neutral
scene briefs, and non-overridable 16:9/white-canvas constraints are composed once
by `project_style_reference_service.py`. The former runtime registration bridge
and `register_project_style_routes(server_module)` no longer exist.

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
