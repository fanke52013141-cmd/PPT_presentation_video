"""Runtime safeguards for the PPT visualization pipeline.

This module is loaded automatically by Python when the repository root is on
``sys.path``. It keeps the current application stable while large-file patching
of ``server.py`` is unavailable through the connector.

The safeguards are intentionally narrow:
- define ``props_started`` so Step 8 does not crash after build_remotion_props;
- skip the first duplicate Remotion render call that has no timeout;
- add bounded timeouts to known pipeline subprocesses;
- preserve edited narration when Step 6 init would otherwise overwrite it;
- reconcile reveal_manifest.json groups with visual_contract.json at runtime;
- normalize validate_render_color.py stdout to JSON so metadata writing is safe.

Disable with: PPT_STUDIO_DISABLE_RUNTIME_HOTFIXES=1
"""

from __future__ import annotations

import builtins
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from subprocess import CompletedProcess, TimeoutExpired
from types import ModuleType
from typing import Any, Iterable


DISABLE_FLAG = "PPT_STUDIO_DISABLE_RUNTIME_HOTFIXES"
_PATCH_MARKER = "__ppt_pipeline_runtime_hotfix__"
_RECONCILE_PATCH_MARKER = "__ppt_reveal_manifest_reconcile_patch__"

# ``server.py`` reads this name without defining it. Name resolution falls back
# to builtins, so this prevents a NameError without replacing the large file.
builtins.props_started = time.time()


def _as_command_list(args: Any) -> list[str]:
    if isinstance(args, (list, tuple)):
        return [str(item) for item in args]
    if args is None:
        return []
    return [str(args)]


def _command_from_call(popenargs: tuple[Any, ...], kwargs: dict[str, Any]) -> list[str]:
    if "args" in kwargs:
        return _as_command_list(kwargs.get("args"))
    if popenargs:
        return _as_command_list(popenargs[0])
    return []


def _normalized_command(command: Iterable[str]) -> str:
    return " ".join(command).replace("\\", "/")


def _contains_script(command_text: str, script_name: str) -> bool:
    return script_name in command_text


def _is_remotion_render(command: list[str]) -> bool:
    lowered = [item.lower() for item in command]
    return "remotion" in lowered and "render" in lowered and "articlevideo" in lowered


def _arg_value(command: list[str], flag: str) -> str | None:
    try:
        index = command.index(flag)
    except ValueError:
        return None
    if index + 1 >= len(command):
        return None
    return command[index + 1]


def _default_timeout(command: list[str], command_text: str) -> int | None:
    if _contains_script(command_text, "scripts/generic_tts.py"):
        return 180
    if _contains_script(command_text, "scripts/bind_reveal_timeline.py"):
        return 60
    if _contains_script(command_text, "scripts/build_remotion_props.py"):
        return 120
    if _contains_script(command_text, "scripts/build_reveal_scene.py"):
        return 180
    if _contains_script(command_text, "scripts/validate_reveal_scene.py"):
        return 60
    if command and os.path.basename(command[0]).lower() in {"npm", "npm.cmd"}:
        if len(command) > 1 and command[1].lower() == "install":
            return 600
    return None


def _timeout_completed_process(args: Any, timeout_sec: int) -> CompletedProcess[str]:
    return CompletedProcess(
        args=args,
        returncode=124,
        stdout="",
        stderr=f"Timed out after {timeout_sec} seconds by sitecustomize.py runtime safeguard.",
    )


def _json_safe_color_validation(result: CompletedProcess[str]) -> CompletedProcess[str]:
    try:
        json.loads(result.stdout or "{}")
        return result
    except Exception:
        safe_stdout = json.dumps(
            {
                "parse_warning": "validate_render_color.py stdout was not valid JSON",
                "raw_stdout": result.stdout or "",
            },
            ensure_ascii=False,
        )
        return CompletedProcess(
            args=result.args,
            returncode=result.returncode,
            stdout=safe_stdout,
            stderr=result.stderr,
        )


