"""Runtime safeguards for the PPT visualization pipeline.

This module is loaded automatically by Python when the repository root is on
``sys.path``. It keeps the current application stable while large-file patching
of ``server.py`` is unavailable through the connector.

The safeguards are intentionally narrow:
- define ``props_started`` so Step 8 does not crash after build_remotion_props;
- skip the first duplicate Remotion render call that has no timeout;
- add bounded timeouts to known pipeline subprocesses;
- preserve edited narration when Step 6 init would otherwise overwrite it;
- normalize validate_render_color.py stdout to JSON so metadata writing is safe.

Disable with: PPT_STUDIO_DISABLE_RUNTIME_HOTFIXES=1
"""

from __future__ import annotations

import builtins
import json
import os
import re
import subprocess
import time
from pathlib import Path
from subprocess import CompletedProcess, TimeoutExpired
from typing import Any, Iterable


DISABLE_FLAG = "PPT_STUDIO_DISABLE_RUNTIME_HOTFIXES"
_PATCH_MARKER = "__ppt_pipeline_runtime_hotfix__"

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
