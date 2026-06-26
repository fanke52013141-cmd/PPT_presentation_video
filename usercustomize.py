"""User-level runtime hooks for PPT Visualization Studio.

Python's site module imports ``usercustomize`` after ``sitecustomize`` when it is
available on ``sys.path``. Keep small optional bridges here to avoid rewriting the
large runtime hotfix file for every isolated hook.
"""

from __future__ import annotations

import os
import subprocess
from typing import Any


_REMOTION_ENTRYPOINT_PATCH_MARKER = "__ppt_remotion_entrypoint_patch__"


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


def _find_token(command: list[str], token: str) -> int:
    token_lower = token.lower()
    for index, item in enumerate(command):
        if item.lower() == token_lower:
            return index
    return -1


def _normalize_remotion_render_entrypoint(command: list[str]) -> list[str]:
    """Force Remotion render commands to use the explicit source entrypoint.

    ``server.py`` builds ``npx remotion render ArticleVideo <output>``. Depending
    on Remotion CLI resolution and current working directory, that can fail to
    locate the composition. The project package script uses the safer explicit
    form ``npx remotion render src/index.tsx ArticleVideo <output>``.
    """

    render_index = _find_token(command, "render")
    composition_index = _find_token(command, "ArticleVideo")
    if render_index < 0 or composition_index < 0:
        return command
    if composition_index != render_index + 1:
        return command
    return command[: render_index + 1] + ["src/index.tsx"] + command[render_index + 1 :]


def _install_remotion_entrypoint_patch() -> None:
    current_run = subprocess.run
    if getattr(current_run, _REMOTION_ENTRYPOINT_PATCH_MARKER, False):
        return

    original_run = current_run

    def run_with_remotion_entrypoint(*popenargs: Any, **kwargs: Any):
        if os.environ.get("PPT_STUDIO_DISABLE_RUNTIME_HOTFIXES"):
            return original_run(*popenargs, **kwargs)

        command = _command_from_call(popenargs, kwargs)
        patched_command = _normalize_remotion_render_entrypoint(command)
        if patched_command != command:
            if "args" in kwargs:
                kwargs["args"] = patched_command
                return original_run(*popenargs, **kwargs)
            if popenargs:
                popenargs = (patched_command, *popenargs[1:])

        return original_run(*popenargs, **kwargs)

    setattr(run_with_remotion_entrypoint, _REMOTION_ENTRYPOINT_PATCH_MARKER, True)
    subprocess.run = run_with_remotion_entrypoint


try:
    import runtime_settings_mask  # noqa: F401
except Exception:
    # Optional hardening must never prevent the local app from starting.
    pass

try:
    import runtime_ai_mask  # noqa: F401
except Exception:
    # Optional AI Mask routes/UI must never prevent the local app from starting.
    pass

try:
    import runtime_storyboard_background  # noqa: F401
except Exception:
    # Optional storyboard background routes/UI must never prevent the local app from starting.
    pass

try:
    import runtime_storyboard_background_render  # noqa: F401
except Exception:
    # Optional final-video background postprocessing must never prevent startup.
    pass

try:
    import runtime_project_profile  # noqa: F401
except Exception:
    # Optional Project Profile routes/UI must never prevent startup.
    pass

try:
    import runtime_project_style_references  # noqa: F401
except Exception:
    # Optional project-local style reference images must never prevent startup.
    pass

try:
    import runtime_project_style_reference_manager  # noqa: F401
except Exception:
    # Optional project-local style reference image manager must never prevent startup.
    pass

_install_remotion_entrypoint_patch()
