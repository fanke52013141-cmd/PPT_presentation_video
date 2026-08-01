# AGENTS.md

## Production Pipeline

The application has six user-visible steps:

1. Import an article or generate one from a topic.
2. Plan article-to-slide and slide-to-visualization output.
3. Configure image style/background and generate or upload one 1920×1080 image per slide.
4. Run automatic multimodal AI Mask annotation.
5. Edit narration, generate audio, and confirm audio.
6. Export and manage videos or image-only PPTX presentations.

### User-visible steps vs internal step numbers

The UI is intentionally compressed to six user-visible steps, while the backend and historical validation scripts still use internal Step numbers.

| User-visible step | Internal API / artifact stage | Main artifacts |
| --- | --- | --- |
| Step 1 Import article | Step 1 import | `inputs/article.md` |
| Step 2 Plan storyboard | Step 2 storyboard / visual contract | `planning/visual_contract.json` |
| Step 3 Images | Step 3 images + Step 4 confirmation | `slides/<slide_id>/visual_draft.png`, `reveal_manifest.json` |
| Step 4 Mask | Step 5 reveal manifest / mask assets | `reveal_manifest.json`, reveal layer assets |
| Step 5 Narration and audio | Step 6 narration + Step 7 TTS/audio confirmation | `planning/narration_beats.json`, audio, subtitles, timelines |
| Step 6 Output works | Step 8 Remotion render / PPTX export | `remotion_props.json`, rendered video, `.render.json` sidecar, image-only `.pptx` |

When writing user-facing documentation, prefer the six visible steps. When changing API routes, validators, or runtime artifacts, use the internal step numbers and keep this mapping accurate.

## UI Style Source of Truth

The current product UI is the soft blue-purple "Soft Pastel Studio" interface, not the older black-outline sketch style.

- Primary reference: `docs/ui_style_reference.md`.
- Implementation reference: the lower half of `static/style.css`, especially `/* Soft Pastel Studio refinement layer */`.
- Do not treat the early `Flat Outline UI` block in `static/style.css` as the intended design direction. It is a legacy compatibility foundation for existing class names such as `.sketch-border`, `.sketch-dashed`, and `.sketch-shadow`.
- Keep existing `sketch-*` class names only for DOM compatibility unless doing a deliberate CSS migration. New visual work should use the blue-purple palette, soft borders, rounded cards, glass header, and gradient AI action buttons from the Soft Pastel Studio layer.
- If the UI appears as heavy black borders or hard offset shadows, first check whether the browser is loading the full `static/style.css` and whether the Soft Pastel Studio layer is present.

## Frontend Module Boundaries

- `static/app.js` remains the shared workflow shell while the legacy frontend is
  being split without changing the established UI or global handler contract.
- `static/settings.js` owns settings form synchronization, configuration package
  import/export, and LLM/image/TTS connection checks. Keep these functions out
  of `app.js`; the classic script order intentionally preserves existing inline
  handlers and event registration.
- `static/projects.js` owns project-library rendering, project creation, and
  deletion. Render user-provided names/descriptions through `escHtml` and bind
  card actions with event listeners instead of interpolated inline handlers.
- `static/article.js` owns the visible Step 1 article workflow: source-mode
  switching, topic generation, manual import/editing, and article-generation
  System Content. Keep Step 1 functions out of `app.js`; a saved article must
  restore the edit action when the project is reopened.
- `static/storyboard.js` owns the visible Step 2 storyboard workflow: result
  loading, AI generation, manual slide editing, batch import/delete, visual and
  narration mapping, autosave, and contract persistence. Keep those functions
  out of `app.js`.
- `static/storyboard_prompts.js` owns the Step 2 Prompt editor and reusable
  Prompt-template lifecycle: modal loading, full-Prompt preview composition,
  template selection/create/delete, and prompt persistence. Keep this workflow
  out of both `app.js` and `storyboard.js`.
- `static/images.js` owns the visible Step 3 image workflow: image-state loading,
  grid and preview rendering, single/batch generation, single/batch upload,
  deletion, drag reassignment, candidate application, and Step 3 confirmation.
  Keep these functions and their transient state out of `app.js`; Step 3 Prompt
  settings and project image-style management remain separate concerns.
