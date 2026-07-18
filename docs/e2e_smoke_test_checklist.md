# End-to-end smoke test checklist

Use this checklist after pipeline fixes, runtime hotfix changes, frontend flow
changes, or security hardening changes.

The goal is not to judge final visual quality. The goal is to catch regressions
that break the happy path from article import to rendered video.

## Step numbering note

The browser UI has six user-visible steps, while the backend and historical validators still use internal Step numbers.

| UI step | Internal stage in this checklist |
| --- | --- |
| UI Step 1 Import article | Step 1 import |
| UI Step 2 Storyboard | Step 2 visual contract |
| UI Step 3 Images | Step 3 images and Step 4 confirmation |
| UI Step 4 Mask | Step 5 mask / reveal manifest |
| UI Step 5 Narration and audio | Step 6 narration and Step 7 TTS |
| UI Step 6 Render video | Step 8 Remotion render |

When this checklist says Step 5/6/7/8, it refers to the internal artifact/API stage.

## 0. Preflight

Run from the repository root:

```bash
python scripts/check_python_startup_hooks.py
python scripts/check_runtime_hotfixes.py
PPT_STUDIO_MASK_SETTINGS_SECRETS=1 python scripts/check_runtime_settings_mask.py
```

Expected result: all scripts print `OK` or pass summaries with no failures.

Optional hardened mode:

```bash
export PPT_STUDIO_ACCESS_TOKEN="replace-with-long-random-token"
export PPT_STUDIO_MASK_SETTINGS_SECRETS=1
export PPT_STUDIO_ALLOWED_ORIGINS="http://127.0.0.1:8000,http://localhost:8000"
python server.py
```

First browser visit in hardened mode:

```text
http://127.0.0.1:8000/?access_token=replace-with-long-random-token
```

## 1. Create project

- Create a new project with a short name.
- Use a small but realistic article, around 300-800 Chinese characters.
- Include a title, 2-4 paragraphs, and at least one concrete example or number.

Expected:

- Project appears in the project list.
- Current visible step is UI Step 1.
- `runs/<project_id>/inputs/` and `runs/<project_id>/planning/` exist.

## 2. Step 1: import article

Action:

- Paste the article.
- Import it.

Expected UI behavior:

- UI Step 1 completes.
- UI Step 2 becomes available.

Expected artifacts:

- `inputs/article.md`
- `inputs/article.md` is non-empty and remains the sole article source.
- New runs do not create `planning/article_brief.json`; legacy files are read only for one-time migration.

Artifact check:

```bash
python scripts/check_smoke_artifacts.py --run-dir runs/<project_id> --stage step1
```

## 3. Step 2: generate storyboard / visual contract

Action:

- Generate or save the storyboard.
- Make one small edit if possible: rename a visible text item or reorder one slide.
- Save.

Expected UI behavior:

- UI Step 2 completes.
- Slide list is stable after refresh.
- No blank slide ids.

Expected artifacts:

- `planning/visual_contract.json`
- `topic.topic_summary` is present.
- Each slide has `slide_id` and at least one `visual_group` or post-design visual anchor.

Artifact check:

```bash
python scripts/check_smoke_artifacts.py --run-dir runs/<project_id> --stage step2
```

## 4. Step 3: generate or upload visual drafts

Action:

- Generate images, or upload one image per slide.
- Use the normal Step 3 confirmation button once.
- Also test direct navigation toward UI Step 4 / internal Step 5 from UI Step 3 if the UI exposes it.

Expected UI behavior:

- Direct UI Step 3 -> UI Step 4 navigation confirms images first.
- UI Step 4 shows Mask annotation UI, not a stale or empty state.

Expected artifacts:

- `slides/<slide_id>/visual_draft.png` or another non-empty image per slide.
- `reveal_manifest.json` may now exist, depending on the path taken.

Artifact check:

```bash
python scripts/check_smoke_artifacts.py --run-dir runs/<project_id> --stage step3
```

## 5. Step 5: Mask annotation

Action:

- Paint at least one visible Mask group on at least one slide.
- Add or keep one manual group if the UI path supports it.
- Save draft once.
- Save final result once.

Expected UI behavior:

- Existing painted masks are not lost after refresh.
- New visual groups from Step 2 appear in UI Step 4.
- Deleted Step 2 groups do not linger unless they are manual groups.
- Save with normal behavior builds reveal assets.

Expected artifacts:

- `reveal_manifest.json`
- each contract slide appears in manifest
- group or semantic block structure exists
- painted mask data is retained where painted

Artifact check:

```bash
python scripts/check_smoke_artifacts.py --run-dir runs/<project_id> --stage step5
```

## 6. Step 6: narration

Action:

- Initialize narration.
- Edit one narration beat.
- Leave UI Step 5 and return to it, or refresh the page.

Expected UI behavior:

- Edited narration is preserved.
- Step 6 init does not overwrite existing `narration_beats.json`.

Expected artifacts:

- `planning/narration_beats.json`, or per-slide narration files:
  - `slides/<slide_id>/narration_beats.json`
  - `slides/<slide_id>/narration.txt`
  - `slides/<slide_id>/tts_text.txt`

Artifact check:

```bash
python scripts/check_smoke_artifacts.py --run-dir runs/<project_id> --stage step6
```

## 7. Step 7: audio generation

Action:

- Generate TTS audio.
- Confirm audio.

Expected UI behavior:

- TTS subprocess does not hang forever.
- Audio confirmation unlocks UI Step 6 / internal Step 8.

Expected artifacts:

- at least one non-empty `.mp3`, `.wav`, `.m4a`, `.aac`, or `.ogg` under `run_dir`
- animation timeline files may be generated or refreshed

Artifact check:

```bash
python scripts/check_smoke_artifacts.py --run-dir runs/<project_id> --stage step7
```

## 8. Step 8: render video

Action:

- Start video render from UI Step 6.
- Wait for completion.

Expected UI behavior:

- No `props_started` NameError.
- Only one effective Remotion render is performed.
- Long subprocesses have bounded timeout behavior.
- Render produces a usable video file.

Expected artifacts:

- `remotion_props.json`
- at least one non-empty `.mp4`, `.mov`, or `.webm` under `run_dir`

Artifact check:

```bash
python scripts/check_smoke_artifacts.py --run-dir runs/<project_id> --stage step8
```

## 9. Settings and security checks

Default local mode:

- With no environment variables, the app should behave as before.

Hardened mode:

- Start with `PPT_STUDIO_ACCESS_TOKEN`.
- Visiting `/api/projects` without a token should return 401.
- Visiting `/?access_token=<token>` should set the cookie and allow normal UI use.
- If `PPT_STUDIO_MASK_SETTINGS_SECRETS=1`, `GET /api/settings` should return masked credential fields.
- Saving settings with masked placeholders should not erase stored credentials.

## 10. Pass/fail criteria

Pass when:

- All artifact checks up to the tested stage have no `FAIL` entries.
- Warnings are understood and acceptable for the specific stage.
- The UI reaches the target stage without stale state or blocking errors.
- Step 8 produces a non-empty rendered video when the full pipeline is tested.

Fail when:

- Any artifact checker reports `FAIL`.
- UI Step 3 can enter UI Step 4 / internal Step 5 without confirmed images.
- Step 5 loses painted masks after save/refresh.
- Step 6 overwrites edited narration.
- Step 8 throws `NameError`, hangs indefinitely, or produces no video.

## 11. Reporting template

```text
Project id:
Run dir:
Server command:
Security env enabled: yes/no
Highest tested stage:
Artifact checker command:
Artifact checker result:
UI failures:
Logs / traceback:
Notes:
```
