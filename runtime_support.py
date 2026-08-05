"""Shared subprocess, JSON, parsing, and timeout helpers."""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import signal
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional


logger = logging.getLogger("PPTStudio.RuntimeSupport")

_IS_WINDOWS = sys.platform.startswith("win")


def kill_process_tree(process: Any, timeout_sec: float = 5.0) -> None:
    """Terminate a process and its entire descendant tree.

    On Windows ``subprocess.run`` only terminates the direct child, leaving
    grandchildren (e.g. npx -> node -> ffmpeg) as orphans that keep consuming
    CPU and writing files. We use ``taskkill /T /F`` to kill the whole tree;
    on POSIX we send SIGKILL to the process group.
    """
    if process is None:
        return
    pid = int(getattr(process, "pid", 0) or 0)
    if pid <= 0:
        return
    try:
        if _IS_WINDOWS:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                timeout=timeout_sec,
            )
        else:
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                # Process group already gone; fall back to direct kill.
                os.kill(pid, signal.SIGKILL)
    except (subprocess.TimeoutExpired, ProcessLookupError, OSError):
        logger.debug("Failed to kill process tree for pid %s", pid, exc_info=True)


def run_subprocess_killable(
    args: List[str],
    *,
    timeout_sec: float,
    **kwargs: Any,
) -> subprocess.CompletedProcess:
    """Run a child process, and on timeout kill the full process tree without
    blocking forever on the orphan's pipe.

    Use this for long-running subprocesses that may spawn grandchildren (e.g.
    npx -> node -> ffmpeg, TTS commands). Bare ``subprocess.run`` kills only
    the direct child on timeout and its internal ``communicate`` then blocks
    until the orphan releases the pipe — which can hang forever. Here we poll
    ``communicate(timeout=...)`` so the timeout branch can call
    :func:`kill_process_tree` and return promptly.
    """
    start = time.monotonic()
    capture = bool(
        kwargs.get("capture_output")
        or kwargs.get("stdout")
        or kwargs.get("stderr")
    )
    popen_kwargs: Dict[str, Any] = {
        "stdout": subprocess.PIPE if capture else None,
        "stderr": subprocess.PIPE if capture else None,
    }
    for key in (
        "cwd",
        "env",
        "shell",
        "text",
        "encoding",
        "errors",
        "stdin",
        "close_fds",
    ):
        if key in kwargs:
            popen_kwargs[key] = kwargs[key]
    proc = subprocess.Popen(args, **popen_kwargs)
    stdout: Any = b""
    stderr: Any = b""
    try:
        while True:
            remaining = timeout_sec - (time.monotonic() - start)
            if remaining <= 0:
                kill_process_tree(proc)
                try:
                    proc.communicate(timeout=3.0)
                except subprocess.TimeoutExpired:
                    # Orphan still holds the pipe; close our end and move on.
                    for stream in (proc.stdout, proc.stderr):
                        if stream is not None:
                            try:
                                stream.close()
                            except OSError:
                                pass
                text_mode = bool(kwargs.get("text"))
                def _text(value: Any) -> str:
                    if isinstance(value, bytes):
                        return value.decode("utf-8", errors="replace")
                    return str(value or "")
                return subprocess.CompletedProcess(
                    args=args,
                    returncode=124,
                    stdout="" if text_mode else "",
                    stderr=(
                        f"Timed out after {timeout_sec:g} seconds. "
                        f"{_text(stderr)}"
                    ).strip(),
                )
            try:
                stdout, stderr = proc.communicate(timeout=min(remaining, 1.0))
                break
            except subprocess.TimeoutExpired:
                continue
    finally:
        if proc.poll() is None:
            kill_process_tree(proc)
    return subprocess.CompletedProcess(
        args=args,
        returncode=proc.returncode,
        stdout=stdout,
        stderr=stderr,
    )


