"""refresh_reveal_semantic_blocks 的读改写必须整体发生在 reveal 锁内（审查 H-03）。

回归背景：manifest/contract 曾在锁外读取、锁内整体回写，与草稿保存并发时
会基于过期快照覆盖用户刚保存的手动 Mask（丢失更新）。
本测试用记录型锁 + 包装修改，确定性地断言"读取时锁必须已持有"。
"""

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import mask_manifest_service as manifest_service


class RecordingLock:
    def __init__(self) -> None:
        self.held = False

    def __enter__(self) -> "RecordingLock":
        self.held = True
        return self

    def __exit__(self, *_exc) -> bool:
        self.held = False
        return False


def test_refresh_reads_manifest_only_inside_reveal_lock(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / "planning").mkdir(parents=True)
    manifest = {
        "slides": [
            {
                "slide_id": "slide_001",
                "status": "confirmed",
                "groups": [
                    {"id": "g1", "box": {"x": 0, "y": 0, "width": 10, "height": 10}}
                ],
            }
        ]
    }
    contract = {
        "slides": [
            {
                "slide_id": "slide_001",
                "visual_groups": [{"id": "g1", "label": "正文"}],
            }
        ]
    }
    (tmp_path / "reveal_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    (tmp_path / "planning" / "visual_contract.json").write_text(
        json.dumps(contract), encoding="utf-8"
    )

    lock = RecordingLock()
    write_states: list[bool] = []
    original_dependencies = manifest_service._dependencies
    manifest_service.configure_mask_manifest_dependencies(
        manifest_service.MaskManifestDependencies(
            normalize_visual_type=lambda value, **_kwargs: str(value or "text"),
            reveal_lock_for=lambda _project: lock,
            read_contract_slide_ids=lambda _run_dir: ["slide_001"],
            sync_reveal_manifest_to_contract=lambda _project: False,
            storage_slide_file=lambda run_dir, slide_id, filename: (
                Path(run_dir) / "slides" / slide_id / filename
            ),
            write_json_atomic=lambda path, payload: write_states.append(lock.held),
            handle_step_navigation=lambda *_args, **_kwargs: None,
            sync_project_background_color=lambda _project: None,
            write_project_log=lambda *_args, **_kwargs: None,
            apply_storyboard_background=lambda _path: None,
            repo_root=tmp_path,
            python_executable="python",
            build_timeout_sec=1.0,
        )
    )
    project = SimpleNamespace(id="lock-order", run_dir=str(tmp_path))

    read_states: list[bool] = []
    original_loads = manifest_service.json.loads

    def recording_loads(*args, **kwargs):
        read_states.append(lock.held)
        return original_loads(*args, **kwargs)

    monkeypatch.setattr(manifest_service.json, "loads", recording_loads)
    try:
        result, processed = manifest_service.refresh_reveal_semantic_blocks(
            project
        )
    finally:
        manifest_service.configure_mask_manifest_dependencies(
            original_dependencies
        )
        monkeypatch.undo()

    assert processed == 1
    assert result["slides"][0]["slide_id"] == "slide_001"
    # 两次读取（manifest + contract）都必须发生在锁内
    assert read_states == [True, True], read_states
    # 回写同样必须发生在锁内
    assert write_states == [True], write_states
    # 离开临界区后锁已释放
    assert lock.held is False
