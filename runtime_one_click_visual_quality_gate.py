"""One-click Step 3 visual draft quality gate.

This additive patch inserts an ``image_quality`` stage immediately after the
One-click ``images`` stage. It reuses ``scripts.check_visual_draft_quality`` so
automation pauses before Step 3 confirmation and Step 5 Mask work when generated
``visual_draft.png`` files are not Mask-friendly.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

PATCH_MARKER = "__ppt_one_click_visual_quality_gate_patch__"
GATE_STAGE_ID = "image_quality"
GATE_STAGE_TITLE = "检查 Step 3 图片质量"
GATE_KEY = "pause_on_visual_draft_quality_failure"


def _run_dir(project: Any) -> Path:
    return Path(str(project.run_dir)).resolve()


def _failure_summaries(report: dict[str, Any], limit: int = 8) -> list[str]:
    summaries: list[str] = []
    for item in report.get("results", []) or []:
        if not isinstance(item, dict):
            continue
        details = item.get("issue_details") if isinstance(item.get("issue_details"), list) else []
        if not details:
            continue
        slide_id = Path(str(item.get("path") or "")).parent.name or "unknown slide"
        for detail in details:
            if not isinstance(detail, dict):
                continue
            title = str(detail.get("title") or detail.get("code") or "图片质量问题").strip()
            message = str(detail.get("message") or "").strip()
            action = str(detail.get("action") or "").strip()
            summary = f"{slide_id}：{title}"
            if message:
                summary += f"；{message}"
            if action:
                summary += f"；建议：{action}"
            summaries.append(summary[:800])
            if len(summaries) >= limit:
                return summaries
    return summaries


def _patch_stages(module: Any) -> None:
    stages = list(getattr(module, "STAGES", []) or [])
    if any(stage_id == GATE_STAGE_ID for stage_id, _title in stages):
        return
    inserted = []
    for stage in stages:
        inserted.append(stage)
        if stage and stage[0] == "images":
            inserted.append((GATE_STAGE_ID, GATE_STAGE_TITLE))
    if not inserted:
        inserted = [(GATE_STAGE_ID, GATE_STAGE_TITLE)]
    module.STAGES = inserted


def _patch_quality_gates(module: Any) -> None:
    gates = getattr(module, "DEFAULT_QUALITY_GATES", None)
    if isinstance(gates, dict):
        gates.setdefault(GATE_KEY, True)


def _run_gate(module: Any, project: Any, status: dict[str, Any]) -> None:
    module._start_stage(project, status, GATE_STAGE_ID, "检查 Step 3 visual_draft.png 是否适合 Step 5 Mask")
    try:
        from scripts.check_visual_draft_quality import check_run_dir

        report = check_run_dir(_run_dir(project))
    except Exception as exc:
        report = {
            "success": False,
            "checked_count": 0,
            "failed_count": 0,
            "results": [],
            "error": f"{type(exc).__name__}: {exc}",
        }

    item = module._stage(status, GATE_STAGE_ID)
    item["quality_report"] = report
    item["progress"] = 1
    module._save_status(project, status)

    if report.get("success") is True:
        module._finish_stage(project, status, GATE_STAGE_ID, f"图片质量检查通过，已检查 {report.get('checked_count', 0)} 张")
        return

    summaries = _failure_summaries(report)
    if not summaries and report.get("error"):
        summaries = [str(report.get("error"))]
    for warning in summaries[:8]:
        module._warn_stage(project, status, GATE_STAGE_ID, warning)

    gates = module._quality_gates(project)
    if gates.get(GATE_KEY, True):
        failed_count = report.get("failed_count", 0)
        checked_count = report.get("checked_count", 0)
        prefix = f"Step 3 图片质量门暂停：{failed_count}/{checked_count} 张图片需要处理"
        detail = "；".join(summaries[:5]) if summaries else "请打开 Step 3 图片质量检查查看详情"
        raise RuntimeError(prefix + "。" + detail)

    module._finish_stage(project, status, GATE_STAGE_ID, "图片质量存在问题，但质量门已关闭，继续执行")


def _patch_finish_stage(module: Any) -> None:
    original = getattr(module, "_finish_stage", None)
    if not callable(original) or getattr(original, PATCH_MARKER, False):
        return

    def patched_finish_stage(project: Any, status: dict[str, Any], stage_id: str, message: str = "", progress: float = 1.0) -> None:
        original(project, status, stage_id, message, progress)
        if stage_id == "images":
            _run_gate(module, project, status)

    setattr(patched_finish_stage, PATCH_MARKER, True)
    setattr(patched_finish_stage, "__wrapped__", original)
    module._finish_stage = patched_finish_stage


def install() -> bool:
    module = importlib.import_module("runtime_one_click_orchestrator")
    if getattr(module, PATCH_MARKER, False):
        return True
    _patch_stages(module)
    _patch_quality_gates(module)
    _patch_finish_stage(module)
    setattr(module, PATCH_MARKER, True)
    return True


def _register(_server_module: Any) -> bool:
    return install()


install()