- `static/image_prompts.js` owns Step 3 image-generation Prompt loading, full
  preview composition, editing, reset, and persistence. It also exposes the
  explicit `window.refreshStep3Prompts` bridge consumed by image-style changes.
  Keep these functions out of both `app.js` and `images.js`.
- `static/mask_workspace.js` owns the visible Step 5 Mask workspace shell:
  project-scoped state reset/loading, reveal and narration normalization, Slide
  navigation, workspace/semantic-card/narration rendering, fragment mapping,
  selection, review focus, and the explicit workspace bridges consumed by the
  AI Mask extension. Canvas painting, raster preview, animation preview, and
  draft persistence remain separate until their own extraction.
- New extractions must preserve current DOM IDs and API paths, add an explicit
  script tag in `static/index.html`, and extend `checks/test_frontend_quality.js`
  with an ownership guard.

The production visual path is:

```text
article.md
-> visual_contract.json
-> visual_prompt.md
-> visual_draft.png
-> automatic element detection and multimodal narration matching
-> exact RLE Masks plus optional manual correction strokes in reveal_manifest.json
-> scripts/build_reveal_scene.py
-> scripts/bind_reveal_timeline.py
-> scripts/build_remotion_props.py
-> Remotion MP4
```

## Automatic AI Mask Contract

`scripts/build_reveal_scene.py` is the only production reveal builder.

- Pipeline version: `exact_rle_mask_with_manual_corrections_v5`.
- AI Mask detects separable elements, names candidate crops, and maps narrated
  visual groups to those candidates with a multimodal model.
- Every foreground component is required. Visual-only and decorative components
  are attached to the nearest narrated semantic anchor.
- The automatic result is stored as exact `manual_mask.rle` row runs. Optional
  manual paint/erase strokes are applied on top as corrections.
- A slide without a Mask is a static full-slide image.
- A slide with an exact or manually painted Mask starts from the configured video background.
- Generated images must use a pure-white outer background.
- Each automatic Mask is a processing boundary; only near-white pixels connected
  inward from that boundary are removed.
- White areas enclosed by content are preserved.
- A reveal layer retains non-white source content inside that group's saved
  Mask, with soft antialias alpha and white-edge decontamination.
- The source image must never be reused as the background of a masked slide.
- Automatic masks must reach at least 99.5% foreground coverage with zero
  unassigned components and zero cross-group pixel overlap.
- The reveal builder must not rematch semantic ownership; that belongs to the
  AI Mask stage. Manual brush, eraser, add, and delete remain available as fallback.
- Rebuild slide assets and Remotion runtime assets before every render.
- Validate the pipeline version and reject unreferenced legacy assets before rendering.

## Image Rules

- The PPT body comes from an approved bitmap image.
- Use 1920×1080, 16:9.
- Generate a pure-white (`#FFFFFF`) outer background.
- The final video canvas color is configurable; the default is `#FEFDF9`.
- Keep independent visual groups separated.
- Keep important body content above the subtitle area.
- Remotion may display PNGs, animate reveal PNGs, play audio, and draw
  transparent-background subtitles. It must not redraw PPT body content with
  HTML, SVG, Canvas, or React shapes.

## State and File Lifecycle

- Production schema changes use consecutive `migrations/NNNN_name.sql` files
  through `database_migrations.py`; never restore `create_all` or startup-time
  handwritten `ALTER TABLE` calls. Applied migrations are immutable and
  checksum protected.
- Business-level downstream invalidation belongs in
  `invalidation_service.py`. The service updates files and project state but
  never commits; API callers own one database commit.
- Replacing or deleting a slide image clears that slide's Masks, reveal assets,
  Remotion props, audio confirmation, and downstream completion state.
- Editing narration clears audio confirmation.
- Rendering is blocked until all slide audio has been generated and confirmed.
- Rendered videos carry a `.render.json` sidecar with the reveal pipeline
  version.
- Video render jobs and PPTX export jobs are persisted in the `local_jobs`
  SQLite table. In-memory task maps are compatibility caches, not the source of
  truth. Jobs left active by an exited process are marked `interrupted`.
- Newly rendered and speed-adjusted MP4 files are registered in
  `artifact_records`; deleting a video must remove the matching record.