def run_subprocess_bounded(
    args: List[str],
    *,
    timeout_sec: float,
    **kwargs: Any,
) -> subprocess.CompletedProcess:
    """Run a child process with a normalized timeout result.

    For commands that may spawn grandchildren and must not leave orphans or
    block on their pipes, prefer :func:`run_subprocess_killable` instead.
    """
    try:
        return subprocess.run(args, timeout=timeout_sec, **kwargs)
    except subprocess.TimeoutExpired as exc:
        stdout = (
            exc.stdout.decode("utf-8", errors="replace")
            if isinstance(exc.stdout, bytes)
            else str(exc.stdout or "")
        )
        stderr = (
            exc.stderr.decode("utf-8", errors="replace")
            if isinstance(exc.stderr, bytes)
            else str(exc.stderr or "")
        )
        return subprocess.CompletedProcess(
            args=args,
            returncode=124,
            stdout=stdout,
            stderr=(
                f"Timed out after {timeout_sec:g} seconds. {stderr}"
            ).strip(),
        )


def parse_json_process_stdout(
    result: subprocess.CompletedProcess,
) -> Dict[str, Any]:
    """Parse validator JSON without crashing on malformed stdout."""
    try:
        payload = json.loads(result.stdout or "{}")
    except (TypeError, json.JSONDecodeError):
        return {
            "parse_warning": (
                "validator stdout was not valid JSON"
            ),
            "raw_stdout": str(result.stdout or ""),
        }
    return (
        payload
        if isinstance(payload, dict)
        else {"result": payload}
    )


def read_json_file(path: str, fallback: Any) -> Any:
    if not os.path.exists(path):
        return copy.deepcopy(fallback)
    try:
        with open(
            path,
            "r",
            encoding="utf-8-sig",
        ) as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "Failed to read JSON file %s: %s",
            path,
            exc,
        )
        return copy.deepcopy(fallback)


def clean_json_markdown(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline:].strip()
        else:
            text = text[3:].strip()
        if text.endswith("```"):
            text = text[:-3].strip()

    first_brace = text.find("{")
    first_bracket = text.find("[")
    start_index = -1
    end_index = -1

    if (
        first_brace != -1
        and (
            first_bracket == -1
            or first_brace < first_bracket
        )
    ):
        start_index = first_brace
        end_index = text.rfind("}")
    elif first_bracket != -1:
        start_index = first_bracket
        end_index = text.rfind("]")

    if (
        start_index != -1
        and end_index != -1
        and end_index > start_index
    ):
        return text[start_index : end_index + 1]
    return text


def json_decode_context(
    text: str,
    exc: json.JSONDecodeError,
    radius: int = 300,
) -> str:
    start = max(0, exc.pos - radius)
    end = min(len(text), exc.pos + radius)
    return text[start:end]


def write_debug_text(
    run_dir: str,
    filename: str,
    content: str,
) -> str:
    planning_dir = os.path.join(run_dir, "planning")
    os.makedirs(planning_dir, exist_ok=True)
    path = os.path.join(planning_dir, filename)
    with open(path, "w", encoding="utf-8") as file:
        file.write(content)
    return path


def parse_int_setting(
    value: str,
    default: int,
    min_value: int,
    max_value: int,
) -> int:
    try:
        parsed = int(float(str(value).strip()))
    except Exception:
        parsed = default
    return max(min_value, min(max_value, parsed))


def is_timeout_exception(exc: BaseException) -> bool:
    seen: set[int] = set()
    current: Optional[BaseException] = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        name = type(current).__name__.lower()
        text = str(current).lower()
        if (
            isinstance(current, TimeoutError)
            or "timeout" in name
            or "timed out" in text
        ):
            return True
        current = current.__cause__ or current.__context__
    return False


def parse_range_text(
    value: Any,
    default_min: int,
    default_max: int,
) -> tuple[int, int]:
    numbers = [
        int(item)
        for item in re.findall(r"\d+", str(value or ""))
    ]
    if not numbers:
        return default_min, default_max
    if len(numbers) == 1:
        parsed_min = parsed_max = numbers[0]
    else:
        parsed_min, parsed_max = numbers[0], numbers[1]
    parsed_min = max(1, min(30, parsed_min))
    parsed_max = max(parsed_min, min(30, parsed_max))
    return parsed_min, parsed_max
