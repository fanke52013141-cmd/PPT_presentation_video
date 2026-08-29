from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server  # noqa: E402
import tts_provider_service as provider  # noqa: E402


def replace_dependencies(
    **changes: Any,
) -> provider.TtsProviderDependencies:
    dependencies = provider._deps()
    values = {
        field: getattr(dependencies, field)
        for field in dependencies.__dataclass_fields__
    }
    values.update(changes)
    return provider.TtsProviderDependencies(**values)


def test_tts_provider_module_has_no_application_wiring() -> None:
    source = (ROOT / "tts_provider_service.py").read_text(
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
        "normalize_tts_provider",
        "configured_tts_api_key",
        "provider_tts_command",
        "run_tts_command_with_retries",
    ):
        assert f"def {function_name}(" in source
        assert f"def {function_name}(" not in server_source
    assert server.provider_tts_command is provider.provider_tts_command
    assert (
        server.run_tts_command_with_retries
        is provider.run_tts_command_with_retries
    )


def test_provider_aliases_and_defaults_are_preserved() -> None:
    assert provider.normalize_tts_provider(None) == "minimax"
    assert provider.normalize_tts_provider(" Doubao ") == (
        "volcengine_seed"
    )
    assert provider.normalize_tts_provider("dashscope") == (
        "aliyun_cosyvoice"
    )
    assert provider.normalize_tts_provider("tencent") == "tencent_tts"
    assert provider.tts_provider_defaults("unknown") == (
        provider.TTS_PROVIDER_DEFAULTS["minimax"]
    )


def test_credential_priority_is_preserved() -> None:
    original = provider._deps()
    try:
        provider.configure_tts_provider_dependencies(
            replace_dependencies(
                get_setting=lambda key: {
                    "tts_api_key": "stored-api",
                    "tts_secret_key": "stored-secret",
                }.get(key, ""),
            )
        )
        with patch.dict(
            os.environ,
            {
                "MINIMAX_API_KEY": "environment-api",
                "TENCENTCLOUD_SECRET_KEY": "environment-secret",
            },
            clear=False,
        ):
            assert (
                provider.configured_tts_api_key(
                    "minimax",
                    "explicit-api",
                )
                == "explicit-api"
            )
            assert (
                provider.configured_tts_api_key("minimax")
                == "stored-api"
            )
            assert (
                provider.configured_tts_secret_key("tencent_tts")
                == "stored-secret"
            )

        provider.configure_tts_provider_dependencies(
            replace_dependencies(
                get_setting=lambda _key: "",
            )
        )
        with patch.dict(
            os.environ,
            {
                "MINIMAX_API_KEY": "environment-api",
                "TENCENTCLOUD_SECRET_KEY": "environment-secret",
            },
            clear=False,
        ):
            assert (
                provider.configured_tts_api_key("minimax")
                == "environment-api"
            )
            assert (
                provider.configured_tts_secret_key("tencent_tts")
                == "environment-secret"
            )
    finally:
        provider.configure_tts_provider_dependencies(original)


def test_retry_contract_is_preserved() -> None:
    logs: list[tuple[Any, ...]] = []
    sleeps: list[int] = []
    calls: list[dict[str, Any]] = []
    results = [
        subprocess.CompletedProcess(
            ["tts"],
            1,
            "stdout-1",
            "stderr-1",
        ),
        subprocess.CompletedProcess(
            ["tts"],
            2,
            "stdout-2",
            "stderr-2",
        ),
        subprocess.CompletedProcess(
            ["tts"],
            0,
            "success",
            "",
        ),
    ]

    def run_process(
        _args: list[str],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(kwargs)
        return results[len(calls) - 1]

    original = provider._deps()
    provider.configure_tts_provider_dependencies(
        replace_dependencies(
            write_project_log=lambda *args, **kwargs: logs.append(
                (args, kwargs)
            ),
        )
    )
    try:
        with patch(
            "tts_provider_service.run_subprocess_killable",
            side_effect=run_process,
        ), patch(
            "tts_provider_service.time.sleep",
            side_effect=sleeps.append,
        ):
            result = provider.run_tts_command_with_retries(
                SimpleNamespace(id="project"),
                "slide_001",
                ["tts"],
                {"API_KEY": "secret"},
            )
    finally:
        provider.configure_tts_provider_dependencies(original)

    assert result == {
        "ok": True,
        "returncode": 0,
        "stdout": "success",
        "stderr": "",
        "attempts": 3,
    }
    assert sleeps == [4, 8]
    assert len(logs) == 2
    assert [entry[1]["attempt"] for entry in logs] == [1, 2]
    # TTS 子进程现在经注入的 run_subprocess_killable 执行（审查 M-09/L 系列），
    # 其超时参数名为 timeout_sec（进程树击杀契约），不再是 subprocess.run 的 timeout。
    assert all(
        call
        == {
            "capture_output": True,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "timeout_sec": provider.STEP7_TTS_PROCESS_TIMEOUT_SEC,
            "env": {"API_KEY": "secret"},
        }
        for call in calls
    )


def test_timeout_is_returned_as_structured_failure() -> None:
    logs: list[tuple[Any, ...]] = []
    original = provider._deps()
    provider.configure_tts_provider_dependencies(
        replace_dependencies(
            write_project_log=lambda *args, **kwargs: logs.append(
                (args, kwargs)
            ),
        )
    )
    def killable_timeout(_args, **_kwargs):
        # run_subprocess_killable 的超时契约：returncode=124 + 结构化 stderr
        return subprocess.CompletedProcess(
            ["tts"],
            124,
            stdout="partial",
            stderr="TTS process timed out after 390s. late",
        )
    try:
        with patch(
            "tts_provider_service.STEP7_TTS_RETRY_ATTEMPTS",
            1,
        ), patch(
            "tts_provider_service.run_subprocess_killable",
            side_effect=killable_timeout,
        ):
            result = provider.run_tts_command_with_retries(
                SimpleNamespace(id="project"),
                "slide_001",
                ["tts"],
                {},
            )
    finally:
        provider.configure_tts_provider_dependencies(original)
    assert result["ok"] is False
    assert result["returncode"] == 124
    assert result["stdout"] == "partial"
    assert result["stderr"] == (
        "TTS process timed out after 390s. late"
    )
    assert result["attempts"] == 1
    assert len(logs) == 1