- Deleting a rendered video deletes both the MP4 and its sidecar.
- Runtime data under `runs/`, `outputs/`, `logs/`, and Remotion `public/runtime`
  is never committed.

## Runtime Bridge Policy

The Python startup monkey patch has been retired. AI Mask is now source-owned:

- `ai_mask_config.py` owns persisted settings and Prompt migration.
- `ai_mask_service.py` owns project task orchestration through narrow
  dependencies.
- `ai_mask_routes.py` owns the explicit FastAPI routes.
- `ai_mask_engine.py` owns the deterministic and multimodal matching engine.
- `ai_mask_semantic_matcher.py` owns semantic-object preparation and is
  injected explicitly into the task service; it must never monkey-patch the
  engine.
- AI Mask algorithm code receives only `AiMaskEngineDependencies`; never pass
  a server module, application namespace, or mutable `SimpleNamespace` into
  `ai_mask_engine.py` or `ai_mask_semantic_matcher.py`.
- `project_style_routes.py` owns the Project Profile and Step 3 image-style
  HTTP contract. Its dependencies are configured through
  `project_style_context.py`; storage, reference generation, reverse analysis,
  and templates live in normal `project_*_service.py` / `*_store.py` modules.
- Project-style services receive `ProjectStyleDependencies` directly; do not
  recreate a mutable compatibility namespace or name that dependency
  `server_module`.
- Never restore `register_project_style_routes(server_module)`, route-order
  shadowing, or `runtime_project_*` modules.
- `global_image_style_service.py` owns legacy-compatible global image-style
  settings, reference images, and templates.
  `global_image_style_routes.py` owns the unchanged `/api/image-style/**`
  contract.
- `image_workflow_service.py` owns Step 3 prompt settings, image generation,
  uploads, candidates, ordering, provenance, deletion, and confirmation.
  `image_workflow_routes.py` owns the corresponding HTTP paths.
- `visual_settings_service.py` owns per-project video background and subtitle
  settings, input normalization, file persistence, preview selection, Reveal
  Manifest background synchronization, and downstream invalidation.
  `visual_settings_routes.py` owns their HTTP paths. The service receives only
  storage/lock/contract-reference primitives; never restore business-operation
  callbacks from `server.py`.
- Step 3 service modules must not import `get_db`, declare `Depends`, own an
  `APIRouter`, or import the complete application module.
- `mask_manifest_service.py` owns Step 5 semantic blocks, Manifest repair,
  draft/final persistence, stale-group pruning, and production Reveal builds.
  `mask_preview_service.py` owns exact single-slide preview builds and reports,
  while `mask_editor_routes.py` owns the seven unchanged editor HTTP routes.
  Mask services receive only their frozen dependency records and must not
  import `server`, `get_db`, declare `Depends`, or own an `APIRouter`.
- `diagnostics_routes.py` and `storyboard_background.py` own explicit
  `APIRouter` instances and are included directly by `server.py`.
- `storyboard_service.py` owns Step 2 prompt/profile normalization, planning,
  visual-contract composition, validation, repair, and manual skeleton logic.
  `storyboard_routes.py` owns all Step 2 and storyboard-template HTTP paths.
  Dependencies are configured explicitly with `StoryboardDependencies`; never
  restore Step 2 route decorators in `server.py` or import the server module
  from storyboard code.
- `visual_contract_service.py` owns shared visual-type normalization,
  narration deduplication, visual-contract normalization, and contract slide
  identity reads. It must remain independent of FastAPI, database wiring, and
  the application module; Storyboard, Narration, TTS, Image, and Mask code
  should reuse this source of truth instead of duplicating contract rules.
- `runtime_support.py` owns bounded subprocess execution, safe validator
  stdout parsing, fallback JSON reads, JSON Markdown cleanup, debug-text
  persistence, bounded numeric parsing, range parsing, and nested timeout
  detection. It must remain independent of FastAPI, database wiring, and the
  application module; `server.py` may re-export these helpers for compatibility
  but must not restore their implementations.
