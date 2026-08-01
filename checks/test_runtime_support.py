from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import runtime_support as runtime  # noqa: E402
import server  # noqa: E402


def test_module_owns_runtime_helpers_without_application_wiring() -> None:
    source = (ROOT / "runtime_support.py").read_text(
        encoding="utf-8"
    )
    server_source = (ROOT / "server.py").read_text(encoding="utf-8")
    for forbidden in (
        "APIRouter",
        "Depends(",
        "get_db",
        "server_module",
        "import server",
    ):
        assert forbidden not in source
    for function_name in (
        "run_subprocess_bounded",
        "parse_json_process_stdout",
        "read_json_file",
        "clean_json_markdown",
        "json_decode_context",
        "write_debug_text",
        "parse_int_setting",
        "is_timeout_exception",
        "parse_range_text",
    ):
        assert f"def {function_name}(" in source
        assert f"def {function_name}(" not in server_source
        assert getattr(server, function_name) is getattr(
            runtime,
            function_name,
        )


def test_bounded_subprocess_normalizes_text_and_byte_timeouts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runtime.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(
                ["demo"],
                timeout=4,
                output=b"partial",
                stderr="busy",
            )
        ),
    )

    result = runtime.run_subprocess_bounded(
        ["demo"],
        timeout_sec=4,
    )

    assert result.returncode == 124
    assert result.stdout == "partial"
    assert result.stderr == "Timed out after 4 seconds. busy"


def test_json_stdout_and_file_fallbacks_are_structured(
    tmp_path: Path,
) -> None:
    assert runtime.parse_json_process_stdout(
        subprocess.CompletedProcess([], 0, '{"ok": true}', "")
    ) == {"ok": True}
    assert runtime.parse_json_process_stdout(
        subprocess.CompletedProcess([], 0, "[1, 2]", "")
    ) == {"result": [1, 2]}
    assert runtime.parse_json_process_stdout(
        subprocess.CompletedProcess([], 0, "bad", "")
    ) == {
        "parse_warning": "validator stdout was not valid JSON",
        "raw_stdout": "bad",
    }

    fallback = {"items": []}
    missing = runtime.read_json_file(
        str(tmp_path / "missing.json"),
        fallback,
    )
    missing["items"].append("changed")
    assert fallback == {"items": []}

    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text("{bad", encoding="utf-8")
    assert runtime.read_json_file(
        str(invalid_path),
        fallback,
    ) == fallback

    valid_path = tmp_path / "valid.json"
    valid_path.write_text(
        json.dumps({"value": 1}),
        encoding="utf-8-sig",
    )
    assert runtime.read_json_file(
        str(valid_path),
        fallback,
    ) == {"value": 1}


def test_json_cleaning_and_debug_context_are_preserved(
    tmp_path: Path,
) -> None:
    assert runtime.clean_json_markdown(
        "说明\n```json\n{\"ok\": true}\n```\n结束"
    ) == '{"ok": true}'
    assert runtime.clean_json_markdown(
        "前缀 [1, 2] 后缀"
    ) == "[1, 2]"

    invalid = '{"value": }'
    with pytest.raises(json.JSONDecodeError) as exc_info:
        json.loads(invalid)
    assert "value" in runtime.json_decode_context(
        invalid,
        exc_info.value,
        radius=20,
    )

    debug_path = Path(
        runtime.write_debug_text(
            str(tmp_path),
            "failure.txt",
            "details",
        )
    )
    assert debug_path == tmp_path / "planning" / "failure.txt"
    assert debug_path.read_text(encoding="utf-8") == "details"


def test_numeric_ranges_and_nested_timeouts_are_bounded() -> None:
    assert runtime.parse_int_setting("42.9", 10, 1, 50) == 42
    assert runtime.parse_int_setting("bad", 10, 1, 50) == 10
    assert runtime.parse_int_setting("100", 10, 1, 50) == 50
    assert runtime.parse_range_text("4-8", 2, 6) == (4, 8)
    assert runtime.parse_range_text("99", 2, 6) == (30, 30)
    assert runtime.parse_range_text("none", 2, 6) == (2, 6)

    try:
        try:
            raise TimeoutError("late")
        except TimeoutError as exc:
            raise RuntimeError("wrapped") from exc
    except RuntimeError as wrapped:
        assert runtime.is_timeout_exception(wrapped)
    assert not runtime.is_timeout_exception(
        ValueError("ordinary failure")
    )