def _clean_tts_text(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"<#\d+(?:\.\d+)?#>", "", text)
    text = re.sub(r"\((?:breath|sighs|chuckle|emm|laughs|inhale|exhale|gasps|whistles|applause)\)", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _beat_tts_text(beat: dict[str, Any]) -> str:
    return str(beat.get("tts_text") or beat.get("spoken_text") or beat.get("source_text") or "").strip()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _preserve_existing_narration_init(command: list[str], command_text: str) -> CompletedProcess[str] | None:
    if not _contains_script(command_text, "scripts/write_narration_from_visual_contract.py"):
        return None
    if "--overwrite" not in command:
        return None
    run_dir_raw = _arg_value(command, "--run-dir")
    if not run_dir_raw:
        return None

    run_dir = Path(run_dir_raw)
    beats_path = run_dir / "planning" / "narration_beats.json"
    if not beats_path.exists():
        return None

    try:
        beats_payload = json.loads(beats_path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return CompletedProcess(
            args=command,
            returncode=1,
            stdout="",
            stderr=f"Existing narration_beats.json could not be read: {exc}",
        )

    slides = beats_payload.get("slides") if isinstance(beats_payload, dict) else None
    if not isinstance(slides, list):
        return None

    for slide_data in slides:
        if not isinstance(slide_data, dict):
            continue
        slide_id = str(slide_data.get("slide_id") or "").strip()
        if not slide_id:
            continue
        slide_beats = slide_data.get("beats") if isinstance(slide_data.get("beats"), list) else []
        slide_dir = run_dir / "slides" / slide_id
        slide_dir.mkdir(parents=True, exist_ok=True)
        _write_json(slide_dir / "narration_beats.json", {"slide_id": slide_id, "beats": slide_beats})
        narration_lines = [_clean_tts_text(_beat_tts_text(beat)) for beat in slide_beats if isinstance(beat, dict)]
        tts_lines = [_beat_tts_text(beat) for beat in slide_beats if isinstance(beat, dict)]
        (slide_dir / "narration.txt").write_text("\n".join(narration_lines).strip() + "\n", encoding="utf-8")
        (slide_dir / "tts_text.txt").write_text("\n".join(tts_lines).strip() + "\n", encoding="utf-8")

    return CompletedProcess(
        args=command,
        returncode=0,
        stdout="Preserved existing narration_beats.json during Step 6 init.\n",
        stderr="",
    )


def _group_id(group: dict[str, Any]) -> str:
    return str(group.get("id") or group.get("group_id") or group.get("visual_group_id") or "").strip()


def _is_manual_group(group: dict[str, Any]) -> bool:
    return _group_id(group).startswith("manual_group_")


def _is_painted_group(group: dict[str, Any]) -> bool:
    strokes = group.get("strokes") or group.get("paint_strokes") or group.get("manual_mask_strokes")
    if isinstance(strokes, list) and strokes:
        return True
    manual_mask = group.get("manual_mask")
    if isinstance(manual_mask, dict):
        mask_strokes = manual_mask.get("strokes") or manual_mask.get("paint_strokes")
        if isinstance(mask_strokes, list) and mask_strokes:
            return True
    return any(key in group for key in ("mask", "mask_path", "mask_url", "mask_data"))


def _contract_group_id(group: dict[str, Any], slide_id: str, index: int) -> str:
    explicit = str(group.get("id") or group.get("group_id") or group.get("visual_group_id") or "").strip()
    return explicit or f"{slide_id}_group_{index:03d}"


def _default_box(index: int) -> dict[str, int]:
    row = max(0, index - 1)
    return {"x": 160, "y": min(760, 140 + row * 110), "w": 1600, "h": 92}


def _normalized_box(value: Any, fallback_index: int) -> dict[str, Any]:
    if isinstance(value, dict):
        try:
            return {
                "x": float(value.get("x", 0)),
                "y": float(value.get("y", 0)),
                "w": float(value.get("w", 0)),
                "h": float(value.get("h", 0)),
            }
        except Exception:
            return _default_box(fallback_index)
    if isinstance(value, list) and len(value) == 4:
        try:
            x1, y1, x2, y2 = [float(item) for item in value]
            return {"x": x1, "y": y1, "w": max(1.0, x2 - x1), "h": max(1.0, y2 - y1)}
        except Exception:
            return _default_box(fallback_index)
    return _default_box(fallback_index)


def _narration_beat_id_for_group(contract_slide: dict[str, Any], group: dict[str, Any]) -> str:
    existing = str(group.get("narration_beat_id") or group.get("beat_id") or "").strip()
    if existing:
        return existing
    group_id = str(group.get("id") or group.get("group_id") or "").strip()
    content_unit_id = str(group.get("content_unit_id") or "").strip()
    for beat in contract_slide.get("narration_beats", []) or []:
        if not isinstance(beat, dict):
            continue
        beat_id = str(beat.get("id") or "").strip()
        if not beat_id:
            continue
        if group_id and str(beat.get("group_id") or "").strip() == group_id:
            return beat_id
        if content_unit_id and str(beat.get("content_unit_id") or "").strip() == content_unit_id:
            return beat_id
    return ""


def _merge_contract_group(
    slide_id: str,
    contract_slide: dict[str, Any],
    contract_group: dict[str, Any],
    old_group: dict[str, Any] | None,
    index: int,
) -> dict[str, Any]:
    group_id = _contract_group_id(contract_group, slide_id, index)
    merged: dict[str, Any] = dict(old_group or {})
    merged["id"] = group_id
    merged["visual_group_id"] = group_id

    for field in (
        "role",
        "content_unit_id",
        "visible_text",
        "visual_anchor",
        "mask_target",
        "reveal_order",
    ):
        value = contract_group.get(field)
        if value not in (None, ""):
            merged[field] = value

    beat_id = _narration_beat_id_for_group(contract_slide, contract_group)
    if beat_id:
        merged["narration_beat_id"] = beat_id

    if "box" in contract_group:
        merged["box"] = _normalized_box(contract_group.get("box"), index)
    elif "bbox" in contract_group:
        merged["box"] = _normalized_box(contract_group.get("bbox"), index)
    else:
        merged.setdefault("box", _default_box(index))

    merged.setdefault("padding", {"x": 12, "y": 12})
    merged.setdefault("z_index", index)
    merged.setdefault("review_status", "pending")
    merged.setdefault("reveal", {"action": "brush_reveal", "duration_sec": 0.75})
    return merged


def _dedupe_groups(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        group_id = _group_id(group)
        if not group_id or group_id in seen:
            continue
        seen.add(group_id)
        result.append(group)
    return result


def _reconciled_slide(
    contract_slide: dict[str, Any],
    old_slide: dict[str, Any] | None,
    slide_index: int,
) -> dict[str, Any]:
    slide_id = str(contract_slide.get("slide_id") or f"slide_{slide_index:03d}").strip()
    slide: dict[str, Any] = dict(old_slide or {})
    slide["slide_id"] = slide_id
    slide.setdefault("image", f"slides/{slide_id}/visual_draft.png")
    slide.setdefault("status", "pending")
    slide.setdefault("canvas", {"w": 1920, "h": 1080, "background": "#FEFDF9"})

    old_candidates: list[dict[str, Any]] = []
    if old_slide:
        for field in ("semantic_blocks", "groups"):
            values = old_slide.get(field)
            if isinstance(values, list):
                old_candidates.extend(group for group in values if isinstance(group, dict))
    old_by_id = {_group_id(group): group for group in old_candidates if _group_id(group)}

    contract_groups = [
        group for group in contract_slide.get("visual_groups", []) or []
        if isinstance(group, dict)
    ]
    contract_ids = {
        _contract_group_id(group, slide_id, index)
        for index, group in enumerate(contract_groups, start=1)
    }

    semantic_blocks = [
        _merge_contract_group(
            slide_id=slide_id,
            contract_slide=contract_slide,
            contract_group=group,
            old_group=old_by_id.get(_contract_group_id(group, slide_id, index)),
            index=index,
        )
        for index, group in enumerate(contract_groups, start=1)
    ]

    manual_groups = [
        dict(group) for group in old_candidates
        if _is_manual_group(group)
    ]
    semantic_blocks = _dedupe_groups(semantic_blocks + manual_groups)

    # ``groups`` is the build input. Preserve painted groups and manual groups;
    # include newly added contract groups so the UI can immediately expose them.
    build_groups = []
    for block in semantic_blocks:
        group_id = _group_id(block)
        old_group = old_by_id.get(group_id)
        if old_group and (_is_painted_group(old_group) or _is_manual_group(old_group)):
            merged = dict(block)
            merged.update(old_group)
            merged["id"] = group_id
            build_groups.append(merged)
        elif group_id in contract_ids:
            build_groups.append(dict(block))
    slide["semantic_blocks"] = semantic_blocks
    slide["groups"] = _dedupe_groups(build_groups)
    return slide


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _install_reveal_manifest_reconcile_patch(server_module: ModuleType) -> bool:
    if getattr(server_module, _RECONCILE_PATCH_MARKER, False):
        return True
    required = (
        "read_contract_slide_ids",
        "reveal_lock_for",
        "write_json_atomic",
    )
    if not all(hasattr(server_module, name) for name in required):
        return False

    def sync_reveal_manifest_to_contract(project: Any, slide_ids: list[str] | None = None) -> bool:
        current_slide_ids = slide_ids if slide_ids is not None else server_module.read_contract_slide_ids(project.run_dir)
        if not current_slide_ids:
            return False

        run_dir = Path(project.run_dir)
        manifest_path = run_dir / "reveal_manifest.json"
        contract_path = run_dir / "planning" / "visual_contract.json"
        if not manifest_path.exists() or not contract_path.exists():
            return False

        with server_module.reveal_lock_for(project):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
                contract = json.loads(contract_path.read_text(encoding="utf-8-sig"))
            except Exception:
                return False

            if not isinstance(manifest, dict) or not isinstance(contract, dict):
                return False
            old_manifest_json = _stable_json(manifest)

            contract_slides_by_id = {
                str(slide.get("slide_id") or "").strip(): slide
                for slide in contract.get("slides", []) or []
                if isinstance(slide, dict) and str(slide.get("slide_id") or "").strip()
            }
            old_slides_by_id = {
                str(slide.get("slide_id") or "").strip(): slide
                for slide in manifest.get("slides", []) or []
                if isinstance(slide, dict) and str(slide.get("slide_id") or "").strip()
            }

            reconciled_slides: list[dict[str, Any]] = []
            for index, slide_id in enumerate(current_slide_ids, start=1):
                contract_slide = contract_slides_by_id.get(str(slide_id))
                if not contract_slide:
                    continue
                reconciled_slides.append(
                    _reconciled_slide(
                        contract_slide=contract_slide,
                        old_slide=old_slides_by_id.get(str(slide_id)),
                        slide_index=index,
                    )
                )

            manifest.setdefault("version", "reveal_v1")
            manifest["slides"] = reconciled_slides
            if _stable_json(manifest) == old_manifest_json:
                return False

            server_module.write_json_atomic(str(manifest_path), manifest)
            return True

    sync_reveal_manifest_to_contract.__name__ = "sync_reveal_manifest_to_contract"
    sync_reveal_manifest_to_contract.__doc__ = "Runtime-patched slide and group-level reveal manifest reconciliation."
    server_module.sync_reveal_manifest_to_contract = sync_reveal_manifest_to_contract
    setattr(server_module, _RECONCILE_PATCH_MARKER, True)
    return True


def _candidate_server_modules() -> list[ModuleType]:
    modules: list[ModuleType] = []
    for module in list(sys.modules.values()):
        if not isinstance(module, ModuleType):
            continue
        if hasattr(module, "sync_reveal_manifest_to_contract") and hasattr(module, "Project"):
            modules.append(module)
    return modules


def _install_reconcile_patch_when_server_is_ready() -> None:
    def worker() -> None:
        while not os.environ.get(DISABLE_FLAG):
            for module in _candidate_server_modules():
                if _install_reveal_manifest_reconcile_patch(module):
                    return
            time.sleep(0.1)

    threading.Thread(target=worker, name="ppt-reveal-reconcile-patch", daemon=True).start()


def _install_subprocess_run_guard() -> None:
    current_run = subprocess.run
    if getattr(current_run, _PATCH_MARKER, False):
        return

    original_run = current_run

    def guarded_run(*popenargs: Any, **kwargs: Any) -> CompletedProcess[Any]:
        if os.environ.get(DISABLE_FLAG):
            return original_run(*popenargs, **kwargs)

        command = _command_from_call(popenargs, kwargs)
        command_text = _normalized_command(command)

        narration_preserve_result = _preserve_existing_narration_init(command, command_text)
        if narration_preserve_result is not None:
            return narration_preserve_result

        # ``server.py`` currently calls Remotion twice. The first call is outside
        # the timeout-protected try block. Treat it as a skipped preflight and let
        # the second call do the actual render with its existing timeout handling.
        if _is_remotion_render(command) and "timeout" not in kwargs:
            return CompletedProcess(
                args=command,
                returncode=0,
                stdout="Skipped duplicate pre-timeout Remotion render by sitecustomize.py.\n",
                stderr="",
            )

        # Keep Step 8 elapsed logging meaningful when build_remotion_props starts.
        if _contains_script(command_text, "scripts/build_remotion_props.py"):
            builtins.props_started = time.time()

        timeout_sec = None
        if "timeout" not in kwargs:
            timeout_sec = _default_timeout(command, command_text)
            if timeout_sec is not None:
                kwargs["timeout"] = timeout_sec

        try:
            result = original_run(*popenargs, **kwargs)
        except TimeoutExpired:
            if timeout_sec is not None:
                args = kwargs.get("args") if "args" in kwargs else (popenargs[0] if popenargs else command)
                return _timeout_completed_process(args, timeout_sec)
            raise

        if _contains_script(command_text, "scripts/validate_render_color.py") and result.returncode == 0:
            return _json_safe_color_validation(result)
        return result

    setattr(guarded_run, _PATCH_MARKER, True)
    subprocess.run = guarded_run


_install_subprocess_run_guard()
_install_reconcile_patch_when_server_is_ready()
