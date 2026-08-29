"""repair_step6_result 变更旁白时必须清除音频确认（审查 M-03）。

回归背景：修复路径曾绕过 handle_step_navigation，旁白重写后旧音频确认
状态残留，可能以旧音频渲染新分镜（违反 AGENTS.md 状态生命周期）。
"""

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runtime_support import read_json_file  # noqa: E402

import narration_service as service  # noqa: E402
from narration_audio_service import TTS_MARKUP_RE  # noqa: E402


class FakeQuery:
    def __init__(self, project) -> None:
        self.project = project

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.project


class FakeDb:
    def __init__(self, project) -> None:
        self.project = project

    def query(self, *_args, **_kwargs):
        return FakeQuery(self.project)

    def commit(self):
        pass


def _configure(sync_changed: bool, navigations: list) -> None:
    service.configure_narration_dependencies(
        service.NarrationDependencies(
            beat_tts_text=lambda *a, **k: "",
            clean_json_markdown=lambda *a, **k: a[0] if a else "",
            clean_tts_text=lambda *a, **k: a[0] if a else "",
            ensure_minimax_delivery_markup=lambda *a, **k: "",
            get_openai_client=lambda *a, **k: None,
            handle_step_navigation=lambda project, step, db: navigations.append(step),
            normalize_minimax_tts_markup=lambda *a, **k: "",
            parse_int_setting=lambda *a, **k: 0,
            parse_json_or_repair_with_llm=lambda *a, **k: {},
            persist_narration_beats=lambda *a, **k: None,
            prepare_narration_payload=lambda *a, **k: {},
            read_contract_slide_ids=lambda *a, **k: [],
            read_json_file=read_json_file,
            sync_narration_beats_to_contract=lambda project: sync_changed,
            tts_markup_re=TTS_MARKUP_RE,
        )
    )


def _make_project(tmp_path: Path) -> SimpleNamespace:
    (tmp_path / "planning").mkdir(parents=True, exist_ok=True)
    (tmp_path / "planning" / "narration_beats.json").write_text(
        '{"beats": []}', encoding="utf-8"
    )
    return SimpleNamespace(id="repair-test", run_dir=str(tmp_path))


_INJECTED_NAMES = (
    "TTS_MARKUP_RE",
    "beat_tts_text",
    "clean_json_markdown",
    "clean_tts_text",
    "ensure_minimax_delivery_markup",
    "get_openai_client",
    "handle_step_navigation",
    "normalize_minimax_tts_markup",
    "parse_int_setting",
    "parse_json_or_repair_with_llm",
    "persist_narration_beats",
    "prepare_narration_payload",
    "read_contract_slide_ids",
    "read_json_file",
    "sync_narration_beats_to_contract",
)


def _snapshot() -> dict:
    return {name: getattr(service, name) for name in _INJECTED_NAMES}


def _restore(snapshot: dict) -> None:
    for name, value in snapshot.items():
        setattr(service, name, value)


def test_repair_with_changes_clears_audio_confirmation(tmp_path) -> None:
    project = _make_project(tmp_path)
    navigations: list[int] = []
    saved = _snapshot()
    _configure(sync_changed=True, navigations=navigations)
    try:
        response = service.repair_step6_result(project.id, FakeDb(project))
    finally:
        _restore(saved)

    assert response["success"] is True
    assert response["changed"] is True
    # 旁白被重写 → 必须走与手动编辑相同的导航失效路径
    assert navigations == [6]


def test_repair_without_changes_keeps_confirmation(tmp_path) -> None:
    project = _make_project(tmp_path)
    navigations: list[int] = []
    saved = _snapshot()
    _configure(sync_changed=False, navigations=navigations)
    try:
        response = service.repair_step6_result(project.id, FakeDb(project))
    finally:
        _restore(saved)

    assert response["success"] is True
    assert response["changed"] is False
    assert navigations == []
