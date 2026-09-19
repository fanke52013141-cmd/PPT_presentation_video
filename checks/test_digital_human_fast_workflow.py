from __future__ import annotations

import json
from pathlib import Path

import comfyui_backend as backend


ROOT = Path(__file__).resolve().parents[1]


class _Response:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _Client:
    def __enter__(self) -> "_Client":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def get(self, path: str) -> _Response:
        if path == "/system_stats":
            return _Response(200, {"system": "ok"})
        if path == "/object_info":
            workflow = _workflow()
            payload = {node["class_type"]: {} for node in workflow.values()}
            payload["FrameInterpolationModelLoader"] = {
                "input": {"required": {"model_name": ["COMBO", {"options": ["rife426.pth"]}]}}
            }
            return _Response(200, payload)
        raise AssertionError(path)


def _workflow() -> dict:
    return json.loads(
        (ROOT / "config" / "digital_human_lecturer_fast_workflow.json").read_text(
            encoding="utf-8"
        )
    )


def test_fast_workflow_keeps_480p_quality_and_interpolates_to_25fps() -> None:
    workflow = _workflow()
    assert workflow["213"]["inputs"]["scale_to_length"] == 480
    assert workflow["199"]["inputs"]["steps"] == 4
    assert workflow["198"]["inputs"]["fps"] == 12.5
    assert workflow["223"]["inputs"]["expression"] == "floor(a*12.5)+1"
    assert workflow["242"]["class_type"] == "FrameInterpolate"
    assert workflow["242"]["inputs"]["multiplier"] == 2
    assert workflow["229"]["inputs"]["frame_rate"] == 25
    assert workflow["229"]["inputs"]["images"] == ["242", 0]


def test_fast_workflow_uses_fixed_lecturer_prompt() -> None:
    prompt = _workflow()["135"]["inputs"]["positive_prompt"]
    assert "女性讲师" in prompt
    assert "自然口型同步" in prompt
    assert "说唱" not in prompt


def test_video_preflight_requires_interpolation_weight(monkeypatch) -> None:
    monkeypatch.setattr(backend, "_make_client", lambda **_kwargs: _Client())
    result = backend.inspect_video_preflight(_workflow())
    assert result["success"] is True

    class _MissingWeightClient(_Client):
        def get(self, path: str) -> _Response:
            response = super().get(path)
            if path == "/object_info":
                response._payload["FrameInterpolationModelLoader"]["input"]["required"]["model_name"][1]["options"] = []
            return response

    monkeypatch.setattr(backend, "_make_client", lambda **_kwargs: _MissingWeightClient())
    result = backend.inspect_video_preflight(_workflow())
    assert result["success"] is False
    assert result["missing_models"] == ["rife426.pth"]
