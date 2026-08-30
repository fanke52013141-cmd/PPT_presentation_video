from __future__ import annotations

from typing import Any

import comfyui_backend as backend


class _Response:
    def __init__(self, status_code: int, payload: Any = None) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        return self._payload


class _Client:
    def __init__(self, object_info: dict[str, Any]) -> None:
        self.object_info = object_info

    def __enter__(self) -> "_Client":
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def get(self, path: str) -> _Response:
        if path == "/system_stats":
            return _Response(200, {"system": "ok"})
        if path == "/object_info":
            return _Response(200, self.object_info)
        raise AssertionError(path)


def _workflow() -> dict[str, dict[str, Any]]:
    return {
        "1": {"class_type": "BSAI_IndexTTS2.5Loader", "inputs": {}},
        "2": {"class_type": "BSAI_IndexTTS2.5Synthesis", "inputs": {"text": ""}},
        "3": {"class_type": "BSAI_IndexTTS2.5SaveAudio", "inputs": {}},
    }


def test_inspect_tts_preflight_reports_success(monkeypatch) -> None:
    workflow = _workflow()
    monkeypatch.setattr(
        backend,
        "_make_client",
        lambda **_kwargs: _Client(
            {
                "BSAI_IndexTTS2.5Loader": {},
                "BSAI_IndexTTS2.5Synthesis": {},
                "BSAI_IndexTTS2.5SaveAudio": {},
            }
        ),
    )

    result = backend.inspect_tts_preflight(workflow)

    assert result["success"] is True
    assert result["service_reachable"] is True
    assert result["missing_nodes"] == []
    assert result["errors"] == []


def test_inspect_tts_preflight_reports_missing_nodes(monkeypatch) -> None:
    monkeypatch.setattr(
        backend,
        "_make_client",
        lambda **_kwargs: _Client({"BSAI_IndexTTS2.5Synthesis": {}}),
    )

    result = backend.inspect_tts_preflight(_workflow())

    assert result["success"] is False
    assert result["missing_nodes"] == [
        "BSAI_IndexTTS2.5Loader",
        "BSAI_IndexTTS2.5SaveAudio",
    ]
    assert any("缺少工作流节点" in error for error in result["errors"])


def test_inspect_tts_preflight_does_not_call_service_for_invalid_workflow(
    monkeypatch,
) -> None:
    called = False

    def fail_client(**_kwargs):
        nonlocal called
        called = True
        raise AssertionError("invalid workflow must fail before network probe")

    monkeypatch.setattr(backend, "_make_client", fail_client)

    result = backend.inspect_tts_preflight({"1": {"inputs": {}}})

    assert result["success"] is False
    assert called is False
    assert "工作流不是 ComfyUI API 格式" in result["errors"]


def test_inspect_tts_preflight_maps_offline_service(monkeypatch) -> None:
    def fail_client(**_kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(backend, "_make_client", fail_client)

    result = backend.inspect_tts_preflight(_workflow())

    assert result["success"] is False
    assert result["service_reachable"] is False
    assert any("ComfyUI 连接失败" in error for error in result["errors"])