- `project_runtime_service.py` owns project-scoped logging and secret
  redaction, artifact locks, current-slide image completeness, Reveal Manifest
  synchronization, TTS artifact adapters, and commit-owning workflow
  transitions. Initial article import completes Step 1 and begins Step 2 in one
  commit through `begin_storyboard_after_article_import`. It must remain
  independent of FastAPI, database wiring, and the
  application module; `server.py` may re-export these helpers for compatibility
  but must not restore their implementations.
- `repository_paths.py` is the only source of repository-root, runtime-data,
  style asset, storyboard template, and Prompt template file paths. Consumers
  may re-export or monkey-patch imported module-level names for compatibility,
  but must not recalculate these paths or add application wiring to the path
  registry. Global image-style storage initialization remains owned by
  `global_image_style_service.py`.
- `narration_service.py` and `narration_routes.py` own Step 6 initialization,
  annotation, repair, persistence, and HTTP paths. `tts_service.py` and
  `tts_routes.py` own Step 7 synthesis, retry/status, audio download, and
  confirmation. Both services receive narrow dependency records and must not
  import the application module or restore route decorators in `server.py`.
- `narration_audio_service.py` owns narration source/TTS synchronization,
  Minimax delivery markup, subtitle segmentation, narration file persistence,
  and beat-aligned audio timeline rewriting. It receives only
  `NarrationAudioDependencies`; never move these implementations back into
  `server.py` or add FastAPI/database wiring to the service.
- `project_service.py` and `project_routes.py` own project creation, listing,
  detail, AI mode, and deletion. Creating a project must remain independent
  from importing article content; an empty Step 1 project is valid.
- `one_click_routes.py` owns the One-click HTTP contract.
  `one_click_orchestrator.py` receives only `OneClickDependencies`; it must
  never receive the FastAPI application or the complete `server` module.
- `pipeline_services.py` receives an immutable `PipelineOperations` graph,
  grouped into storyboard, images, Mask, narration, and media capabilities.
  Add a named operation when the pipeline grows; never pass `server`,
  `ModuleType`, or an application namespace into this facade.
- `pptx_routes.py` owns the explicit PPTX HTTP contract.
  `pptx_service.py` owns persistent export jobs and artifact lifecycle, and
  receives only `PptxServiceDependencies` (`session_factory`, `runs_root`, and
  an optional executor). Never restore `register_pptx_routes(server_module)`.
- `video_routes.py` owns the explicit render, polling, MP4 collection,
  download, speed-adjustment, deletion, and legacy final-video routes.
  `video_render_service.py` owns only orchestration, the in-memory task cache,
  and per-project locks. `video_job_store.py` owns persistent SQLite jobs,
  `video_artifact_service.py` owns MP4 paths, freshness metadata, speed
  variants, and registry lifecycle, while `remotion_runner.py` owns bounded
  subprocess stages and color validation. Shared configuration and errors live
  in `video_contracts.py`. Never collapse these boundaries or move Step 8
  workers and route decorators back into `server.py`.
- Never restore `_register(server_module)` in diagnostics, storyboard
  background, or One-click code.
- Access control is installed explicitly from `app_security.py`.
- `route_inventory.py` is the only production inspection API for the effective
  HTTP route surface. FastAPI may retain included routers as nested entries;
  diagnostics and route-contract tests must not infer public routes from a
  direct `app.routes` scan.
- `ai_provider_service.py` owns the shared OpenAI-compatible client,
  bounded image decoding, 1920x1080 white-canvas normalization, image
  response extraction, and provider-specific image-generation fallbacks.
  It must not import the application module or own FastAPI/database wiring.
- `tts_provider_service.py` owns provider aliases/defaults, credential
  resolution, environment-only secret transport, generic TTS command
  construction, and bounded retry/backoff behavior. It receives only
  `TtsProviderDependencies` and must not import `server` or own
  FastAPI/database wiring.
- `settings_service.py` owns global settings persistence, credential masking,
  masked-placeholder preservation, and provider connection checks.
  `config_portability_service.py` owns configuration export/import and
  validates every image reference before any write.
  `settings_routes.py` owns the eight unchanged `/api/settings` and
  `/api/config` HTTP routes, including bounded request streaming.
  These services receive only frozen dependency records and must not import
  `server`, `get_db`, declare `Depends`, or own an `APIRouter`.
