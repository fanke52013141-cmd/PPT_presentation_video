"""Shared subprocess, JSON, parsing, and timeout helpers."""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import subprocess
from typing import Any, Dict, List, Optional


logger = logging.getLogger("PPTStudio.RuntimeSupport")


def run_subprocess_bounded(
    args: List[str],
    *,
    timeout_sec: float,
    **kwargs: Any,
) -> subprocess.CompletedProcess:
    """Run a child process with a normalized timeout result."""
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