- `article_service.py` owns the Step 1 article Prompt setting, topic-only
  generation contract, `inputs/article.md` source lifecycle, legacy brief
  migration, and change-triggered invalidation. `article_routes.py` owns the
  six unchanged settings/import/result HTTP routes. The service receives only
  `ArticleDependencies` and must not import `server`, `get_db`, declare
  `Depends`, or own an `APIRouter`.

Treat the remaining compatibility modules as migration debt, not as the normal
extension mechanism. Never reintroduce `sitecustomize.py`, polling installers,
or global standard-library monkey patches. New fixes should land in
`server.py`, normal service modules, `static/**`, or explicit application
startup code.

## Required Validation

Run before publishing:

```powershell
python -m compileall -q server.py runtime_support.py project_runtime_service.py repository_paths.py ai_provider_service.py tts_provider_service.py narration_audio_service.py visual_contract_service.py settings_service.py config_portability_service.py settings_routes.py article_service.py article_routes.py diagnostics_routes.py storyboard_background.py storyboard_service.py storyboard_routes.py global_image_style_service.py global_image_style_routes.py image_workflow_service.py image_workflow_routes.py visual_settings_service.py visual_settings_routes.py mask_manifest_service.py mask_preview_service.py mask_editor_routes.py narration_service.py narration_routes.py tts_service.py tts_routes.py one_click_orchestrator.py one_click_routes.py pptx_export.py pptx_service.py pptx_routes.py video_contracts.py video_job_store.py video_artifact_service.py remotion_runner.py video_render_service.py video_routes.py ai_mask_config.py ai_mask_engine.py ai_mask_routes.py ai_mask_semantic_matcher.py ai_mask_service.py project_style_context.py project_style_routes.py project_profile_service.py project_profile_store.py project_style_reference_service.py project_style_reference_store.py project_style_template_service.py image_style_reverse_service.py step3_image_style_service.py database.py database_migrations.py invalidation_service.py reveal_manifest_service.py scripts checks
node --check static/app.js
node --check static/flow.js
node checks/test_visible_flow.js
python -m pytest checks/test_database_migrations.py checks/test_invalidation_service.py -q
python -m pytest checks/test_source_runtime_safeguards.py -q
python checks/test_reveal_mask_integrity.py
python checks/test_reveal_pipeline_isolation.py
python checks/test_slide_visual_invalidation.py
python checks/test_audio_confirmation.py
python checks/test_audio_tail_padding.py
Push-Location scripts/remotion
npm install
npx tsc --noEmit -p tsconfig.json
Pop-Location
```

For a populated run:

```powershell
python scripts/validate_reveal_scene.py --run-dir runs/<run_id> --repo-root .
python scripts/validate_run_assets.py --run-dir runs/<run_id> --repo-root . --require-layered
```

Also verify the six visible steps in the local browser, including the exact
Mask preview and a rendered MP4.

## Prompt Optimization Policy

All new or modified production prompts must use
`.agents/skills/optimize-prompts/SKILL.md` before implementation.

- Trace the real system message, user payload, attached images/files, output
  parser, fallback, and downstream consumer. Do not optimize a template in
  isolation.
- Keep model input minimum and necessary: stable rules appear once in the
  system prompt; each request contains only facts needed for the model's next
  decision; deterministically derivable fields stay in code.
- Do not ask a model to return IDs or fields that are absent from its input, or
  values that the application can expand, sort, count, or validate itself.
- Preserve user-editable prompt settings and complete previews. Migrate only
  recognized legacy built-in defaults; never overwrite genuine custom prompts.
- Add tests that prove the runtime payload, output contract, migration, and UI
  preview remain aligned.

## Git Rules

Commit reusable application and framework files:

```text
server.py
database.py
config_store.py
static/**
scripts/**
checks/**
config/**
references/**
schemas/**
templates/**
README.md
AGENTS.md
.gitignore
.env.example
```

Do not commit:

```text
runs/**
outputs/**
logs/**
data/**
scripts/remotion/public/runtime/**
*.mp4
*.mp3
*.wav
*.srt
.env
API keys or other credentials
```

Merged temporary branches with `ahead_by=0` relative to `main` should be deleted after confirming no follow-up work depends on them.
